import json
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import Mock
import dots_cli.cli as dots

class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.app=self.base/'ChatGPT.app';(self.app/'Contents').mkdir(parents=True)
        (self.app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'com.openai.codex'}))
        self.run=Mock(return_value=subprocess.CompletedProcess([],0,'',''))
        self.launcher=dots.Launcher(project=dots.PROJECT,runtime=self.base/'runtime',runner=self.run,app=self.app, platform='darwin')

    def test_first_time_setup_needs_no_existing_dot(self):
        result=self.launcher.launch('setup')
        self.assertFalse(result['submitted']);self.assertEqual(result['outcome'],'launch_requested')
        self.assertEqual(self.run.call_args.args[0],['/usr/bin/open','-a',str(self.app),'codex://dots'])
        self.assertEqual(self.launcher.settings()['url'],'')

    def test_setup_uses_web_when_desktop_app_is_missing(self):
        self.launcher.app=self.base/'missing.app';self.launcher.launch('setup')
        self.assertEqual(self.run.call_args.args[0],['/usr/bin/open','https://chatgpt.com/dots'])

    def test_missing_target_does_not_copy_or_launch(self):
        with self.assertRaisesRegex(ValueError,'Save your Dot'):self.launcher.launch('dot','private prompt')
        self.run.assert_not_called();self.assertEqual(self.launcher.history(),[])

    def test_url_validation_rejects_credentials_and_command_schemes(self):
        for value in ['file:///tmp/test','https://chatgpt.com.evil/c/id','https://chatgpt.com@evil/c/id','https://user:pass@chatgpt.com/c/id','https://chatgpt.com/','http://chatgpt.com/c/id','https://chatgpt.com/c/a\nb',17]:
            with self.subTest(value=value),self.assertRaises(ValueError):self.launcher.configure(value)
        self.run.assert_not_called()

    def test_target_and_prompt_are_data_not_shell_commands(self):
        url='https://chatgpt.com/c/example';self.launcher.configure(url)
        prompt='Literal $(touch /tmp/unwanted) `echo nope` \"quote\"\nsecond line'
        result=self.launcher.launch('dot',prompt)
        first,second=self.run.call_args_list
        self.assertEqual(first.args[0],['/usr/bin/pbcopy']);self.assertEqual(first.kwargs['input'],prompt)
        self.assertEqual(second.args[0],['/usr/bin/open',url]);self.assertNotIn('shell',second.kwargs)
        self.assertTrue(result['copied']);self.assertFalse(result['submitted'])
        self.assertNotIn(prompt,(self.base/'runtime/dots-launches.jsonl').read_text(encoding='utf-8'))

    def test_dry_run_has_no_side_effects(self):
        result=self.launcher.launch('app','test',dry_run=True)
        self.assertEqual(len(result['commands']),2);self.run.assert_not_called()
        self.assertFalse((self.base/'runtime').exists())

    def test_partial_failure_is_not_logged_as_success(self):
        self.run.side_effect=[subprocess.CompletedProcess([],0,'',''),subprocess.CompletedProcess([],1,'','failed')]
        with self.assertRaisesRegex(ValueError,'Prompt was copied'):self.launcher.launch('app','test')
        event=self.launcher.history()[0]
        self.assertEqual(event['outcome'],'failed');self.assertTrue(event['copied']);self.assertFalse(event['submitted'])

    def test_bad_actions_and_prompts_do_not_run(self):
        for action,prompt in [('shell','test'),('copy',''),('app','a'*12001),('app',None),('app','a\0b')]:
            with self.subTest(action=action,prompt=str(prompt)[:20]),self.assertRaises(ValueError):self.launcher.launch(action,prompt)
        self.run.assert_not_called()

    def test_presets_come_from_written_project_and_status_does_not_launch(self):
        status=self.launcher.status();self.assertEqual([p['id'] for p in status['presets']],['first','local','followup'])
        self.assertTrue(all(p['text'] for p in status['presets']))
        self.assertIn(str(dots.PROJECT),status['presets'][1]['text']);self.run.assert_not_called()
        self.assertFalse((self.base/'runtime').exists())

    def test_setup_guide_is_distinct_from_opening_chatgpt(self):
        plan=self.launcher.plan('guide');self.assertEqual(plan[0]['argv'],['/usr/bin/open',dots.SETUP_URL])

    def test_configuration_can_be_saved_and_cleared_without_launching(self):
        self.launcher.configure('https://chatgpt.com/c/example');self.assertTrue(self.launcher.settings()['url'])
        self.launcher.configure('');self.assertEqual(self.launcher.settings()['url'],'');self.run.assert_not_called()

if __name__=='__main__':unittest.main()
