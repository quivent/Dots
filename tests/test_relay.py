import unittest
from unittest.mock import patch

from cli.api import ApiError
from cli.relay import conversation_client, RelayClient


class RelayTests(unittest.TestCase):
    def test_healthy_relay_uses_device_credential_without_account_login(self):
        with patch('cli.relay.Path.read_text', return_value='device-token\n'), \
                patch.object(RelayClient, 'request', return_value={'protocol_version': 1}) as request, \
                patch('cli.api.credentials') as credentials:
            client = conversation_client()
        self.assertIsInstance(client, RelayClient)
        self.assertEqual(client.token, 'device-token')
        request.assert_not_called()
        credentials.assert_not_called()

    def test_unavailable_relay_does_not_switch_account_transport(self):
        with patch('cli.relay.Path.read_text', return_value='device-token'), \
                patch.object(RelayClient, 'request', side_effect=ApiError('Unavailable')), \
                patch('cli.relay.DotClient', return_value='direct'):
            client = conversation_client()
            self.assertIsInstance(client, RelayClient)
            with self.assertRaises(ApiError):
                client.request('GET', '/tbo')

    def test_relay_authorization_failure_is_not_hidden_by_fallback(self):
        with patch('cli.relay.Path.read_text', return_value='device-token'), \
                patch.object(RelayClient, 'request', side_effect=ApiError('Denied', status=401)), \
                patch('cli.relay.DotClient') as direct:
            client = conversation_client()
            with self.assertRaises(ApiError):
                client.request('GET', '/tbo')
        direct.assert_not_called()

    def test_errors_identify_the_transport_and_failed_operation(self):
        with patch('cli.api.DotClient.request', side_effect=ApiError('Not found', status=404)):
            with self.assertRaisesRegex(ApiError, 'Local Dots relay: GET /tbo: Not found') as caught:
                RelayClient('device-token').request('GET', '/tbo')
        self.assertEqual(caught.exception.status, 404)
