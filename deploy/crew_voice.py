"""Paired owner speech for exact observed notices, using private Garden inference."""
import asyncio
import hashlib
import json
from pathlib import Path
import re

from aiohttp import ClientError, ClientSession, ClientTimeout, web

ORIGIN = 'http://127.0.0.1:18740'
R2 = Path('/etc/dots-hub/voice-r2.json')
VOICES = {'soren': ('soren-bright-v1', 1)}


class Rejected(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def context(state, body):
    if not isinstance(body, dict) or set(body) != {'eventId', 'agentId', 'nativeSessionId', 'textSHA256'}:
        raise Rejected('Invalid speech request.', 400)
    event = body['eventId']
    if not isinstance(event, str) or not re.fullmatch(r'notice:[a-f0-9]{56}', event):
        raise Rejected('Invalid speech event.', 400)
    notices = getattr(state.notifications, 'notices', None)
    if not isinstance(notices, dict):
        raise Rejected('Custom voice notices are not enabled on this server.', 503)
    record = notices.get(event)
    if not record or record['agentId'] != body['agentId'] or record['nativeSessionId'] != body['nativeSessionId']:
        raise Rejected('This speech event no longer matches the conversation.')
    agent, session = record['agentId'], record['nativeSessionId']
    roster = state.data.get('roster', {})
    if not state.notifications.current(agent, session, state.data.get('agents', {}), roster):
        raise Rejected('This crew session changed.')
    profile = VOICES.get(agent)
    if not profile:
        raise Rejected('No custom voice is selected for this member.', 404)
    announcement = state.notifications.payload((event, agent, record['agentName'], record['createdAt']))['spokenText']
    accepted = {hashlib.sha256(announcement.encode()).hexdigest()}
    legacy_titles = {'received': record['agentName'] + ' received your request',
                     'reply': record['agentName'] + ' sent a message',
                     'ready': record['agentName'] + ': crew ready',
                     'completed': record['agentName'] + ': completed',
                     'blocked': record['agentName'] + ': needs attention'}
    if record.get('stage') in legacy_titles:
        legacy = legacy_titles[record['stage']] + '. ' + record['summary']
        accepted.add(hashlib.sha256(legacy.encode()).hexdigest())
    digest = body['textSHA256']
    if digest not in accepted:
        raise Rejected('The spoken text changed.')
    # Notifications identify the event; speech is the author's actual response,
    # never the push title or its 240-character preview.
    source = record.get('messageId') or record['requestId']
    history = state.data.get('agents', {}).get(agent, {}).get('history', {})
    item = next((row for row in history.get('items', [])
                 if row.get('id') == source and row.get('role') == 'assistant'), None)
    if not item or not isinstance(item.get('content', {}).get('text'), str):
        raise Rejected('The original assistant response is unavailable.')
    original = item['content']['text']
    text = original.replace('**', '').replace('`', '').strip()
    if not text or len(text) > 12000:
        raise Rejected('This response is not available for speech.')
    speech_digest = hashlib.sha256(text.encode()).hexdigest()
    job = 'reply-' + hashlib.sha256((source + ':' + speech_digest + ':' + profile[0] + ':' + str(profile[1])).encode()).hexdigest()
    return {'eventId': event, 'agentId': agent, 'nativeSessionId': session,
            'source_response_id': source, 'response_id': job,
            'text_sha256': digest, 'source_text_sha256': hashlib.sha256(original.encode()).hexdigest(),
            'speech_text_sha256': speech_digest,
            'voice_id': profile[0], 'voice_version': profile[1], 'text': text}


def signed_audio(manifest, expected):
    if (manifest.get('schema') != 'crew.speech.v1'
            or manifest.get('response_id') != expected['response_id']
            or manifest.get('crew_id') != expected['agentId']
            or manifest.get('text_sha256') != expected.get('speech_text_sha256', expected['text_sha256'])
            or manifest.get('voice_id') != expected['voice_id']
            or manifest.get('voice_version') != expected['voice_version']):
        raise Rejected('Generated speech identity does not match this response.')
    audio = manifest['audio']
    prefix = 'crew-voice/responses/' + expected['response_id'] + '/'
    if (audio.get('bucket') != 'governor' or not audio.get('key', '').startswith(prefix)
            or '..' in audio['key'].split('/') or audio.get('content_type') != 'audio/mpeg'
            or not isinstance(audio.get('sha256'), str) or not re.fullmatch('[a-f0-9]{64}', audio['sha256'])
            or type(audio.get('bytes')) is not int or not 0 < audio['bytes'] <= 8 * 1024 * 1024):
        raise Rejected('Invalid audio manifest.')
    import boto3
    from botocore.config import Config
    credential = json.loads(R2.read_text())
    client = boto3.client('s3', endpoint_url=credential['endpoint'],
                          aws_access_key_id=credential['accessKeyId'],
                          aws_secret_access_key=credential['secretAccessKey'],
                          config=Config(signature_version='s3v4'), region_name='auto')
    url = client.generate_presigned_url('get_object', Params={'Bucket': audio['bucket'], 'Key': audio['key']}, ExpiresIn=120)
    return {k: audio[k] for k in ['sha256', 'bytes', 'duration_s', 'sample_rate', 'channels']} | {'url': url}


async def generate(expected):
    async with ClientSession(timeout=ClientTimeout(total=10)) as client:
        async with client.post(ORIGIN + '/v1/crew/responses', json={
                'response_id': expected['response_id'], 'voice': expected['voice_id'], 'input': expected['text']}) as response:
            if response.status != 202:
                raise Rejected('The voice service is temporarily unavailable.', 503)
            job = await response.json()
    if (job.get('response_id') != expected['response_id'] or job.get('voice') != expected['voice_id']
            or job.get('text_sha256') != expected.get('speech_text_sha256', expected['text_sha256'])):
        raise Rejected('The voice response changed.')
    result = {k: v for k, v in expected.items() if k != 'text'}
    status = job.get('status')
    if status not in ('queued', 'running', 'complete', 'failed', 'interrupted'):
        raise Rejected('Unknown voice job state.', 503)
    result['status'] = status
    if status == 'complete':
        result['audio'] = await asyncio.to_thread(signed_audio, job['manifest'], expected)
    return result


def install(app, authorized, generator=generate):
    async def speech(request):
        if request.headers.get('Origin') or not await authorized(request):
            raise web.HTTPUnauthorized()
        try:
            if request.content_length is None or request.content_length > 2048:
                raise Rejected('Invalid speech request size.', 413)
            expected = context(request.app['state'], await request.json())
            result = await generator(expected)
            # Revalidate current exact session before handing out a media capability.
            current = context(request.app['state'], {k: expected[k] for k in ['eventId', 'agentId', 'nativeSessionId']} | {'textSHA256': expected['text_sha256']})
            if current['source_text_sha256'] != expected['source_text_sha256']:
                raise Rejected('The original response changed during speech generation.')
            return web.json_response(result, headers={'Cache-Control': 'no-store'})
        except Rejected as error:
            return web.json_response({'error': str(error)}, status=error.status)
        except (ClientError, asyncio.TimeoutError, OSError):
            return web.json_response({'error': 'Custom speech is unavailable. Device speech is still available.'}, status=503)
        except (ValueError, KeyError, TypeError):
            return web.json_response({'error': 'Invalid speech response.'}, status=400)
    app.router.add_post('/v1/vmfactory/voice/responses', speech)
