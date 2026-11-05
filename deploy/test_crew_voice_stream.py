"""Synthetic HTTP stream tests; no models, artists, R2 or device actions."""
import asyncio
import base64
import hashlib
import json
from types import SimpleNamespace
import unittest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import crew_voice_stream as module

ROUTE = '/v1/vmfactory/voice/responses/stream'
PCM = b'\x01\x00\xff\xff\x00\x00'


def upstream_start(identity='upstream'):
    return {'type': 'start', 'stream_id': identity, 'format': 'pcm_s16le',
            'sample_rate': 24000, 'channels': 1, 'voice': 'server-selected-v2'}


def upstream_audio(sequence=0, identity='upstream'):
    return {'type': 'audio', 'stream_id': identity, 'sequence': sequence,
            'samples': 3, 'pcm_s16le_base64': base64.b64encode(PCM).decode()}


def upstream_end(chunks=1, identity='upstream'):
    return {'type': 'end', 'stream_id': identity, 'chunks': chunks}


class SplitTests(unittest.TestCase):
    def test_short_first_phrase_preserves_text_and_later_capacity(self):
        text = 'A real response should start speaking before its long first sentence has finished rendering. ' * 12
        parts = module.split_text(text, first_limit=64)
        self.assertEqual(''.join(parts), text)
        self.assertLessEqual(len(parts[0]), 64)
        self.assertTrue(parts[0][-1].isspace())
        self.assertTrue(any(len(part) > 64 for part in parts[1:]))
        self.assertEqual(module.split_text('Short reply.', first_limit=64), ['Short reply.'])
        for invalid in [0, True, 601]:
            with self.assertRaises(ValueError):
                module.split_text(text, first_limit=invalid)

    def test_every_unicode_whitespace_character_is_retained(self):
        text = (' Hello.\n  World! 😀e\u0301\t' * 200) + 'x' * 1100 + '\n' * 700
        parts = module.split_text(text)
        self.assertEqual(''.join(parts), text)
        self.assertTrue(all(0 < len(p) <= 600 for p in parts))
        import re
        self.assertTrue(all(len([x for x in re.split(r'(?<=[.!?])\s+', p) if x.strip()]) <= 12 for p in parts))


class StreamTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.text = 'A genuine published reply.\n'
        self.owner = {'Authorization': 'Bearer fixture-owner'}
        self.body = {'eventId': 'notice-fixture', 'agentId': 'fixture-agent',
                     'nativeSessionId': 'fixture-native-session', 'textSHA256': 'a' * 64}
        self.requests, self.resolve_calls = [], []
        self.mode = 'good'
        self.frames = None
        self.first_part = asyncio.Event()
        self.upstream_closed = asyncio.Event()
        self.release_upstream = asyncio.Event()
        self.resolver_error = None
        self.context_generation = 1
        self.maximum_seconds = 2
        self.upstream = TestServer(web.Application(), handler_cancellation=True)
        self.upstream.app.router.add_post('/v1/audio/speech/stream', self.producer)
        await self.upstream.start_server()
        await self.start_gateway()

    async def start_gateway(self):
        self.app = web.Application()
        self.app['state'] = SimpleNamespace()
        async def authorized(request): return request.headers.get('Authorization') == 'Bearer fixture-owner'
        def resolver(state, body, *, max_characters):
            self.resolve_calls.append((body, max_characters))
            if self.resolver_error: raise self.resolver_error
            digest = hashlib.sha256(self.text.encode()).hexdigest()
            return {'eventId': 'notice-fixture', 'agentId': 'fixture-agent',
                    'nativeSessionId': 'fixture-native-session', 'source_response_id': 'actual-reply-id',
                    'response_id': 'service-safe-reply-id', 'text_sha256': 'a' * 64,
                    'source_text_sha256': digest, 'speech_text_sha256': digest,
                    'voice_id': 'server-selected-v2', 'voice_version': 2, 'text': self.text}
        module.install(self.app, authorized, resolver,
                       upstream=str(self.upstream.make_url('')).rstrip('/'), maximum_seconds=self.maximum_seconds)
        # Explicitly use the default cancellation-disabled server. The route must
        # still close its upstream immediately when this client disconnects.
        self.client = TestClient(TestServer(self.app, handler_cancellation=False))
        await self.client.start_server()

    async def asyncTearDown(self):
        self.release_upstream.set()
        await self.client.close()
        await self.upstream.close()

    async def producer(self, request):
        body = await request.json()
        self.requests.append({'body': body, 'authorization': request.headers.get('Authorization')})
        self.first_part.set()
        if self.mode == 'rejected': return web.json_response({'internal': 'not forwarded'}, status=429)
        response = web.StreamResponse(headers={'Content-Type': 'application/x-ndjson'})
        await response.prepare(request)
        if self.mode == 'wait_after_audio':
            await response.write((json.dumps(upstream_start()) + '\n' + json.dumps(upstream_audio()) + '\n').encode())
        if self.mode in ('wait', 'wait_after_audio'):
            try:
                await self.release_upstream.wait()
            except asyncio.CancelledError:
                self.upstream_closed.set()
                raise
        frames = self.frames if self.frames is not None else [upstream_start(), upstream_audio(), upstream_end()]
        payload = b''.join((json.dumps(f) + '\n').encode() for f in frames)
        try:
            # Deliberately cut JSON tokens and base64 payloads across HTTP writes.
            for start in range(0, len(payload), 7): await response.write(payload[start:start + 7])
            await response.write_eof()
            if self.mode == 'source_change': self.text += ' Edited after request.'
        except (ConnectionError, asyncio.CancelledError):
            self.upstream_closed.set()
        return response

    async def fetch(self, body=None, headers=None):
        response = await self.client.post(ROUTE, headers=self.owner if headers is None else headers,
                                          json=self.body if body is None else body)
        raw = await response.read()
        if response.status == 200:
            return response, [json.loads(line) for line in raw.splitlines() if line]
        try: return response, json.loads(raw)
        except ValueError: return response, {'error': raw.decode()}

    async def assert_stream_error(self, frames):
        self.frames = frames
        response, actual = await self.fetch()
        self.assertEqual(response.status, 200)
        self.assertEqual(actual[0]['type'], 'start')
        self.assertEqual(actual[-1]['type'], 'error')
        self.assertFalse(any(f['type'] == 'end' for f in actual))
        return actual

    async def test_segmented_ndjson_preserves_context_and_hashes_actual_pcm(self):
        response, frames = await self.fetch()
        self.assertEqual(response.status, 200)
        first, audio, end = frames
        self.assertEqual(first['voice_id'], 'server-selected-v2')
        self.assertEqual(first['voice_version'], 2)
        self.assertEqual(first['source_response_id'], 'actual-reply-id')
        self.assertEqual(first['text_sha256'], 'a' * 64)  # Compatibility metadata differs from spoken text.
        self.assertEqual(first['format'], 'pcm_s16le')
        self.assertEqual(first['sample_rate'], 24000)
        self.assertEqual(first['channels'], 1)
        self.assertEqual(audio['sequence'], 0)
        self.assertEqual(audio['samples'], 3)
        self.assertEqual(end['chunks'], 1)
        self.assertEqual(end['samples'], 3)
        self.assertEqual(end['audio_bytes'], len(PCM))
        self.assertEqual(end['pcm_sha256'], hashlib.sha256(PCM).hexdigest())
        self.assertTrue(end['complete'])
        self.assertEqual(self.requests[0]['body']['voice'], 'server-selected-v2')
        self.assertEqual(self.requests[0]['body']['model'], 'qwen-base')
        self.assertIsNone(self.requests[0]['authorization'])
        self.assertTrue(all(size == 64000 for _, size in self.resolve_calls))

    async def test_multiple_requests_keep_all_text_and_one_global_sequence(self):
        self.text = ('First sentence.  Second!\n' * 45) + 'end'
        response, frames = await self.fetch(body={'responseId': 'direct-fixture'})
        self.assertEqual(response.status, 200)
        self.assertGreater(len(self.requests), 1)
        self.assertEqual(''.join(r['body']['input'] for r in self.requests), self.text)
        self.assertTrue(all(len(r['body']['input']) <= 600 for r in self.requests))
        audios = [f for f in frames if f['type'] == 'audio']
        self.assertEqual([f['sequence'] for f in audios], list(range(len(audios))))
        self.assertEqual(len({f['stream_id'] for f in frames}), 1)
        self.assertEqual(frames[-1]['pcm_sha256'], hashlib.sha256(PCM * len(self.requests)).hexdigest())

    async def test_auth_origin_and_bad_context_do_not_contact_model(self):
        self.assertEqual((await self.fetch(headers={}))[0].status, 401)
        self.assertEqual((await self.fetch(headers={**self.owner, 'Origin': 'https://external'}))[0].status, 401)
        self.assertEqual((await self.fetch(headers={**self.owner, 'Origin': ''}))[0].status, 401)
        class Rejected(ValueError): status = 409
        self.resolver_error = Rejected('The native session changed.')
        response, body = await self.fetch()
        self.assertEqual(response.status, 409)
        self.assertEqual(body['error'], 'The native session changed.')
        self.assertEqual(self.requests, [])

    async def test_sequence_and_stream_id_mismatch_are_not_success(self):
        for frame in [upstream_audio(1), upstream_audio(identity='other')]:
            await self.assert_stream_error([upstream_start(), frame, upstream_end()])

    async def test_invalid_pcm_base64_and_sample_count_are_not_success(self):
        for update in [{'pcm_s16le_base64': 'not-base64'}, {'samples': 4}, {'sequence': True}, {'sample_rate': 16000}]:
            await self.assert_stream_error([upstream_start(), upstream_audio() | update, upstream_end()])

    async def test_error_missing_end_and_bad_end_counts_are_not_success(self):
        for frames in [[upstream_start(), {'type': 'error', 'message': 'private upstream details'}],
                       [upstream_start(), upstream_audio()],
                       [upstream_start(), upstream_audio(), upstream_end(2)],
                       [upstream_start(), upstream_audio(), upstream_end(), upstream_audio(1)]]:
            actual = await self.assert_stream_error(frames)
            self.assertNotIn('private upstream details', json.dumps(actual))

    async def test_bad_start_format_or_voice_is_rejected(self):
        for update in [{'sample_rate': 16000}, {'channels': 2}, {'format': 'wav'}, {'voice': 'client-selected'}]:
            await self.assert_stream_error([upstream_start() | update, upstream_audio(), upstream_end()])

    async def test_rejected_upstream_produces_error_not_false_end(self):
        self.mode = 'rejected'
        response, frames = await self.fetch()
        self.assertEqual(response.status, 200)
        self.assertEqual([r['type'] for r in frames], ['start', 'error'])

    async def test_disconnect_before_first_pcm_closes_upstream_without_second_request(self):
        self.text = 'word ' * 200
        self.mode = 'wait'
        response = await self.client.post(ROUTE, headers=self.owner, json=self.body)
        self.assertEqual(json.loads(await response.content.readline())['type'], 'start')
        await asyncio.wait_for(self.first_part.wait(), 1)
        response.close()
        await asyncio.wait_for(self.upstream_closed.wait(), 1)
        self.assertEqual(len(self.requests), 1)

    async def test_disconnect_during_pcm_closes_upstream_without_second_request(self):
        self.text = 'word ' * 200
        self.mode = 'wait_after_audio'
        response = await self.client.post(ROUTE, headers=self.owner, json=self.body)
        self.assertEqual(json.loads(await response.content.readline())['type'], 'start')
        self.assertEqual(json.loads(await response.content.readline())['type'], 'audio')
        response.close()
        await asyncio.wait_for(self.upstream_closed.wait(), 1)
        self.assertEqual(len(self.requests), 1)

    async def test_changed_published_source_stops_before_further_requests(self):
        self.text = 'a published sentence. ' * 40
        self.mode = 'source_change'
        response, frames = await self.fetch()
        self.assertEqual(response.status, 200)
        self.assertEqual(frames[-1]['type'], 'error')
        self.assertEqual(frames[-1]['code'], 'source_changed')
        self.assertEqual(len(self.requests), 1)
        self.assertFalse(any(f['type'] == 'end' for f in frames))

    async def test_line_bound_and_duplicate_json_fields(self):
        class Content:
            async def iter_chunked(self, size):
                yield b'{"x":"' + b'a' * 64
        with self.assertRaises(module.StreamFailure):
            async for _ in module.json_lines(Content(), limit=32): pass
        for raw in [b'{"type":"start","type":"audio"}', b'{"samples":NaN}', b'[]']:
            with self.assertRaises(module.StreamFailure): module.parse_json(raw)

    async def test_global_deadline_closes_upstream_and_yields_explicit_error(self):
        await self.client.close()
        self.maximum_seconds = .08
        await self.start_gateway()
        self.mode = 'wait'
        response, frames = await self.fetch()
        self.assertEqual(response.status, 200)
        self.assertEqual(frames[-1]['type'], 'error')
        self.assertEqual(frames[-1]['code'], 'stream_timeout')
        await asyncio.wait_for(self.upstream_closed.wait(), 1)


if __name__ == '__main__': unittest.main()
