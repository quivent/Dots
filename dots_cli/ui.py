"""Terminal formatting, with color disabled automatically for redirected output."""
import argparse
import ast
from difflib import get_close_matches
from io import StringIO
import re
import sys

from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich_argparse import RichHelpFormatter

# Each row is a real command, its arguments, and a short description.
GROUPS = [
    ('Setup', [
        ('update', '', 'Update the installed Dots CLI'),
        ('setup', '', 'Show the numbered setup steps'),
        ('installation', '', 'List the individual installation and setup commands'),
        ('setup run', '', 'Run setup prerequisites through account discovery'),
        ('preflight', '', 'Check this computer and Dot account access'),
        ('auth', '', 'Sign in, or reuse your existing login'),
        ('setup onboard', '', 'Open Dot onboarding in ChatGPT'),
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
        ('doctor', '', 'Full troubleshooting diagnostics'),
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

    def error(self, message):
        """One concise error format for the root command and every subcommand."""
        terminal = Console(file=sys.stderr, no_color=console.no_color, highlight=False)
        correction = None
        invalid = re.search(r'invalid choice: (.+) \(choose from ', message)
        if invalid:
            try:
                value = ast.literal_eval(invalid.group(1))
            except (ValueError, SyntaxError):
                value = None
            if isinstance(value, str):
                command = self.prog + ' ' + value
                message = 'Unknown command: ' + command
                moved = {'dots setup steps': 'dots installation'}
                correction = moved.get(command)
                if correction is None:
                    choices = [str(choice) for action in self._actions
                               if action.choices for choice in action.choices]
                    matches = get_close_matches(value, choices, n=1, cutoff=0.6)
                    if matches:
                        correction = self.prog + ' ' + matches[0]
        else:
            message = 'Error: ' + message
        terminal.print(Text(message, style='yellow'))
        terminal.print(Text('Try: ' + correction if correction else 'Help: ' + self.prog + ' --help', style='dim'))
        self.exit(2)

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
    from .workflow import SETUP_STEPS, step_command
    console.print(Text('\nSetup', style='bold #f9a8d4'))
    console.print('[dim]Every operation in terminal setup. NAME is your chosen name; DOT is a returned ID or unique name.[/dim]\n')
    for index, step in enumerate(SETUP_STEPS, 1):
        label = Text(f'  {index:02d}  ', style='#67e8f9')
        label.append(step['description'].rstrip('.'), style='bold #a7f3d0')
        if step['status'] != 'independent':
            label.append(' · ' + step['status'], style='#fdba74')
        console.print(label)
        command = step_command(step)
        if command:
            console.print(Text('      ' + command))
        if step.get('note'):
            console.print(Text('      ' + step['note'], style='dim'))
    console.print('\n[dim]dots setup run runs prerequisites 01–04 only; it does not create a Dot.[/dim]')
    console.print('[dim]Steps 05–07 are currently one creation request, not independent commands. Live creation remains unverified.[/dim]\n')


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


def show_preflight(data):
    table = Table(title='Setup preflight', box=None, show_header=False)
    table.add_column(style='bold')
    table.add_column()
    table.add_row('Project', Text(data['project']))
    def state(key, ready, missing):
        return 'Not checked' if key not in data else ready if data[key] else missing
    table.add_row('ChatGPT app', state('app_available', 'Installed', 'Not found; browser fallback available'))
    table.add_row('Conversation', state('conversation_saved', 'Link saved', 'No saved link'))
    table.add_row('Workspace', state('workspace_ready', 'Ready', 'Not initialized; use dots setup onboard'))
    table.add_row('Prompts', state('presets_available', 'Ready', 'Missing'))
    table.add_row('FIRST-RESULT.md', state('result_exists', 'Nonempty file found', 'Not found or empty'))
    if data.get('local_error'):
        table.add_row('Local configuration', Text(data['local_error']))
    connection = data.get('connection')
    table.add_row('Account sign-in', Text(data.get('credential_source', 'none')))
    table.add_row('Dot account access', 'Verified' if connection == 'ready' else Text(data.get('connection_error', 'Authentication needed: dots auth')))
    console.print(table)


def show_doctor(data):
    show_preflight(data)
    console.print(Text('Python ' + data['python'] + ' · ' + data['platform'] + ' · dots ' + data['version'], style='dim'))
    table = Table(title='Troubleshooting diagnostics', box=None)
    table.add_column('Check')
    table.add_column('State')
    table.add_column('Detail')
    for item in data['diagnostics']:
        table.add_row(Text(item['check']), Text(item['state']), Text(item['detail']))
    console.print(table)
