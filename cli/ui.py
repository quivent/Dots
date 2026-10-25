"""Terminal formatting, with color disabled automatically for redirected output."""
import argparse
import ast
from difflib import get_close_matches
from io import StringIO
import json
import re
import sys

from rich.console import Console
from rich.table import Column, Table
from rich.text import Text
from rich_argparse import RichHelpFormatter

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
        if self.prog in ('dots terminal', 'dots terminal guide'):
            from .guide import format_terminal_help
            return format_terminal_help(console)
        if self.prog != 'dots':
            return super().format_help()
        from . import __version__
        output = StringIO()
        terminal = Console(file=output, width=console.width, force_terminal=console.is_terminal,
                           no_color=console.no_color or '--no-color' in sys.argv,
                           color_system=None if console.no_color else console.color_system, highlight=False)
        terminal.print(Text('\ndots', style='bold #a7f3d0'), Text('  ' + __version__, style='dim'))
        terminal.rule(style='dim')
        terminal.print(Text('Default: locally saved ChatGPT Dots. Import: dots import --source chatgpt', style='dim'))
        terminal.print()
        from .commands import menu_groups
        for title, rows in menu_groups():
            command_tree(terminal, title, rows)
        return output.getvalue()


def show_setup():
    from .workflow import SETUP_STEPS
    rows = []
    for step in SETUP_STEPS:
        arguments = step['args'] or tuple(step['via'].split()[1:])
        description = step['description'].rstrip('.')
        if step['status'] != 'independent':
            description += ' · ' + step['status']
        rows.append((arguments[0], ' '.join(arguments[1:]), description))
    console.print()
    command_tree(console, 'Installation', rows)
    console.print('[dim]NAME: chosen name · DOT: returned ID or unique name[/dim]')
    console.print('[dim]dots setup run runs update, preflight, auth, and list only.[/dim]')
    console.print('[dim]Profile, conversation, and initialization share one create request; live creation remains unverified.[/dim]\n')


def show_table(columns, rows, **options):
    table = Table(*columns, box=None, **options)
    for row in rows:
        table.add_row(*(cell if isinstance(cell, Text) else Text(str(cell)) for cell in row))
    console.print(table)


def show_list(entries):
    if not entries:
        console.print('No locally saved Dots. Start with [green]dots create NAME --local[/green] or [green]dots configure URL --name NAME[/green].')
        return
    show_table((Column('Active', width=6), Column('Name', style='green'), 'Local status'),
               (('●' if entry['selected'] else '', entry['name'], entry['state']) for entry in entries),
               title='Saved Dot conversations', caption='Local shortcuts — not an account listing', header_style='bold')


def show_saved(entries):
    if not entries:
        console.print('No saved Dots. Run dots import --source chatgpt, or dots create NAME.')
        return
    show_table(('Active', 'ID', 'Name', 'Backend', 'Status'),
               (('●' if e.get('selected') else '', e['id'], e['display_name'],
                 'ChatGPT Dot' if e['backend'] == 'chatgpt' else 'Hosted Codex (uses allowance)',
                 e['status']) for e in entries), title='Saved Dots', header_style='bold')


def show_activity(events):
    console.print('[bold]Local launcher activity[/bold] [dim]— app opens and clipboard actions[/dim]')
    if events:
        show_table(('Time', Column('Action', style='green'), 'Outcome'),
                   ((event.get('time', ''), event.get('action', ''), event.get('outcome', '')) for event in events),
                   header_style='bold')
    else:
        console.print('No local actions recorded.')
    console.print('[dim]Dot task progress: conversation → profile → Activity. Use dots activity DOT --open for account activity.[/dim]')


def show_preflight(data):
    def state(key, ready, missing):
        return 'Not checked' if key not in data else ready if data[key] else missing
    rows = [('Project', data['project']),
            ('ChatGPT app', state('app_available', 'Installed', 'Not found; browser fallback available')),
            ('Conversation', state('conversation_saved', 'Link saved', 'No saved link')),
            ('Workspace', state('workspace_ready', 'Ready', 'Not initialized; use dots setup onboard')),
            ('Prompts', state('presets_available', 'Ready', 'Missing')),
            ('FIRST-RESULT.md', state('result_exists', 'Nonempty file found', 'Not found or empty'))]
    if data.get('local_error'):
        rows.append(('Local configuration', data['local_error']))
    connection = data.get('connection')
    rows.extend([('Account sign-in', data.get('credential_source', 'none')),
                 ('Dot account access', 'Verified' if connection == 'ready' else data.get('connection_error', 'Authentication needed: dots auth'))])
    show_table((Column(style='bold'), ''), rows, title='Setup preflight', show_header=False)


def show_doctor(data):
    show_preflight(data)
    console.print(Text('Python ' + data['python'] + ' · ' + data['platform'] + ' · dots ' + data['version'], style='dim'))
    show_table(('Check', 'State', 'Detail'),
               ((item['check'], item['state'], item['detail']) for item in data['diagnostics']),
               title='Troubleshooting diagnostics')


def output(value, raw=False, title='Dots', render=None):
    if raw:
        print(json.dumps(value, indent=2, ensure_ascii=False))
    elif render:
        render(value)
    elif isinstance(value, list):
        if not value:
            console.print('No records returned.')
            return
        if any(not isinstance(item, dict) for item in value):
            raise ValueError('Unexpected record in internal API response. Try --json.')
        show_table((Column('ID', style='green'), 'Name / title', 'Status'),
                   ((item.get('id', item.get('thread_id', '')),
                     item.get('display_name', item.get('title', item.get('name', ''))),
                     item.get('status', item.get('state', ''))) for item in value), title=title)
    else:
        # Render unrecognized profile fields faithfully instead of inventing a schema.
        from rich.json import JSON
        console.print(JSON.from_data(value))
