"""Installation policy shared by make and the updater."""
import subprocess
import sys


def pip_command(source, upgrade=False):
    command = [sys.executable, '-m', 'pip', '--disable-pip-version-check', 'install', '--quiet']
    if sys.prefix == sys.base_prefix:
        command.extend(('--user', '--break-system-packages'))
    if upgrade:
        command.append('--upgrade')
    return [*command, source]


if __name__ == '__main__':
    raise SystemExit(subprocess.call(pip_command(sys.argv[1])))
