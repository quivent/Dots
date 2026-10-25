"""Source routing must preserve real Dot identities and never start Codex inference."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cli.api import ApiError, DotClient
from cli.main import Launcher, main
from cli.registry import Registry


PROFILE = {'id': 'provider-dot', 'display_name': 'Pocket', 'messaging_room_id': 'room', 'is_paused': True}


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.launcher = Launcher(project=Path(self.directory.name), runtime=Path(self.directory.name) / 'runtime')
        self.launcher_patch = patch('cli.main.Launcher', return_value=self.launcher)
        self.launcher_patch.start()
        self.addCleanup(self.launcher_patch.stop)
        self.registry = Registry(self.launcher)

    def invoke(self, *args):
        stream = io.StringIO()
        with redirect_stdout(stream), redirect_stderr(stream):
            code = main(list(args))
        return code, stream.getvalue()

    @patch('cli.sources.DotClient')
    @patch('subprocess.Popen')
    def test_default_listing_is_offline_and_does_not_launch_runtime(self, process, client):
        code, text = self.invoke('list', '--json')
        self.assertEqual((code, json.loads(text)), (0, []))
        client.assert_not_called()
        process.assert_not_called()
        self.assertFalse(self.registry.path.exists())

    @patch('cli.sources.DotClient')
    @patch('subprocess.Popen')
    def test_import_then_default_chat_uses_exact_provider_id(self, process, client):
        client.return_value.list.return_value = [PROFILE]
        self.assertEqual(self.invoke('import', '--source', 'chatgpt', '--json')[0], 0)
        with patch('cli.chat.run', return_value=0) as chat:
            self.assertEqual(self.invoke('chat', 'Pocket')[0], 0)
            options, launcher = chat.call_args.args
            self.assertEqual(options.dot, PROFILE['id'])
            self.assertTrue(options.by_id)
            self.assertFalse(options.local)
            self.assertIs(launcher, self.launcher)
        process.assert_not_called()
        client.return_value.request.assert_not_called()
        self.assertEqual(client.return_value.method_calls, [unittest.mock.call.list()])

    @patch('cli.sources.DotClient')
    def test_create_saves_same_dot_used_by_default_chat(self, client):
        client.return_value.list.return_value = []
        client.return_value.create.return_value = PROFILE
        self.assertEqual(self.invoke('create', 'Pocket', '--json')[0], 0)
        self.assertEqual(self.registry.resolve()['remote_id'], PROFILE['id'])
        self.assertEqual(len(self.registry.read()['agents']), 1)
        client.return_value.create.assert_called_once_with('Pocket', additional=False)
        with patch('cli.chat.run', return_value=0) as chat:
            self.assertEqual(self.invoke('chat')[0], 0)
            self.assertEqual(chat.call_args.args[0].dot, PROFILE['id'])
        self.assertEqual(self.invoke('create', 'Pocket', '--json')[0], 1)
        self.assertEqual(client.return_value.create.call_count, 1)

    @patch('cli.sources.DotClient')
    def test_explicit_chatgpt_creation_also_saves_locally(self, client):
        client.return_value.create.return_value = PROFILE
        self.assertEqual(self.invoke('create', 'Pocket', '--source', 'chatgpt', '--first', '--json')[0], 0)
        self.assertEqual(self.registry.resolve('Pocket')['remote_id'], PROFILE['id'])
        client.return_value.create.assert_called_once_with('Pocket', additional=False)
        client.return_value.list.assert_not_called()

    def test_catalog_failure_does_not_reserve_name_or_submit_creation(self):
        client = DotClient('test-token', 'test-account')
        with patch('cli.sources.DotClient', return_value=client), \
                patch.object(client, 'request', side_effect=ApiError('Catalog unreachable')) as request:
            for _ in range(2):
                code, text = self.invoke('create', 'Pocket')
                self.assertEqual(code, 1)
                self.assertIn('Catalog unreachable', text)
                self.assertEqual(self.registry.read()['agents'], [])
            self.assertEqual([call.args for call in request.call_args_list], [('GET', '/tbo')] * 2)

    @patch('cli.sources.DotClient')
    def test_existing_account_dot_selects_additional_creation(self, client):
        client.return_value.list.return_value = [PROFILE]
        client.return_value.create.return_value = {**PROFILE, 'id': 'new', 'display_name': 'Other'}
        self.assertEqual(self.invoke('create', 'Other', '--json')[0], 0)
        client.return_value.list.assert_called_once()
        client.return_value.create.assert_called_once_with('Other', additional=True)

    @patch('cli.sources.DotClient')
    def test_unknown_create_is_reserved_and_not_repeated(self, client):
        client.return_value.create.side_effect = ApiError('Network outcome unknown')
        self.assertEqual(self.invoke('create', 'Pocket')[0], 1)
        self.assertEqual(self.invoke('create', 'Pocket')[0], 1)
        self.assertEqual(client.return_value.create.call_count, 1)
        self.assertEqual(self.registry.resolve('Pocket')['status'], 'creating')
        self.assertEqual(self.registry.resolve('Pocket')['creation_error'], 'Network outcome unknown')
        self.assertIn('creation_started_at', self.registry.resolve('Pocket'))
        with patch('cli.chat.run') as chat:
            self.assertEqual(self.invoke('chat', 'Pocket')[0], 1)
            chat.assert_not_called()

    @patch('cli.sources.DotClient')
    def test_import_recovers_pending_name_without_another_creation(self, client):
        client.return_value.create.side_effect = ApiError('Network outcome unknown')
        self.assertEqual(self.invoke('create', 'Pocket', '--json')[0], 1)
        pending = self.registry.resolve('Pocket')
        client.return_value.request.return_value = PROFILE
        self.assertEqual(self.invoke('import', PROFILE['id'], '--by-id', '--source', 'chatgpt',
                                     '--name', 'Pocket', '--json')[0], 0)
        saved = self.registry.resolve('Pocket')
        self.assertEqual(saved['id'], pending['id'])
        self.assertEqual(saved['remote_id'], PROFILE['id'])
        self.assertEqual(saved['status'], 'saved')
        self.assertNotIn('creation_error', saved)
        self.assertEqual(len(self.registry.read()['agents']), 1)
        self.assertEqual(client.return_value.create.call_count, 1)

    @patch('cli.sources.DotClient')
    def test_rejected_create_removes_reservation(self, client):
        client.return_value.create.side_effect = ApiError('Forbidden', status=403)
        self.assertEqual(self.invoke('create', 'Pocket')[0], 1)
        self.assertEqual(self.registry.read()['agents'], [])

    @patch('cli.sources.DotClient')
    def test_import_is_idempotent_and_preserves_local_alias(self, client):
        client.return_value.resolve.return_value = PROFILE['id']
        client.return_value.request.return_value = PROFILE
        self.assertEqual(self.invoke('import', 'Pocket', '--source', 'chatgpt', '--name', 'Home', '--json')[0], 0)
        client.return_value.list.return_value = [{**PROFILE, 'display_name': 'New provider name'}]
        self.assertEqual(self.invoke('import', '--source', 'chatgpt', '--json')[0], 0)
        self.assertEqual(len(self.registry.read()['agents']), 1)
        self.assertEqual(self.registry.resolve('Home')['provider_name'], 'New provider name')
        if os.name != 'nt':
            self.assertEqual(self.registry.path.stat().st_mode & 0o077, 0)
        saved = self.registry.path.read_text()
        self.assertNotIn('token', saved)
        self.assertNotIn('messages', saved)

    @patch('cli.sources.DotClient')
    def test_use_and_rename_are_local_and_source_specific(self, client):
        pocket = self.registry.remember(PROFILE)
        self.registry.remember({**PROFILE, 'id': 'second', 'display_name': 'Other'})
        self.assertEqual(self.invoke('use', 'Other', '--json')[0], 0)
        self.assertEqual(self.registry.resolve()['remote_id'], 'second')
        self.assertEqual(self.invoke('rename', 'Other', 'Desk', '--json')[0], 0)
        self.assertEqual(self.registry.resolve('Desk')['remote_id'], 'second')
        self.assertEqual(self.invoke('rename', 'Desk', 'Pocket', '--json')[0], 1)
        self.assertEqual(self.registry.resolve('Pocket')['id'], pocket['id'])
        client.assert_not_called()

    @patch('cli.cloud.DotClient')
    def test_root_source_option_still_reaches_account(self, client):
        client.return_value.list.return_value = [PROFILE]
        self.assertEqual(self.invoke('--source', 'chatgpt', 'list', '--json')[0], 0)
        client.return_value.list.assert_called_once()

    @patch('cli.cloud.run', return_value=0)
    def test_saved_pause_and_tasks_route_to_same_provider(self, cloud):
        self.registry.remember(PROFILE)
        for command in ('pause', 'resume', 'tasks', 'activity', 'room'):
            self.assertEqual(self.invoke(command, 'Pocket', '--json')[0], 0)
            args = cloud.call_args.args[0]
            self.assertEqual(args.dot, PROFILE['id'])
            self.assertTrue(args.by_id)
            self.assertEqual(args.source, 'chatgpt')

    @patch('cli.chat.run')
    @patch('cli.hosted.HostedClient')
    def test_hosted_chat_is_blocked_before_credentials_or_inference(self, hub, chat):
        self.registry.remember({'id': 'hosted-wave', 'display_name': 'Wavesmith'}, backend='hosted')
        for args in (('chat', 'Wavesmith'), ('chat', 'Wavesmith', '--source', 'hosted')):
            code, text = self.invoke(*args)
            self.assertEqual(code, 1)
            self.assertIn('Codex allowance', text)
        hub.assert_not_called()
        chat.assert_not_called()

    @patch('cli.sources.DotClient')
    def test_forget_only_removes_local_reference(self, client):
        self.registry.remember(PROFILE)
        self.assertEqual(self.invoke('forget', 'Pocket', '--json')[0], 0)
        self.assertEqual(self.registry.read()['agents'], [])
        client.assert_not_called()

    def test_old_shortcuts_are_explicit_and_do_not_become_agents(self):
        self.launcher.create('Old link', no_open=True)
        self.assertEqual(json.loads(self.invoke('list', '--json')[1]), [])
        code, text = self.invoke('list', '--source', 'shortcuts', '--json')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(text)['dots'][0]['name'], 'Old link')

    def test_local_alias_cannot_conflict_with_explicit_source(self):
        self.assertEqual(self.invoke('list', '--local', '--source', 'chatgpt')[0], 1)


class HostedBoundaryTests(unittest.TestCase):
    @patch('cli.api.credentials')
    @patch('cli.hosted.build_opener')
    def test_hub_only_receives_its_device_credential(self, opener, credentials):
        from cli.hosted import HostedClient
        from unittest.mock import Mock
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({'items': [PROFILE]}).encode()
        opener.return_value.open.return_value = response
        with patch.dict(os.environ, {'DOTS_HUB_URL': 'https://hub.example', 'DOTS_HUB_TOKEN': 'hub-secret',
                                     'DOTS_ACCESS_TOKEN': 'provider-secret', 'DOTS_ACCOUNT_ID': 'account'}):
            self.assertEqual(HostedClient().list()[0]['id'], PROFILE['id'])
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://hub.example/v1/hosted/rooms')
        self.assertEqual(request.get_header('Authorization'), 'Bearer hub-secret')
        self.assertIsNone(request.get_header('Chatgpt-account-id'))
        credentials.assert_not_called()

    @patch('cli.hosted.build_opener')
    def test_hub_client_rejects_inference_sends(self, opener):
        from cli.hosted import HostedClient
        with patch.dict(os.environ, {'DOTS_HUB_URL': 'https://hub.example', 'DOTS_HUB_TOKEN': 'hub-secret'}):
            client = HostedClient()
            with self.assertRaisesRegex(ApiError, 'consume usage'):
                client.request('POST', '/messaging/rooms/hub-agent/messages', {'content': {'text': 'Hi'}})
            opener.return_value.open.assert_not_called()

    def test_hub_rejects_insecure_or_credential_bearing_origins(self):
        from cli.hosted import HostedClient
        for base in ('http://hub.example', 'https://user:secret@hub.example', 'https://hub.example/path', 'https://hub.example?q=x'):
            with self.subTest(base=base), patch.dict(os.environ, {'DOTS_HUB_URL': base}), self.assertRaises(ApiError):
                HostedClient()
