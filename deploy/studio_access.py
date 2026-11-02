"""Scoped Studio reads for invited devices; never grants owner or agent control."""
from dataclasses import dataclass
import hashlib
import json
import math

PROJECT = 'fmvisual'
READ_CAPABILITIES = frozenset({'tasks.read', 'crew.read'})
PROTOCOL_FIELDS = ('schema', 'source')
TASK_TEXT_FIELDS = ('id', 'text', 'title', 'state', 'status', 'owner', 'next',
                    'done_when', 'acceptance', 'lane', 'workstream', 'priority',
                    'plan_status', 'queue_scope', 'delivery_stage')
CREW_TEXT_FIELDS = ('id', 'name', 'role', 'roleId', 'roleFocus', 'focus', 'server',
                    'sessionId', 'nativeSessionId', 'teamId', 'locationId', 'lifecycle')
DISPLAY_FIELDS = ('id', 'name', 'title', 'label', 'shortLabel', 'color', 'accent')


def normalize_grant(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {'project', 'capabilities'}:
        raise ValueError('Studio access requires project and read capabilities')
    capabilities = value['capabilities']
    if (value['project'] != PROJECT or not isinstance(capabilities, list)
            or any(not isinstance(c, str) or c not in READ_CAPABILITIES for c in capabilities)
            or len(set(capabilities)) != len(capabilities)):
        raise ValueError('Unknown Studio project or capability')
    return {'project': PROJECT, 'capabilities': sorted(capabilities)}


def stored_grant(value):
    try:
        return normalize_grant(json.loads(value)) if value else None
    except (ValueError, TypeError):
        return None


def migrate_grants(connection):
    """Add columns to the existing auth store; old invitations gain no access."""
    for table in ('invitations', 'devices'):
        if 'studio_access' not in {row[1] for row in connection.execute('PRAGMA table_info(' + table + ')')}:
            connection.execute('ALTER TABLE ' + table + ' ADD COLUMN studio_access TEXT')


def texts(record, keys):
    return {key: record[key] for key in keys
            if isinstance(record.get(key), str) and len(record[key]) <= 32768}


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def visible(record):
    return (isinstance(record, dict) and record.get('ownerOnly') is not True
            and record.get('visibility') not in ('owner', 'private'))


def project_work(work):
    if not isinstance(work, dict) or not isinstance(work.get('tables'), dict):
        return None
    tables = work['tables']
    source = tables.get('tasks', {})
    if not isinstance(source, dict):
        return None
    identities = {key for key, row in source.items() if visible(row)}
    tasks = {}
    for key in sorted(identities):
        row = source[key]
        public = texts(row, TASK_TEXT_FIELDS)
        for name in ('execution_order', 'lane_order', 'plan_order'):
            if number(row.get(name)):
                public[name] = row[name]
        for name in ('depends_on', 'dependsOn'):
            if isinstance(row.get(name), list):
                public[name] = [i for i in row[name] if isinstance(i, str) and i in identities]
        contract = row.get('work_contract')
        if isinstance(contract, dict):
            public['work_contract'] = texts(contract, ('lane_title', 'lane_owner'))
        reconciliation = row.get('assignment_reconciliation')
        if isinstance(reconciliation, dict):
            public['assignment_reconciliation'] = texts(reconciliation, ('counting_role',))
            references = reconciliation.get('canonical_task_ids', [])
            if isinstance(references, list):
                public['assignment_reconciliation']['canonical_task_ids'] = [i for i in references if isinstance(i, str) and i in identities]
        outcome = row.get('outcome_progress')
        if isinstance(outcome, dict):
            public['outcome_progress'] = texts(outcome, ('unit',))
            for name in ('verified_count', 'defined_count', 'unverified_count'):
                if number(outcome.get(name)) and outcome[name] >= 0:
                    public['outcome_progress'][name] = outcome[name]
        tasks[key] = public
    runs = {}
    source_runs = tables.get('runs') if isinstance(tables.get('runs'), dict) else {}
    for key, row in source_runs.items():
        if not isinstance(row, dict) or row.get('task_id') not in identities:
            continue
        public = texts(row, ('run_id', 'task_id', 'phase', 'agent', 'reported_agent'))
        if number(row.get('accepted_epoch')):
            public['accepted_epoch'] = row['accepted_epoch']
        runs[key] = public
    lanes = {}
    source_lanes = tables.get('lanes') if isinstance(tables.get('lanes'), dict) else {}
    for key, row in source_lanes.items():
        if not isinstance(row, dict):
            continue
        public = texts(row, ('id', 'title'))
        for name in ('active', 'waiting', 'blocked'):
            members = row.get(name, [])
            if not isinstance(members, list):
                members = []
            ids = [m if isinstance(m, str) else m.get('task_id', m.get('id'))
                   for m in members if isinstance(m, (str, dict))]
            public[name] = [i for i in ids if isinstance(i, str) and i in identities]
        public['active_count'] = len(public['active'])
        if isinstance(row.get('front_task_id'), str) and row['front_task_id'] in identities:
            public['front_task_id'] = row['front_task_id']
        lanes[key] = public
    result = texts(work, ('schema', 'source'))
    for name in ('revision', 'updated_epoch'):
        if number(work.get(name)):
            result[name] = work[name]
    result.update(snapshot=True, tables={'tasks': tasks, 'runs': runs, 'lanes': lanes, 'workers': {}})
    return result


def project_roster(roster, agents):
    roster = roster if isinstance(roster, dict) else {}
    rows = roster.get('crew', [])
    if not isinstance(rows, list):
        rows = []
    crew = []
    public_agents = {}
    for row in rows:
        if not visible(row) or not isinstance(row.get('id'), str):
            continue
        public = texts(row, CREW_TEXT_FIELDS)
        if number(row.get('displayOrder')):
            public['displayOrder'] = row['displayOrder']
        crew.append(public)
        raw = agents.get(row['id'], {}) if isinstance(agents, dict) else {}
        agent = dict(texts(raw, CREW_TEXT_FIELDS), **public)
        for key in ('relayOnline', 'sessionLoaded'):
            if isinstance(raw.get(key), bool):
                agent[key] = raw[key]
        agent['capabilities'] = {'boundInput': False, 'inspect': False}
        public_agents[row['id']] = agent
    result = texts(roster, ('schema', 'session'))
    result['crew'] = crew
    for name in ('groups', 'locations'):
        values = roster.get(name)
        if isinstance(values, list):
            result[name] = []
            for row in values:
                if not isinstance(row, dict):
                    continue
                public = texts(row, DISPLAY_FIELDS)
                for key in ('order', 'displayOrder'):
                    if number(row.get(key)):
                        public[key] = row[key]
                result[name].append(public)
    return result, public_agents


@dataclass(frozen=True)
class StudioAccess:
    capabilities: frozenset = frozenset()
    owner: bool = False

    @classmethod
    def owner_access(cls):
        return cls(READ_CAPABILITIES, True)

    @classmethod
    def from_health(cls, health):
        if not isinstance(health, dict) or health.get('scope') != 'hosted':
            return None
        try:
            grant = normalize_grant(health.get('studio_access'))
        except ValueError:
            return None
        if not grant or not grant['capabilities']:
            return None
        return cls(frozenset(grant['capabilities']))

    @property
    def key(self):
        return PROJECT + ':' + ','.join(sorted(self.capabilities))

    def metadata(self):
        return {'schema': 'fmvision.studio-access/1', 'project': PROJECT,
                'capabilities': sorted(self.capabilities),
                'role': 'owner' if self.owner else 'reader', 'ownerControls': self.owner}

    def snapshot(self, source):
        if self.owner:
            return dict(source, studioAccess=self.metadata())
        result = texts(source, PROTOCOL_FIELDS)
        result['studioAccess'] = self.metadata()
        if 'tasks.read' in self.capabilities:
            work = project_work(source.get('work'))
            if work is not None:
                result['work'] = work
        if 'crew.read' in self.capabilities:
            result['roster'], result['agents'] = project_roster(source.get('roster'), source.get('agents'))
        return result


def view_digest(snapshot):
    # A private chat or global wire counter cannot change a reader's ETag.
    value = {k: v for k, v in snapshot.items() if k not in ('revision', 'wireSequence', 'sequence', 'epoch')}
    if isinstance(value.get('work'), dict):
        value['work'] = {k: v for k, v in value['work'].items() if k not in ('revision', 'updated_epoch')}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
