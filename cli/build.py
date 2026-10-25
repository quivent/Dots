"""Build the complete Dots CLI as a standalone native executable."""
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import uuid


def main():
    root = Path(__file__).resolve().parent.parent
    compiler = shutil.which('nuitka')
    if not compiler:
        raise SystemExit('Install Nuitka and put nuitka on PATH before building.')
    build = root / 'build' / 'native'
    build.mkdir(parents=True, exist_ok=True)
    output = root / 'dist'
    output.mkdir(parents=True, exist_ok=True)
    entry = build / 'dots.py'
    entry.write_text('from cli.main import main\nraise SystemExit(main())\n', encoding='utf-8')
    guides = runpy.run_path(str(root / 'cli' / 'resources.py'))['GUIDE_FILES']
    # A fresh identity per build prevents stale code/dependency reuse, even when
    # rebuilding the same version. Repeated commands reuse this build's runtime.
    cache_tag = uuid.uuid4().hex
    staged = output / ('.dots-' + cache_tag)
    command = [compiler, '--mode=onefile', '--output-filename=' + str(staged),
               '--onefile-cache-mode=cached',
               '--onefile-tempdir-spec={CACHE_DIR}/Quivent/Dots/' + cache_tag,
               '--output-dir=' + str(build), '--include-package=cli',
               '--nofollow-import-to=cli.build', '--assume-yes-for-downloads']
    command.extend('--include-data-files=' + str(root / name) + '=share/dots/' + name
                   for name in guides)
    environment = dict(os.environ)
    environment['PYTHONPATH'] = str(root) + os.pathsep + environment.get('PYTHONPATH', '')
    try:
        subprocess.run([*command, str(entry)], cwd=root, env=environment, check=True)
        # Validate and warm the new runtime before replacing the live command.
        subprocess.run([str(staged), '--version'], cwd=root, env=environment,
                       capture_output=True, text=True, timeout=30, check=True)
        os.replace(staged, output / 'dots')
    finally:
        staged.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
