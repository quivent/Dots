"""Unprivileged installation rendezvous; only an owner can bind a team member."""
import hashlib
import json
import logging
import re
import secrets
import time
import uuid


def migrate(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS pending_installations(
      id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
      platform TEXT NOT NULL, build TEXT NOT NULL, created REAL NOT NULL,
      device_id TEXT)''')
    connection.commit()


def digest(token):
    if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43,128}',token):
        raise ValueError('Invalid installation credential')
    return hashlib.sha256(token.encode()).hexdigest()


def register(hub,token,body):
    if set(body)!={'id','name','platform','build'}:
        raise ValueError('Installation id, name, platform and build are required')
    if not isinstance(body['id'],str): raise ValueError('Invalid installation id')
    identity=str(uuid.UUID(body['id']))
    for key,limit in [('name',80),('platform',40),('build',40)]:
        value=body[key]
        if not isinstance(value,str) or not 1<=len(value)<=limit or any(ord(c)<32 for c in value):
            raise ValueError('Invalid installation metadata')
    hashed=digest(token)
    with hub.lock,hub.conn:
        previous=hub.conn.execute('SELECT * FROM pending_installations WHERE id=?',(identity,)).fetchone()
        if previous:
            if not secrets.compare_digest(previous['token_hash'],hashed):
                raise PermissionError('Installation identity is already registered')
            return status(hub,token)
        # New enrollment cannot reclaim an existing/revoked credential or enroll
        # an existing owner credential. This API has no identity assertion.
        if hub.authorized(token) or hub.conn.execute('SELECT 1 FROM devices WHERE token_hash=?',(hashed,)).fetchone():
            raise PermissionError('Use the existing device connection')
        now=time.time()
        count=hub.conn.execute('SELECT COUNT(*) FROM pending_installations WHERE device_id IS NULL AND created>?',(now-86400,)).fetchone()[0]
        if count>=1000:
            raise PermissionError('Installation enrollment capacity reached')
        hub.conn.execute('DELETE FROM pending_installations WHERE device_id IS NULL AND created<?',(now-86400,))
        hub.conn.execute('INSERT INTO pending_installations VALUES(?,?,?,?,?,?,NULL)',
                         (identity,hashed,body['name'],body['platform'],body['build'],now))
    logging.getLogger('dots.installations').warning(json.dumps({'event':'studio.installation.pending','installationId':identity,'platform':body['platform'],'build':body['build']}))
    return status(hub,token)


def status(hub,token):
    row=hub.db('SELECT id,device_id FROM pending_installations WHERE token_hash=?',(digest(token),),one=True)
    if not row:
        raise PermissionError('Unknown installation')
    grant=hub.studio_access(token) if row['device_id'] and hub.authorized(token) else None
    return {'id':row['id'],'state':'approved' if grant and grant.get('capabilities') else ('denied' if row['device_id'] else 'pending'),
            'scope':'hosted','studio_access':grant,'name':'Dots server'}


def listing(hub):
    return hub.db('SELECT id,name,platform,build,created,device_id FROM pending_installations ORDER BY created DESC')


def attach(hub,identity,member_id):
    identity=str(uuid.UUID(identity))
    # Normalizer checks the exact canonical id format; team resolver rechecks
    # lifecycle and the authoritative source. Never trust installation names.
    from studio_access import normalize_grant
    grant=hub.team_studio_grant(normalize_grant(dict(project='fmvisual',capabilities=['crew.read'],crew_member_id=member_id)))
    if not grant or not grant.get('capabilities'):
        raise ValueError('An active registered team member is required')
    with hub.lock,hub.conn:
        row=hub.conn.execute('SELECT * FROM pending_installations WHERE id=?',(identity,)).fetchone()
        if not row:
            return None
        if row['device_id']:
            current=hub.conn.execute('SELECT studio_access,revoked FROM devices WHERE id=?',(row['device_id'],)).fetchone()
            if not current or current['revoked'] or not current['studio_access'] or json.loads(current['studio_access']).get('crew_member_id')!=member_id:
                raise PermissionError('Installation is already attached or revoked')
            return {'id':identity,'device_id':row['device_id'],'crew_member_id':member_id}
        device=str(uuid.uuid4())
        hub.conn.execute('INSERT INTO devices(id,token_hash,name,created,revoked,studio_access) VALUES(?,?,?,?,0,?)',
                         (device,row['token_hash'],row['name'],time.time(),json.dumps(grant)))
        hub.conn.execute('UPDATE pending_installations SET device_id=? WHERE id=?',(device,identity))
    logging.getLogger('dots.installations').warning(json.dumps({'event':'studio.installation.attached','installationId':identity,'deviceId':device,'crewMemberId':member_id}))
    return {'id':identity,'device_id':device,'crew_member_id':member_id}
