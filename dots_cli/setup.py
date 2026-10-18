"""Independent setup actions; no pipeline state or automatic cloud writes."""
from .api import DotClient, credentials


def run_step(step, launcher):
    if step == 'check':
        app_available = launcher.app_available()
        token, account, source = credentials()
        checks = [
            {'name': 'CLI', 'state': 'ready', 'next': 'dots --help'},
            {'name': 'Desktop app', 'state': 'found' if app_available else 'not found', 'next': 'dots setup app' if app_available else 'dots setup web'},
            {'name': 'Account credential', 'state': 'present; not verified' if token and account else 'missing', 'next': 'dots setup api' if token and account else 'dots auth --help'},
            {'name': 'Local guide', 'state': 'available' if launcher.resource('setup.html').is_file() else 'missing', 'next': 'dots serve'},
        ]
        for name, inspect, next_command in [
            ('Saved shortcut', lambda: bool(launcher.settings()['url']), 'dots configure URL'),
            ('Starter prompts', lambda: all(p['text'] for p in launcher.presets()), 'dots prompt first'),
        ]:
            try:
                state = 'ready' if inspect() else 'not configured'
            except (OSError, ValueError, KeyError):
                state = 'needs repair; other steps still available'
            checks.append({'name': name, 'state': state, 'next': next_command})
        return {'step': step, 'checks': checks, 'credential_source': source, 'api_checked': False}
    if step == 'auth':
        token, account, source = credentials()
        return {'step': step, 'token_present': bool(token), 'account_id_present': bool(account),
                'source': source, 'verified': False,
                'next': 'dots setup api' if token and account else 'dots auth --help'}
    if step == 'api':
        entries = DotClient().list()
        return {'step': step, 'read_access_verified': True, 'dot_count': len(entries),
                'write_access_verified': False, 'next': 'dots list'}
    result = launcher.launch('setup' if step == 'open' else step) if step != 'web' else _open_web(launcher)
    return dict(result, step=step, onboarding_verified=False)


def _open_web(launcher):
    # Keep the generic dots web shortcut distinct from this direct setup route.
    command = launcher.url_command('https://chatgpt.com/dots')
    result = launcher.runner(command['argv'], capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise ValueError('Could not open Dot onboarding in the browser.')
    return {'message': 'Web Dot onboarding launch requested.', 'submitted': False}


def show_step(result):
    from .ui import console
    from rich.table import Table
    from rich.text import Text
    if 'checks' in result:
        table = Table(title='Independent setup checks', box=None)
        for heading in ['Step', 'State', 'Run separately']:
            table.add_column(heading)
        for check in result['checks']:
            table.add_row(Text(check['name']), Text(check['state']), Text(check['next']))
        console.print(table)
    elif 'message' in result:
        console.print(Text(result['message']))
    else:
        from rich.json import JSON
        console.print(JSON.from_data(result))
