"""Check for a newer CLI before updating this installation."""
from pathlib import Path
import os
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.error import URLError
from urllib.request import Request, urlopen
import venv

from . import __version__

SOURCE = 'https://github.com/quivent/Dots/archive/refs/heads/main.zip'
VERSION_URL = 'https://raw.githubusercontent.com/quivent/Dots/main/dots_cli/__init__.py'


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


def update():
    from .ui import console
    # Shell import paths can expose unrelated source distributions to pip.
    environment = {key: value for key, value in os.environ.items()
                   if key not in ('PYTHONPATH', 'PYTHONHOME')}
    try:
        with console.status('Checking for a Dots CLI update…'):
            latest = latest_version()
        if version_key(latest) <= version_key(__version__):
            console.print('Dots CLI ' + __version__ + ' is up to date.', style='green')
            return 0
        console.print('Updating Dots CLI ' + __version__ + ' → ' + latest + '…')
        # pipx environments may have no pip. Keep the disposable installer private
        # and target this interpreter; leave satisfied dependencies alone.
        with console.status('Installing Dots CLI…'), TemporaryDirectory(prefix='dots-update-') as directory:
            venv.EnvBuilder(with_pip=True).create(directory)
            python = Path(directory) / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
            subprocess.run([str(python), '-m', 'pip', 'install', '--quiet', 'pip>=22.3'],
                           check=True, capture_output=True, text=True, timeout=180, env=environment)
            subprocess.run([str(python), '-m', 'pip', '--python', sys.executable,
                            'install', '--upgrade', '--quiet', SOURCE],
                           check=True, capture_output=True, text=True, timeout=300, env=environment)
        result = subprocess.run([sys.executable, '-m', 'dots_cli', '--version'],
                                cwd=Path(sys.executable).parent, check=True,
                                capture_output=True, text=True, timeout=30, env=environment)
        installed = result.stdout.strip().removeprefix('dots ')
        if version_key(installed) < version_key(latest):
            raise ValueError('The installed version did not match the requested update.')
    except (OSError, URLError, ValueError, subprocess.SubprocessError) as error:
        console.print('Dots CLI update failed.', style='yellow')
        if isinstance(error, subprocess.CalledProcessError):
            # Keep failures actionable without flooding the terminal with build logs.
            detail = (error.stderr or error.stdout or str(error)).strip()
            console.print('\n'.join(detail.splitlines()[-12:]), markup=False)
        elif isinstance(error, subprocess.TimeoutExpired):
            console.print('The update timed out. Check your connection and retry dots update.')
        else:
            console.print(str(error), markup=False)
        return 1
    console.print('Dots CLI updated to ' + installed + '.', style='green')
    return 0
