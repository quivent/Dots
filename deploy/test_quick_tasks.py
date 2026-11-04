"""Isolated quick-capture tests; never write a production task."""
import copy
import json
import unittest
import uuid
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from quick_tasks import GROUP, Rejected, capture, install, validate


def snapshot():
    return {'revision': 4, 'documents': {
        'status.json': json.dumps({'tracks': {'tools': {}}, 'groups': [], 'stages': []}),
        'done.json': json.dumps({'groups': [{'items': [{'id': 'FMV-999'}]}]}),
        'runtime/claims.json': '{"claims":{}}'}}


class CaptureTests(unittest.TestCase):
    def test_capture_is_unassigned_nonexecuting_and_preserves_other_documents(self):
        original = snapshot(); before = copy.deepcopy(original)
        documents, result, changed = capture(original, str(uuid.uuid4()), 'Fix the studio')
        self.assertEqual(original, before)
        self.assertTrue(changed)
        self.assertEqual(result['task_id'], 'FMV-1000')
        self.assertIsNone(result['owner'])
        self.assertEqual(documents['done.json'], before['documents']['done.json'])
        self.assertEqual(documents['runtime/claims.json'], before['documents']['runtime/claims.json'])
        data = json.loads(documents['status.json'])
        self.assertEqual(data['stages'][0]['state'], 'later')
        self.assertEqual(data['stages'][0]['groups'], [GROUP])
        self.assertEqual(data['groups'][0]['items'][0]['touches'], [])

    def test_lost_reply_reuses_receipt_even_after_task_moved_or_edited(self):
        request = str(uuid.uuid4())
        documents, first, _ = capture(snapshot(), request, 'Original')
        current = {'revision': 22, 'documents': documents}
        status = json.loads(documents['status.json'])
        status['groups'][0]['items'][0].update(text='Edited', owner='a-real-member')
        documents['status.json'] = json.dumps(status)
        after, repeated, changed = capture(current, request, 'Original')
        self.assertFalse(changed)
        self.assertEqual(repeated['task_id'], first['task_id'])
        self.assertEqual(json.loads(after['status.json'])['groups'][0]['items'][0]['text'], 'Edited')
        with self.assertRaises(Rejected) as error:
            capture(current, request, 'Different')
        self.assertEqual(error.exception.status, 409)

    def test_rebased_concurrent_captures_have_distinct_canonical_ids(self):
        documents, first, _ = capture(snapshot(), str(uuid.uuid4()), 'A')
        documents, second, _ = capture({'revision': 5, 'documents': documents}, str(uuid.uuid4()), 'B')
        self.assertNotEqual(first['task_id'], second['task_id'])
        status = json.loads(documents['status.json'])
        self.assertEqual([t['text'] for t in status['groups'][0]['items']], ['A', 'B'])

    def test_invalid_names_and_unknown_fields(self):
        for title in ['', ' ', 'a\nb', 'x' * 501, None]:
            with self.assertRaises(Rejected): validate({'request_id': str(uuid.uuid4()), 'title': title})
        with self.assertRaises(Rejected): validate({'request_id': str(uuid.uuid4()), 'title': 'A', 'owner': 'someone'})


class RouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_owner_only_no_origins_and_no_write_for_invalid_input(self):
        calls = []
        async def authorized(request): return request.headers.get('Authorization') == 'Bearer fixture-owner'
        async def writer(identity, title): calls.append((identity, title));return {'task_id': 'FMV-1'}
        app = web.Application();install(app, authorized, writer)
        async with TestClient(TestServer(app)) as client:
            route = '/v1/vmfactory/work/tasks'
            body = {'request_id': str(uuid.uuid4()), 'title': ' Capture '}
            self.assertEqual((await client.post(route, json=body)).status, 401)
            headers = {'Authorization': 'Bearer fixture-owner'}
            self.assertEqual((await client.post(route, headers={**headers, 'Origin': 'https://other'}, json=body)).status, 401)
            self.assertEqual((await client.post(route, headers=headers, json={**body, 'title': ''})).status, 400)
            self.assertEqual(calls, [])
            response = await client.post(route, headers=headers, json=body)
            self.assertEqual(response.status, 200)
            self.assertEqual(calls, [(body['request_id'], 'Capture')])


if __name__ == '__main__': unittest.main()
