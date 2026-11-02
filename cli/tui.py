"""Launch the upstream Qwen terminal application with the Dots backend."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .resources import SOURCE_ROOT


def interactive(args, launcher):
    default_root = launcher.project if (launcher.project / 'qwen-code').is_dir() else SOURCE_ROOT
    root = Path(os.environ.get('DOTS_ROOT', str(default_root))).expanduser().resolve()
    qwen = root / 'qwen-code'
    node = shutil.which('node')
    if not node:
        raise ValueError('The Qwen terminal interface requires Node.js 22 or newer.')
    entry = qwen / 'packages/cli/dist/index.js'
    if not entry.is_file():
        raise ValueError('Build the Qwen interface first: cd ' + str(qwen) + ' && npm run build -- --cli-only')
    compiled = '__compiled__' in globals()
    backend_executable = sys.executable
    if compiled:
        # Nuitka's sys.executable can name a nonexistent cached Python binary.
        # Re-enter the installed onefile command through its bridge entry point.
        backend_executable = str(Path(shutil.which(sys.argv[0]) or sys.argv[0]).expanduser().resolve())
        if not Path(backend_executable).is_file():
            raise ValueError('Could not find the installed dots executable.')
    environment = dict(os.environ)
    environment.update(DOTS_BACKEND='1', DOTS_ROOT=str(root),
                       DOTS_PYTHON=backend_executable,
                       DOTS_BRIDGE_BINARY='1' if compiled else '0',
                       DOTS_DOT=args.dot or '',
                       DOTS_BY_ID='1' if args.by_id else '0',
                       DOTS_SOURCE=getattr(args, 'source', 'local') or 'local',
                       DOTS_POLL=str(args.poll),
                       DOTS_DATA_HOME=str(launcher.runtime))
    try:
        return subprocess.run([node, str(entry)], env=environment).returncode
    except KeyboardInterrupt:
        return 130
