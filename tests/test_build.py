"""Native runtime caching and atomic publication of a checked executable."""
import subprocess
import unittest
from unittest.mock import patch

from cli import build


class BuildCacheTests(unittest.TestCase):
    @patch('cli.build.os.replace')
    @patch('cli.build.shutil.which', return_value='/fake/nuitka')
    @patch('cli.build.subprocess.run')
    def test_cached_runtime_is_unique_and_published_only_after_validation(self, run, compiler, publish):
        build.main()
        first = run.call_args_list[0].args[0]
        warm = run.call_args_list[1].args[0]
        self.assertEqual(warm[1:], ['--version'])
        first_output = next(arg.split('=', 1)[1] for arg in first if arg.startswith('--output-filename='))
        self.assertEqual(warm[0], first_output)
        self.assertNotEqual(first_output, str(publish.call_args.args[1]))
        self.assertEqual(publish.call_args.args[1].name, 'dots')
        self.assertEqual(str(publish.call_args.args[0]), first_output)
        build.main()
        second = run.call_args_list[2].args[0]
        self.assertIn('--onefile-cache-mode=cached', first)
        prefix = '--onefile-tempdir-spec={CACHE_DIR}/Quivent/Dots/'
        cache1 = next(arg for arg in first if arg.startswith(prefix))
        cache2 = next(arg for arg in second if arg.startswith(prefix))
        self.assertNotEqual(cache1, cache2)
        self.assertNotIn('{PID}', cache1)

    @patch('cli.build.os.replace')
    @patch('cli.build.shutil.which', return_value='/fake/nuitka')
    @patch('cli.build.subprocess.run')
    def test_failed_compilation_or_smoke_check_preserves_live_executable(self, run, compiler, publish):
        for results in ([subprocess.CalledProcessError(1, 'compile')],
                        [None, subprocess.CalledProcessError(1, 'validate')]):
            with self.subTest(results=results):
                run.side_effect = results
                with self.assertRaises(subprocess.CalledProcessError):
                    build.main()
                publish.assert_not_called()
