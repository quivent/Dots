import io
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

from cli.main import main
from cli.api import ApiError


class RenameTests(unittest.TestCase):
    def invoke(self, *args):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return main(['rename', *args, '--json', '--source', 'chatgpt'])

    @patch('cli.cloud.DotClient')
    def test_name_lookup_and_single_patch(self, client):
        client.return_value.resolve.return_value = 'one'
        client.return_value.path.return_value = '/tbo/one'
        client.return_value.request.return_value = {'display_name': 'New name'}
        self.assertEqual(self.invoke('Terminal', ' New name '), 0)
        client.return_value.resolve.assert_called_once_with('Terminal')
        client.return_value.request.assert_called_once_with('PATCH', '/tbo/one', {'display_name': 'New name'})

    @patch('cli.cloud.DotClient')
    def test_by_id_skips_catalog(self, client):
        client.return_value.path.return_value = '/tbo/one'
        client.return_value.request.return_value = {}
        self.assertEqual(self.invoke('one', 'New', '--by-id'), 0)
        client.return_value.resolve.assert_not_called()
        client.return_value.request.assert_called_once_with('PATCH', '/tbo/one', {'display_name': 'New'})

    @patch('cli.cloud.DotClient')
    def test_invalid_name_never_writes(self, client):
        for name in (' ', 'x' * 81, 'bad\nname'):
            self.assertNotEqual(self.invoke('one', name, '--by-id'), 0)
        client.return_value.request.assert_not_called()

    @patch('cli.cloud.DotClient')
    def test_failed_write_is_not_retried(self, client):
        client.return_value.request.side_effect = ApiError('Outcome unknown')
        self.assertNotEqual(self.invoke('one', 'New', '--by-id'), 0)
        self.assertEqual(client.return_value.request.call_count, 1)
