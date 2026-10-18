"""Terminal formatting, with color disabled automatically for redirected output."""
import argparse
from io import StringIO
import sys

from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich_argparse import RichHelpFormatter

# Each row is a real command, its arguments, and a short description.
GROUPS = [
    ('Setup', [
        ('setup', '', 'Show the numbered setup steps'),
        ('setup run', '', 'Run the setup steps in order'),
        ('doctor', '', 'Check this computer and local files'),
        ('auth', '', 'Sign in, or reuse your existing login'),
        ('check', '', 'Verify sign-in and Dot account access'),
        ('setup open', '', 'Open Dot onboarding in ChatGPT'),
    ]),
    ('Dots', [
        ('list', '', 'List your Dots'),
        ('create', 'NAME', 'Create a Dot'),
        ('use', 'DOT', 'Select the primary Dot'),
        ('show', '[DOT]', 'Inspect a Dot'),
        ('open', '', 'Open the saved conversation'),
        ('run', '--prompt TEXT', 'Copy a task and open ChatGPT'),
        ('copy', '--prompt TEXT', 'Copy a prompt'),
        ('prompt', '[PRESET]', 'Print a saved prompt'),
    ]),
    ('Manage', [
        ('activity', '[DOT]', 'Read Dot activity'),
        ('tasks', '[DOT]', 'List or inspect tasks'),
        ('pause', '[DOT]', 'Request a runtime pause'),
        ('resume', '[DOT]', 'Request a runtime resume'),
        ('room', '[DOT]', 'Create or recover a messaging room'),
        ('configure', 'URL', 'Save a conversation shortcut'),
        ('serve', '', 'Open the local setup guide'),
        ('status', '', 'Show local configuration'),
        ('history', '', 'Show local launch history'),
        ('app', '', 'Open the desktop app'),
        ('web', '', 'Open ChatGPT in the browser'),
        ('folder', '', 'Open the project folder'),
        ('guide', '', 'Open the official setup guide'),
    ]),
]
console = Console(highlight=False)


def command_tree(terminal, title, rows):
    from rich.padding import Padding
    terminal.print(Text('▸ ' + title, style='bold #f9a8d4'))
    table = Table.grid(padding=(0, 2), expand=False)
    table.add_column(no_wrap=True)
    table.add_column(style='dim')
    for index, (command, arguments, description) in enumerate(rows):
        label = Text('└─ ' if index == len(rows) - 1 else '├─ ', style='#67e8f9')
        label.append('dots ' + command, style='bold #a7f3d0')
        if arguments:
            label.append(' ' + arguments, style='#fdba74')
        table.add_row(label, Text(description, style='dim'))
    terminal.print(Padding(table, (0, 0, 0, 2)))
    terminal.print()


class DotsParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('formatter_class', lambda prog: RichHelpFormatter(prog, console=console))
        super().__init__(*args, **kwargs)

    def format_help(self):
        if self.prog != 'dots':
            return super().format_help()
        from . import __version__
        output = StringIO()
        terminal = Console(file=output, width=console.width, force_terminal=console.is_terminal,
                           no_color=console.no_color or '--no-color' in sys.argv,
                           color_system=None if console.no_color else console.color_system, highlight=False)
        terminal.print(Text('\ndots', style='bold #a7f3d0'), Text('  ' + __version__, style='dim'))
        terminal.rule(style='dim')
        terminal.print()
        for title, rows in GROUPS:
            command_tree(terminal, title, rows)
        terminal.print('[dim]Usage: dots COMMAND [OPTIONS] · dots COMMAND --help for details[/dim]')
        terminal.print('[dim]--help  --version  --no-color · --local uses saved shortcuts[/dim]')
        terminal.print('[dim]Account commands use an experimental API; run copies prompts for you to send.[/dim]\n')
        return output.getvalue()


def show_setup():
    from .workflow import SETUP_STEPS
    console.print(Text('\nSetup', style='bold #f9a8d4'))
    console.print('[dim]Run each step on its own, or run the sequence with dots setup run.[/dim]\n')
    rows = [('setup run', '', 'Run the numbered steps below')]
    command_tree(console, 'Run setup', rows)
    for index, step in enumerate(SETUP_STEPS, 1):
        label = Text(f'  {index:02d}  ', style='#67e8f9')
        label.append('dots ' + ' '.join(step['args']), style='bold #a7f3d0')
        console.print(label)
        console.print(Text('      ' + step['description'], style='dim'))
    console.print('\n[dim]No step creates a Dot. Run dots create NAME when ready.[/dim]\n')


def show_list(entries):
    if not entries:
        console.print('No locally saved Dots. Start with [green]dots create NAME --local[/green] or [green]dots configure URL --name NAME[/green].')
        return
    table = Table(title='Saved Dot conversations', caption='Local shortcuts — not an account listing', box=None, header_style='bold')
    table.add_column('Active', width=6)
    table.add_column('Name', style='green')
    table.add_column('Local status')
    for entry in entries:
        table.add_row('●' if entry['selected'] else '', Text(entry['name']), entry['state'])
    console.print(table)


def show_activity(events):
    console.print('[bold]Local launcher activity[/bold] [dim]— app opens and clipboard actions[/dim]')
    if events:
        table = Table(box=None, header_style='bold')
        table.add_column('Time')
        table.add_column('Action', style='green')
        table.add_column('Outcome')
        for event in events:
            table.add_row(Text(str(event.get('time', ''))), Text(str(event.get('action', ''))), Text(str(event.get('outcome', ''))))
        console.print(table)
    else:
        console.print('No local actions recorded.')
    console.print('[dim]Dot task progress: conversation → profile → Activity. Use dots activity DOT --open for account activity.[/dim]')


def show_doctor(data):
    table = Table(title='Local readiness', box=None, show_header=False)
    table.add_column(style='bold')
    table.add_column()
    table.add_row('Project', Text(data['project']))
    table.add_row('ChatGPT app', 'Installed' if data['app_available'] else 'Not found; browser fallback available')
    table.add_row('Conversation', 'Link saved' if data['conversation_saved'] else 'No saved link')
    table.add_row('Prompts', 'Ready' if data['presets_available'] else 'Missing')
    table.add_row('FIRST-RESULT.md', 'Nonempty file found' if data['result_exists'] else 'Not found or empty')
    console.print(table)


def show_connection(data):
    table = Table(title='Dot connection', box=None, show_header=False)
    table.add_column(style='bold')
    table.add_column()
    table.add_row('Sign-in', Text(data['credential_source']))
    table.add_row('Dot account access', 'Verified')
    table.add_row('Dots', str(data['dot_count']))
    console.print(table)
