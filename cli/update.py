"""Check once, then update using an installer already on this computer."""
from importlib.util import find_spec
from pathlib import Path
import os
import re
import subprocess
import sys
from tempfile import mkstemp
from urllib.error import URLError
from urllib.request import Request, urlopen

from . import __version__
from .install import pip_command

SOURCE = 'https://github.com/quivent/Dots/archive/refs/heads/main.zip'
VERSION_URL = 'https://raw.githubusercontent.com/quivent/Dots/main/cli/__init__.py'


def latest_version():
    request = Request(VERSION_URL, headers={'User-Agent': 'Dots-CLI/' + __version__})
    with urlopen(request, timeout=15) as response:
        source = response.read(4096).decode('utf-8')
    match = re.search(r"^__version__ = ['\"](\d+\.\d+\.\d+)['\"]$", source, re.MULTILINE)
    if not match:
        raise ValueError('The repository did not provide a valid CLI version.')
    return match.group(1)


def version_key(version):
    return tuple(int(part) for part in version.split('.'))


def run_quiet(command, environment, timeout=300):
    return subprocess.run(command, cwd=Path(sys.executable).parent, env=environment,
                          check=True, capture_output=True, encoding='utf-8', errors='replace', timeout=timeout)


def install(environment):
    if find_spec('pip') is None:
        # Bootstrap pip in the existing interpreter when needed.
        run_quiet([sys.executable, '-m', 'ensurepip', '--upgrade'], environment, timeout=120)
    run_quiet(pip_command(SOURCE, upgrade=True), environment)


def report_failure(console, error):
    """Never forward installer output to the terminal, including on errors."""
    if isinstance(error, subprocess.TimeoutExpired):
        message = 'Update timed out. Check your connection and retry dots update.'
    elif isinstance(error, (URLError, ConnectionError)):
        message = 'Could not check for updates. Check your connection and retry dots update.'
    elif isinstance(error, subprocess.CalledProcessError):
        message = 'Update could not be installed. Details are saved in the log below.'
    else:
        message = 'Update could not be completed. Details are saved in the log below.'
    console.print(message, style='yellow')
    try:
        descriptor, filename = mkstemp(prefix='dots-update-', suffix='.log')
        with os.fdopen(descriptor, 'w', encoding='utf-8') as log:
            log.write(str(error) + '\n')
            for detail in (getattr(error, 'stdout', None), getattr(error, 'stderr', None)):
                if detail:
                    log.write(detail.decode('utf-8', errors='replace') if isinstance(detail, bytes) else detail)
                    log.write('\n')
        console.print('Update log: ' + filename, markup=False)
    except OSError:
        console.print('Could not save the update log.', style='dim')


def update():
    from .ui import console
    if '__compiled__' in globals():
        console.print('This is a compiled Dots CLI. To update it, rebuild from your updated checkout with make -C cli binary.', markup=False)
        return 0
    # Shell import paths can expose unrelated source distributions to installers.
    environment = {key: value for key, value in os.environ.items()
                   if key not in ('PYTHONPATH', 'PYTHONHOME')}
    try:
        with console.status('Checking for a Dots CLI update…'):
            latest = latest_version()
        if version_key(latest) <= version_key(__version__):
            console.print('Dots CLI ' + __version__ + ' is up to date.', style='green')
            return 0
        with console.status('Updating Dots CLI ' + __version__ + ' → ' + latest + '…'):
            install(environment)
            result = run_quiet([sys.executable, '-m', 'cli', '--version'], environment, timeout=30)
            installed = result.stdout.strip().removeprefix('dots ')
            if version_key(installed) < version_key(latest):
                raise ValueError('The installed version did not match the requested update.')
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report_failure(console, error)
        return 1
    console.print('Dots CLI updated to ' + installed + '.', style='green')
    return 0
