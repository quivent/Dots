"""One setup plan shared by the menu and runner; steps remain separate commands."""
SETUP_STEPS = (
    {'args': ('doctor',), 'description': 'Check the desktop app, local files, and saved shortcuts.'},
    {'args': ('auth',), 'description': 'Reuse your ChatGPT login, or sign in when needed.'},
    {'args': ('check',), 'description': 'Verify the current connection to the Dot account API.'},
    {'args': ('setup', 'onboard'), 'description': 'Open Dot onboarding in ChatGPT.'},
)


def run_setup(execute):
    from .ui import console
    from rich.text import Text
    for index, step in enumerate(SETUP_STEPS, 1):
        command = 'dots ' + ' '.join(step['args'])
        console.print(Text(f'\n[{index}/{len(SETUP_STEPS)}] ' + command, style='bold green'))
        result = execute(list(step['args']))
        if result:
            console.print(Text('Setup stopped at ' + command + '. Run that command to retry, or choose another step independently.', style='yellow'))
            return result
    console.print('\n[green]Setup steps finished.[/green] [dim]Onboarding was opened; complete it in ChatGPT.[/dim]')
    return 0
