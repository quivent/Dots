"""Speech identity tests without inference, R2 writes or production notices."""
import hashlib
from types import SimpleNamespace
import unittest
from crew_voice import Rejected, context, signed_audio


class VoiceTests(unittest.TestCase):
    def setUp(self):
        self.event = 'notice:' + 'a' * 56
        self.record = {'agentId': 'soren', 'nativeSessionId': 'exact-session',
                       'requestId': 'actual-assistant-response', 'agentName': 'Soren', 'createdAt': 1}
        self.notifications = SimpleNamespace(notices={self.event: self.record},
                current=lambda *args: True, payload=lambda _: {'spokenText': 'Hello Jay.'})
        self.state = SimpleNamespace(notifications=self.notifications, data={'agents': {'soren': {'history': {'items': [
            {'id': 'actual-assistant-response', 'role': 'assistant', 'content': {'text': 'This is my **actual reply**, beyond the notification preview.'}}
        ]}}}})
        self.body = {'eventId': self.event, 'agentId': 'soren', 'nativeSessionId': 'exact-session',
                     'textSHA256': hashlib.sha256(b'Hello Jay.').hexdigest()}

    def test_actual_response_and_text_association_survive_service_safe_job_encoding(self):
        value = context(self.state, self.body)
        self.assertEqual(value['source_response_id'], 'actual-assistant-response')
        self.assertEqual(value['text'], 'This is my actual reply, beyond the notification preview.')
        self.assertNotIn('sent a message', value['text'])
        self.assertEqual(value['voice_id'], 'soren-bright-v1')
        self.assertEqual(value, context(self.state, self.body))

    def test_edited_source_gets_new_audio_and_missing_response_cannot_speak_preview(self):
        before = context(self.state, self.body)
        items = self.state.data['agents']['soren']['history']['items']
        items[0]['content']['text'] = 'A corrected response.'
        after = context(self.state, self.body)
        self.assertNotEqual(before['response_id'], after['response_id'])
        self.assertNotEqual(before['source_text_sha256'], after['source_text_sha256'])
        items.clear()
        with self.assertRaises(Rejected): context(self.state, self.body)

    def test_stale_text_session_unknown_notice_and_client_voice_override_rejected(self):
        for update in [{'textSHA256': 'b' * 64}, {'nativeSessionId': 'other'},
                       {'eventId': 'notice:' + 'b' * 56}, {'voice': 'fabio-warm-v1'}]:
            with self.assertRaises(Rejected): context(self.state, self.body | update)
        self.notifications.current = lambda *args: False
        with self.assertRaises(Rejected): context(self.state, self.body)

    def test_foreign_manifest_rejected_before_credentials_or_signed_url_access(self):
        expected = context(self.state, self.body)
        for wrong in [{'response_id': 'other'}, {'crew_id': 'fabio'}, {'text_sha256': 'b' * 64},
                      {'voice_id': 'fabio-warm-v1'}, {'voice_version': 2}]:
            manifest = {'schema': 'crew.speech.v1', 'response_id': expected['response_id'],
                        'crew_id': 'soren', 'text_sha256': expected['speech_text_sha256'],
                        'voice_id': expected['voice_id'], 'voice_version': 1} | wrong
            with self.assertRaises(Rejected): signed_audio(manifest, expected)


if __name__ == '__main__': unittest.main()
