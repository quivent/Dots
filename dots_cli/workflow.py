"""One setup plan shared by the menu and runner; steps remain separate commands."""
SETUP_STEPS = (
    {'args': ('update',), 'description': 'Update the installed Dots CLI.'},
    {'args': ('preflight',), 'description': 'Check local readiness and current Dot account access.'},
    {'args': ('auth',), 'description': 'Reuse your ChatGPT login, or sign in when needed.'},
    {'args': ('setup', 'onboard'), 'description': 'Open Dot onboarding in ChatGPT.'},
)


def execute_step(arguments):
    from pathlib import Path
    import subprocess
    import sys
    # Reload the installed package for each step, especially after self-update.
    # A source checkout in the caller's working directory must not shadow it.
    return subprocess.run([sys.executable, '-m', 'dots_cli', *arguments],
                          cwd=Path(sys.executable).parent).returncode


def run_setup(execute=None):
    if execute is None:
        execute = execute_step
    from .ui import console
    from rich.text import Text
    for index, step in enumerate(SETUP_STEPS, 1):
        command = 'dots ' + ' '.join(step['args'])
        console.print(Text(f'\n[{index}/{len(SETUP_STEPS)}] ' + command, style='bold green'))
        result = execute(list(step['args']))
        if result:
            console.print(Text('Setup stopped at ' + command + '. Run that command to retry, or choose another step independently.', style='yellow'))
            return result
    console.print('\n[green]Setup steps finished.[/green] [dim]Onboarding launch requested; complete it in ChatGPT.[/dim]')
    return 0
