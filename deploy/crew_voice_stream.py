"""Owner-authenticated PCM streaming from Garden, without jobs or status polling."""
import asyncio
import base64
import binascii
from contextlib import contextmanager
import hashlib
import inspect
import json
import re
import time
import uuid

from aiohttp import ClientError, ClientSession, ClientTimeout, web

ORIGIN = 'http://127.0.0.1:18740'
MAX_TEXT = 64000
MAX_PART = 480  # Below Garden's 600-character input ceiling.
MAX_LINE = 4 * 1024 * 1024
MAX_SAMPLES_PER_FRAME = 24000 * 45
MAX_DURATION = 1800
RATE = 24000
CONTEXT_KEYS = ('eventId', 'agentId', 'nativeSessionId', 'source_response_id',
                'response_id', 'text_sha256', 'source_text_sha256',
                'speech_text_sha256', 'voice_id', 'voice_version')


class StreamFailure(ValueError):
    def __init__(self, code, message='The voice stream could not finish.', status=502):
        super().__init__(message)
        self.code, self.status = code, status


def split_text(text, limit=MAX_PART):
    """Preserve every character and respect Garden's twelve-sentence ceiling."""
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
        raise StreamFailure('invalid_text', 'The response cannot be spoken.', 413)
    if type(limit) is not int or not 1 <= limit <= 600:
        raise ValueError('Invalid input-part limit')
    parts, start = [], 0
    while start < len(text):
        end = min(start + limit, len(text))
        candidate = text[start:end]
        boundaries = list(re.finditer(r'(?<=[.!?])\s+', candidate))
        if len([x for x in re.split(r'(?<=[.!?])\s+', candidate) if x.strip()]) > 12:
            end = start + boundaries[11].end()
        parts.append(text[start:end])
        start = end
    assert ''.join(parts) == text and all(0 < len(p) <= 600 for p in parts)
    return parts


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON field')
        result[key] = value
    return result


def parse_json(raw):
    def invalid_constant(_):
        raise ValueError('Nonfinite JSON number')
    try:
        value = json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid_constant)
        if not isinstance(value, dict):
            raise ValueError('Expected JSON object')
        return value
    except (ValueError, UnicodeError, RecursionError) as error:
        raise StreamFailure('invalid_upstream') from error


async def json_lines(content, limit=MAX_LINE):
    """HTTP chunks can end anywhere; at most one bounded NDJSON line is retained."""
    pending = bytearray()
    async for block in content.iter_chunked(16384):
        pending.extend(block)
        while True:
            position = pending.find(b'\n')
            if position < 0:
                break
            if position > limit:
                raise StreamFailure('upstream_line_too_large')
            line = bytes(pending[:position])
            del pending[:position + 1]
            if line.strip():
                yield parse_json(line)
        if len(pending) > limit:
            raise StreamFailure('upstream_line_too_large')
    if pending.strip():
        yield parse_json(bytes(pending))


def validate_context(value):
    if not isinstance(value, dict) or any(k not in value for k in (*CONTEXT_KEYS, 'text')):
        raise StreamFailure('invalid_context', status=503)
    for key in CONTEXT_KEYS:
        if key == 'voice_version':
            if type(value[key]) is not int or value[key] < 1:
                raise StreamFailure('invalid_context', status=503)
        elif not isinstance(value[key], str) or not 0 < len(value[key]) <= 512:
            raise StreamFailure('invalid_context', status=503)
    for key in ('text_sha256', 'source_text_sha256', 'speech_text_sha256'):
        if not re.fullmatch('[0-9a-f]{64}', value[key]):
            raise StreamFailure('invalid_context', status=503)
    split_text(value['text'])
    try:
        digest = hashlib.sha256(value['text'].encode()).hexdigest()
    except UnicodeError as error:
        raise StreamFailure('invalid_context', status=503) from error
    if value['speech_text_sha256'] != digest:
        raise StreamFailure('speech_text_changed', status=409)
    return value


@contextmanager
def disconnected(request):
    """Route-local close signal, even with aiohttp handler_cancellation disabled.

    aiohttp 3.9 calls Request._cancel on connection loss irrespective of its
    global handler-cancellation option. Observe that one request's callback;
    restore it afterward. Other routes and server cancellation policy are intact.
    """
    future = asyncio.get_running_loop().create_future()
    original = request._cancel
    had_instance_value = '_cancel' in request.__dict__
    previous = request.__dict__.get('_cancel')
    def closed(error):
        if not future.done():
            future.set_result(None)
        original(error)
    request._cancel = closed
    try:
        if request.transport is None or request.transport.is_closing():
            future.set_result(None)
        yield future
    finally:
        if request.__dict__.get('_cancel') is closed:
            if had_instance_value:
                request._cancel = previous
            else:
                del request._cancel
        if not future.done():
            future.cancel()


async def run_until_closed(request, operation):
    with disconnected(request) as closed:
        task = asyncio.create_task(operation)
        try:
            done, _ = await asyncio.wait((task, closed), return_when=asyncio.FIRST_COMPLETED)
            if closed in done:
                raise ConnectionResetError('Voice client disconnected')
            return await task
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def read_body(request):
    if request.content_length is not None and request.content_length > 8192:
        raise StreamFailure('invalid_request', 'Speech request is too large.', 413)
    raw = bytearray()
    async for block in request.content.iter_chunked(4096):
        raw.extend(block)
        if len(raw) > 8192:
            raise StreamFailure('invalid_request', 'Speech request is too large.', 413)
    try:
        return parse_json(bytes(raw))
    except StreamFailure as error:
        raise StreamFailure('invalid_request', 'Invalid speech request.', 400) from error


def install(app, authorized, resolver, *, upstream=ORIGIN, maximum_seconds=MAX_DURATION):
    async def resolve(request, body):
        value = resolver(request.app['state'], body, max_characters=MAX_TEXT)
        if inspect.isawaitable(value):
            value = await value
        return validate_context(value)

    async def stream(request):
        if 'Origin' in request.headers or not await authorized(request):
            raise web.HTTPUnauthorized()
        try:
            body = await read_body(request)
            expected = await resolve(request, body)
            parts = split_text(expected['text'])
        except Exception as error:
            status = getattr(error, 'status', 503)
            status = status if type(status) is int and 400 <= status <= 599 else 503
            message = str(error)[:300] if hasattr(error, 'status') else 'Speech is temporarily unavailable.'
            return web.json_response({'error': message}, status=status, headers={'Cache-Control': 'no-store'})

        identity = {k: expected[k] for k in CONTEXT_KEYS}
        stream_id = uuid.uuid4().hex
        response = web.StreamResponse(headers={'Content-Type': 'application/x-ndjson',
                'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})
        started = time.monotonic()
        sequence = samples = audio_bytes = 0
        digest = hashlib.sha256()
        first_audio = None

        async def emit(frame):
            if request.transport is None or request.transport.is_closing():
                raise ConnectionResetError('Voice client disconnected')
            await response.write((json.dumps(frame, separators=(',', ':'), allow_nan=False) + '\n').encode())

        async def fresh():
            value = await resolve(request, body)
            if any(value[k] != expected[k] for k in CONTEXT_KEYS) or value['text'] != expected['text']:
                raise StreamFailure('source_changed', 'The conversation changed; speech stopped.', 409)

        async def pump():
            nonlocal sequence, samples, audio_bytes, first_audio
            await response.prepare(request)
            await emit({'type': 'start', 'stream_id': stream_id, **identity,
                        'mode': 'sentence', 'format': 'pcm_s16le', 'sample_rate': RATE,
                        'channels': 1, 'parts': len(parts)})
            timeout = ClientTimeout(total=None, connect=10, sock_read=60)
            async with ClientSession(timeout=timeout) as client:
                for part in parts:
                    await fresh()
                    if request.transport is None or request.transport.is_closing():
                        raise ConnectionResetError('Voice client disconnected')
                    payload = {'model': 'qwen-base', 'voice': expected['voice_id'],
                               'input': part, 'max_new_tokens': 512}
                    async with client.post(upstream + '/v1/audio/speech/stream', json=payload) as incoming:
                        if incoming.status != 200:
                            raise StreamFailure('upstream_rejected')
                        if incoming.content_type != 'application/x-ndjson':
                            raise StreamFailure('invalid_upstream')
                        current_id, local_sequence, ended = None, 0, False
                        async for frame in json_lines(incoming.content):
                            if ended:
                                raise StreamFailure('data_after_upstream_end')
                            kind = frame.get('type')
                            if kind == 'start':
                                sid = frame.get('stream_id')
                                if (current_id is not None or not isinstance(sid, str)
                                        or not re.fullmatch('[A-Za-z0-9_-]{1,128}', sid)
                                        or frame.get('format') != 'pcm_s16le'
                                        or frame.get('sample_rate') != RATE or type(frame.get('sample_rate')) is not int
                                        or frame.get('channels') != 1 or type(frame.get('channels')) is not int
                                        or frame.get('voice') != expected['voice_id']):
                                    raise StreamFailure('invalid_upstream_start')
                                current_id = sid
                            elif kind == 'audio':
                                if (current_id is None or frame.get('stream_id') != current_id
                                        or type(frame.get('sequence')) is not int or frame['sequence'] != local_sequence
                                        or type(frame.get('samples')) is not int
                                        or not 0 < frame['samples'] <= MAX_SAMPLES_PER_FRAME):
                                    raise StreamFailure('invalid_upstream_audio')
                                encoded = frame.get('pcm_s16le_base64')
                                if not isinstance(encoded, str) or len(encoded) > MAX_LINE:
                                    raise StreamFailure('invalid_upstream_audio')
                                try:
                                    pcm = base64.b64decode(encoded, validate=True)
                                except (ValueError, binascii.Error) as error:
                                    raise StreamFailure('invalid_upstream_audio') from error
                                if len(pcm) != frame['samples'] * 2:
                                    raise StreamFailure('invalid_upstream_sample_count')
                                for key, wanted in [('format', 'pcm_s16le'), ('sample_rate', RATE), ('channels', 1)]:
                                    if key in frame and (frame[key] != wanted or type(frame[key]) is not type(wanted)):
                                        raise StreamFailure('invalid_upstream_audio_format')
                                if audio_bytes + len(pcm) > RATE * 2 * maximum_seconds or sequence >= 16384:
                                    raise StreamFailure('stream_limit')
                                await fresh()
                                await emit({'type': 'audio', 'stream_id': stream_id,
                                            'sequence': sequence, 'samples': frame['samples'],
                                            'pcm_s16le_base64': encoded})
                                if first_audio is None:
                                    first_audio = time.monotonic() - started
                                digest.update(pcm)
                                audio_bytes += len(pcm); samples += frame['samples']
                                sequence += 1; local_sequence += 1
                            elif kind == 'end':
                                if (current_id is None or frame.get('stream_id') != current_id
                                        or type(frame.get('chunks')) is not int or frame['chunks'] != local_sequence
                                        or (not local_sequence and part.strip())):
                                    raise StreamFailure('invalid_upstream_end')
                                ended = True
                            elif kind == 'error':
                                raise StreamFailure('upstream_error')
                            else:
                                raise StreamFailure('invalid_upstream')
                        if not ended:
                            raise StreamFailure('upstream_incomplete')
            await fresh()
            await emit({'type': 'end', 'stream_id': stream_id, 'complete': True,
                        'chunks': sequence, 'samples': samples, 'audio_bytes': audio_bytes,
                        'pcm_sha256': digest.hexdigest(), 'parts': len(parts),
                        'first_audio_s': first_audio, 'elapsed_s': time.monotonic() - started})
            await response.write_eof()

        try:
            async with asyncio.timeout(maximum_seconds):
                await run_until_closed(request, pump())
        except asyncio.CancelledError:
            raise
        except (ConnectionError, ClientError):
            if response.prepared:
                try:
                    await emit({'type': 'error', 'stream_id': stream_id, 'code': 'connection_lost',
                                'message': 'The voice connection ended before completion.'})
                    await response.write_eof()
                except (ConnectionError, RuntimeError):
                    pass
        except Exception as error:
            if response.prepared:
                try:
                    await emit({'type': 'error', 'stream_id': stream_id,
                                'code': error.code if isinstance(error, StreamFailure) else
                                        'stream_timeout' if isinstance(error, TimeoutError) else 'stream_failed',
                                'message': str(error) if isinstance(error, StreamFailure) else 'The voice stream could not finish.'})
                    await response.write_eof()
                except (ConnectionError, RuntimeError):
                    pass
            else:
                return web.json_response({'error': 'The voice stream could not start.'}, status=503)
        return response

    app.router.add_post('/v1/vmfactory/voice/responses/stream', stream)
