"""Speech identity tests without inference, R2 writes or production notices."""
import hashlib
from types import SimpleNamespace
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from crew_voice import Rejected, context, signed_audio


class VoiceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        configured = patch('crew_voice.ASSIGNMENTS', Path(temp.name) / 'assignments.json')
        configured.start();self.addCleanup(configured.stop)
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

    def test_visible_conversation_uses_exact_completed_response_without_a_notice(self):
        text = self.state.data['agents']['soren']['history']['items'][0]['content']['text']
        body = {'agentId': 'soren', 'nativeSessionId': 'exact-session',
                'responseId': 'actual-assistant-response', 'textSHA256': hashlib.sha256(text.encode()).hexdigest()}
        self.notifications.notices.clear()
        value = context(self.state, body)
        self.assertEqual(value['eventId'], 'response:actual-assistant-response')
        self.assertEqual(value['source_response_id'], 'actual-assistant-response')
        with self.assertRaises(Rejected): context(self.state, body | {'textSHA256': 'b' * 64})
        with self.assertRaises(Rejected): context(self.state, body | {'responseId': 'other'})

    def test_other_crew_profile_requires_actual_service_activation(self):
        import json
        import crew_voice
        item = self.state.data['agents']['soren']['history']['items'][0]
        self.state.data['agents']['atlas'] = {'history': {'items': [item]}}
        body = {'agentId': 'atlas', 'nativeSessionId': 'exact-session',
                'responseId': item['id'], 'textSHA256': hashlib.sha256(item['content']['text'].encode()).hexdigest()}
        row = {'crew_id': 'atlas', 'voice_id': 'crew-atlas-v1', 'voice_version': 1, 'serviceActivated': False}
        crew_voice.ASSIGNMENTS.write_text(json.dumps({'schema': 'crew.voice-assignments/1', 'profiles': [row]}))
        with self.assertRaises(Rejected): context(self.state, body)
        row['serviceActivated'] = True
        crew_voice.ASSIGNMENTS.write_text(json.dumps({'schema': 'crew.voice-assignments/1', 'profiles': [row]}))
        self.assertEqual(context(self.state, body)['voice_id'], 'crew-atlas-v1')

    def test_server_voice_change_keeps_inflight_reply_and_applies_to_next_reply(self):
        import sqlite3
        from crew_voice import pin_profile
        self.state.db = sqlite3.connect(':memory:');self.addCleanup(self.state.db.close)
        self.state.db.execute('CREATE TABLE crew_speech_profile_pins(key TEXT PRIMARY KEY,voice TEXT,version INTEGER,created REAL)')
        self.assertEqual(pin_profile(self.state, 'soren', 'session', 'reply-one', 'hash', ('bright', 1)), ('bright', 1))
        self.assertEqual(pin_profile(self.state, 'soren', 'session', 'reply-one', 'hash', ('grounded', 2)), ('bright', 1))
        self.assertEqual(pin_profile(self.state, 'soren', 'session', 'reply-two', 'hash', ('grounded', 2)), ('grounded', 2))
        self.assertEqual(pin_profile(self.state, 'soren', 'new-session', 'reply-one', 'hash', ('grounded', 2)), ('grounded', 2))

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
