"""Terminal formatting, with color disabled automatically for redirected output."""
import argparse
from io import StringIO
import os
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich_argparse import RichHelpFormatter

GROUPS = [
    ('Account Dots · experimental API', ['auth', 'create', 'list', 'use', 'show', 'tasks', 'activity', 'pause', 'resume', 'room']),
    ('Setup & connections', ['setup', 'configure']),
    ('Tasks & activity', ['run', 'open', 'app', 'copy', 'prompt']),
    ('Local tools', ['serve', 'doctor', 'status', 'history', 'folder', 'web', 'guide']),
]
console = Console(highlight=False)


class DotsParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('formatter_class', lambda prog: RichHelpFormatter(prog, console=console))
        super().__init__(*args, **kwargs)

    def format_help(self):
        if self.prog != 'dots':
            return super().format_help()
        output = StringIO()
        terminal = Console(file=output, width=console.width, force_terminal=console.is_terminal,
                           no_color=console.no_color or '--no-color' in sys.argv, highlight=False)
        terminal.print('\n[bold green]● dots[/bold green]  [dim]Account & local tools for ChatGPT Dots[/dim]\n')
        terminal.print('[bold]Usage:[/bold] dots [--no-color] [--version] COMMAND [OPTIONS]')
        sub = next(a for a in self._actions if isinstance(a, argparse._SubParsersAction))
        descriptions = {a.dest: a.help for a in sub._choices_actions}
        for title, commands in GROUPS:
            table = Table(title=title, title_justify='left', title_style='bold', box=None,
                          show_header=False, padding=(0, 2), expand=False)
            table.add_column(style='green', no_wrap=True, min_width=12)
            table.add_column()
            for command in commands:
                table.add_row(command, descriptions[command])
            terminal.print('\n', end='')
            terminal.print(table)
        terminal.print('\n[bold]Options[/bold]')
        terminal.print('  [green]-h, --help[/green]     Show this help')
        terminal.print('  [green]--version[/green]      Show the installed version')
        terminal.print('  [green]--no-color[/green]     Disable terminal colors')
        terminal.print(Panel('make\ndots setup\ndots auth status --check\ndots list\ndots create research\ndots activity research\ndots serve', title='Examples', title_align='left', border_style='dim', expand=False))
        terminal.print('Use [green]dots COMMAND --help[/green] for every option and argument.\n')
        terminal.print('[dim]Cloud commands require explicit account credentials: dots auth --help.\nUse --local for saved shortcuts and launcher activity.[/dim]\n')
        return output.getvalue()


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
