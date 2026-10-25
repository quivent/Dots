"""Read-only setup preflight and broader troubleshooting diagnostics."""
import os
import platform
import sys

from . import __version__
from . import api
from .auth import executable
from .resources import GUIDE_FILES


def preflight(launcher):
    try:
        result = launcher.local_readiness()
    except (OSError, ValueError) as error:
        result = {'project': str(launcher.project), 'local_error': str(error)}
    token, account, source = api.credentials()
    result.update(credential_source=source, authenticated=False, read_access_verified=False,
                  write_access_verified=False, connection='auth_required')
    if token and account:
        try:
            entries = api.DotClient(token, account).list()
            result.update(authenticated=True, read_access_verified=True, dot_count=len(entries), connection='ready')
        except api.ApiError as error:
            result.update(connection='error', connection_error=str(error))
    if result.get('local_error'):
        result['error'] = True
    return result


def doctor(launcher):
    result = preflight(launcher)
    details = []
    def inspect(name, function):
        try:
            state, detail = function()
        except (OSError, ValueError) as error:
            state, detail = 'error', str(error)
        details.append({'check': name, 'state': state, 'detail': detail})
    inspect('Runtime', lambda: ('ready', str(launcher.runtime)))
    inspect('Settings', lambda: ('ready', str(len(launcher.settings()['dots'])) + ' saved shortcuts; configuration parses'))
    def saved_dots():
        from .registry import Registry
        registry = Registry(launcher)
        return 'ready', str(len(registry.read()['agents'])) + ' saved Dot identities; ' + str(registry.path)
    inspect('Saved Dots', saved_dots)
    inspect('History', lambda: ('ready', str(len(launcher.history())) + ' recent launch records parse'))
    inspect('App server', lambda: ('ready', path) if (path := executable()) else ('optional', 'Not found; needed for first-party sign-in'))
    inspect('Clipboard', lambda: ('ready', launcher.clipboard_command('')['argv'][0]))
    def assets():
        missing = [name for name in GUIDE_FILES if not launcher.resource(name).is_file()]
        return ('error', 'Missing: ' + ', '.join(missing)) if missing else ('ready', 'All guide and prompt resources available')
    inspect('Guide assets', assets)
    def notes():
        path = launcher.runtime / 'dots-trials.md'
        if path.is_symlink():
            return 'error', 'Private notes path is a symlink'
        if not path.exists():
            return 'ready', 'No private notes file created'
        if os.name != 'nt' and path.stat().st_mode & 0o077:
            return 'error', 'Private notes file is readable by other users'
        return 'ready', 'Private notes permissions checked'
    inspect('Private notes', notes)
    result.update(version=__version__, python=sys.version.split()[0], platform=platform.system(), diagnostics=details)
    return result


def run(args, launcher):
    from .ui import output, show_preflight, show_doctor
    result = (preflight if args.command == 'preflight' else doctor)(launcher)
    output(result, args.json, render=show_preflight if args.command == 'preflight' else show_doctor)
    return int(bool(result.get('error') or result['connection'] == 'error'
                    or any(item['state'] == 'error' for item in result.get('diagnostics', []))))
