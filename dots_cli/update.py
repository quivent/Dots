"""Update this installation from the project's public source distribution."""
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import venv

SOURCE = 'https://github.com/quivent/Dots/archive/refs/heads/main.zip'


def update():
    from .ui import console
    console.print('Updating Dots CLI from quivent/Dots (main)…')
    # A disposable installer also works with pipx environments that contain no pip.
    # --python targets this installation, rather than whichever pip is on PATH.
    try:
        with TemporaryDirectory(prefix='dots-update-') as directory:
            builder = venv.EnvBuilder(with_pip=True)
            builder.create(directory)
            python = Path(directory) / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
            subprocess.run([str(python), '-m', 'pip', 'install', '--upgrade', 'pip>=22.3'], check=True)
            subprocess.run([str(python), '-m', 'pip', '--python', sys.executable,
                            'install', '--upgrade', '--force-reinstall', '--no-cache-dir', SOURCE], check=True)
        subprocess.run([sys.executable, '-m', 'dots_cli', '--version'],
                       cwd=Path(sys.executable).parent, check=True)
    except (OSError, subprocess.SubprocessError) as error:
        console.print('Update failed. Resolve the installer error above, then retry dots update.', style='yellow')
        if isinstance(error, OSError):
            console.print(str(error), markup=False)
        return 1
    console.print('Dots CLI updated.', style='green')
    return 0
