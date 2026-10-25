"""One command catalog for argument parsing, dispatch, and the terminal menu."""
from typing import NamedTuple
from pathlib import Path
import argparse


class Command(NamedTuple):
    name: str
    help: str
    arguments: tuple = ()
    handler: str = 'cloud'
    children: tuple = ()
    description: str = None
    route: tuple = ()


def arg(name, help=None, **options):
    return name, dict(options, help=help)


def flag(name, help):
    return arg(name, help, action='store_true')


JSON = flag('--json', 'Print machine-readable JSON')
LOCAL = flag('--local', 'Use locally saved Dot identities (the terminal default)')
BY_ID = flag('--by-id', 'Treat the target as a literal Dot ID; skip catalog lookup')
DOT = arg('dot', 'Dot ID or unique name; defaults to the only or primary Dot', nargs='?')
PRESETS = ('first', 'local', 'followup')
PROMPT = ((None, (arg('--preset', choices=PRESETS),
                  arg('--prompt', 'Text to copy; passed as clipboard data, never shell code'))),
          flag('--dry-run', 'Show commands without executing or logging them'))
SETUP_ACTIONS = {'run': 'Run setup prerequisites through account discovery',
                 'onboard': 'Open Dot onboarding in ChatGPT'}
AUTH_ACTIONS = (
    Command('login', 'Sign in with ChatGPT; --account-id selects advanced manual-token input', (
        arg('--account-id', 'Advanced: validate and save a supplied token for this account ID'),
        flag('--token-stdin', 'Read token from stdin instead of a hidden prompt'))),
    Command('status', 'Report credential source without displaying secrets', (
        flag('--check', 'Also test read-only account access'),)),
    Command('logout', 'Remove the CLI credential from the OS store (environment is unaffected)'),
)
COMMANDS = (
    ('Setup', (
        Command('guide', 'Read a Markdown guide for an interface', (
            arg('interface', 'Guide to read', nargs='?', default='overview',
                choices=('overview', 'terminal', 'desktop', 'mobile', 'sources')),
            flag('--plain', 'Print raw Markdown instead of rendering it')), 'guide'),
        Command('terminal', 'Terminal guide; --help shows the full guide', (
            arg('--plain', 'Print raw Markdown', action='store_true', default=argparse.SUPPRESS),), 'guide',
            children=(Command('guide', 'Read the terminal Markdown guide', (
                arg('--plain', 'Print raw Markdown', action='store_true', default=argparse.SUPPRESS),), 'guide'),)),
        Command('setup', 'Show the setup steps', (
            arg('setup_action', 'Choose run or onboard; omit to list every operation.', nargs='?', choices=SETUP_ACTIONS), JSON), 'workflow'),
        Command('installation', 'Show the full setup plan', (JSON,), 'workflow'),
        Command('update', 'Update the installed Dots CLI', handler='update'),
        Command('preflight', 'Check this computer and Dot account access', (JSON,), 'diagnostics'),
        Command('auth', 'Sign in, or reuse your existing login', children=AUTH_ACTIONS,
                description='Reuse an existing ChatGPT sign-in or start first-party browser login, then verify Dot account access. '
                'The CLI never displays tokens or reads browser/session files. Advanced alternatives: DOTS_ACCESS_TOKEN '
                'and DOTS_ACCOUNT_ID, or auth login --account-id ACCOUNT_ID. OpenAI platform API keys do not provide Dot account access.'),
    )),
    ('Dots', (
        Command('list', 'List your Dots', (LOCAL, JSON)),
        Command('create', 'Create a Dot', (
            arg('name', 'Dot display name', nargs='?'), LOCAL,
            flag('--no-open', 'With --source shortcuts, save a shortcut without opening onboarding'), JSON,
            (None, (arg('--first', 'Create the first Dot without a catalog lookup', dest='additional', action='store_false', default=None),
                    arg('--additional', 'Create an additional Dot without a catalog lookup', dest='additional', action='store_true'))))),
        Command('import', 'Save existing account Dots locally', (
            DOT, BY_ID, arg('--name', 'Local alias when importing one Dot'), JSON)),
        Command('forget', 'Remove a saved identity without changing its provider', (DOT, BY_ID, JSON)),
        Command('use', 'Select the default saved Dot', (arg('name', 'Saved Dot ID or unique name'), BY_ID, LOCAL, JSON)),
        Command('show', 'Inspect a Dot', (DOT, BY_ID, JSON), route=('GET', '{dot}')),
        Command('rename', 'Rename a saved alias (provider name with --source chatgpt)', (arg('dot', 'Dot ID or unique current name'),
                arg('name', 'New display name'), BY_ID, JSON)),
        Command('open', 'Open the saved conversation', PROMPT, 'launch'),
        Command('run', 'Copy a task and open ChatGPT', PROMPT, 'launch'),
        Command('chat', 'Chat with a Dot in the terminal', (
            DOT, BY_ID, arg('--message', 'Send one message and wait for a reply'),
            flag('--status', 'Read runtime and delivery status without sending a message'),
            arg('--timeout', 'Seconds to wait for a reply (default: 120)', type=int, default=120),
            arg('--poll', 'Seconds between reply checks (default: 2)', type=int, default=2)), 'chat',
            description='Chat with a locally saved ChatGPT Dot (cloud execution). /refresh reads recent messages; '
            '/wait continues waiting; /status reads runtime and delivery state; /abandon stops tracking a pending reply; /quit exits. '
            'Paused Dots are never resumed automatically. Writes are never retried automatically.'),
        Command('copy', 'Copy a prompt', PROMPT, 'launch'),
        Command('prompt', 'Print a saved prompt', (
            arg('preset', 'Prompt to print (default: first)', choices=PRESETS, nargs='?', default='first'),), 'prompt'),
    )),
    ('Manage', (
        Command('activity', 'Read Dot activity', (DOT, BY_ID, JSON, LOCAL, flag('--open', 'Open the Dot activity page after reading it'))),
        Command('tasks', 'List or inspect tasks', (DOT, BY_ID, JSON, arg('--task', 'Inspect one task ID instead of listing tasks'))),
        Command('pause', 'Request a runtime pause', (DOT, BY_ID, JSON), route=('POST', '{dot}/runtime/pause')),
        Command('resume', 'Request a runtime resume', (DOT, BY_ID, JSON), route=('POST', '{dot}/runtime/resume')),
        Command('room', 'Create or recover a messaging room', (DOT, BY_ID, JSON), route=('POST', '{dot}/messaging-room')),
        Command('configure', 'Save a conversation shortcut', (
            arg('url', 'Paste the conversation URL; empty string clears it'), arg('--name', 'Name this local conversation shortcut')), 'configure'),
        Command('web', 'Open the local setup guide', (
            arg('--port', 'Local HTTP port (default: 8768; 0 selects a free port)', type=int, default=8768),
            flag('--no-open', 'Start the local server without opening a browser')), 'serve'),
        Command('mobile', 'Connect the iPhone app through this Mac', (
            arg('--host', 'Listen address; use your Tailscale IP for phone access', default='127.0.0.1'),
            arg('--port', 'Listen port (default: 8769)', type=int, default=8769),
            arg('--token-file', 'Private mobile connection token file', default=str(Path.home() / '.local/share/dots/mobile-token')),
            flag('--install-daemon', 'Install and start a per-user macOS launchd service'),
            flag('--quiet', 'Do not print connection details')), 'mobile'),
        Command('doctor', 'Full troubleshooting diagnostics', (JSON,), 'diagnostics'),
        Command('status', 'Show local configuration', handler='inspect'),
        Command('history', 'Show local launch history', handler='inspect'),
        Command('app', 'Open the desktop app', PROMPT, 'launch'),
    )),
)


def add_arguments(parser, arguments):
    for name, options in arguments:
        if name is None:
            add_arguments(parser.add_mutually_exclusive_group(), options)
        else:
            parser.add_argument(name, **options)


def register(subparsers, commands):
    from .sources import AGENT_COMMANDS
    for command in commands:
        parser = subparsers.add_parser(command.name, help=command.help, description=command.description)
        parser.set_defaults(handler=command.handler, route=command.route)
        add_arguments(parser, command.arguments)
        if command.name in AGENT_COMMANDS:
            parser.set_defaults(local=False)
            parser.add_argument('--source', choices=('local', 'chatgpt', 'hosted', 'shortcuts'),
                                default=argparse.SUPPRESS,
                                help='Identity source (default: local saved Dots; hosted entries are Codex workers)')
        if command.children:
            register(parser.add_subparsers(dest=command.name + '_action'), command.children)


def build_parser():
    from . import __version__
    from .ui import DotsParser
    parser = DotsParser(prog='dots', description='Use saved Dots in the terminal; actual Dots run in the cloud.')
    parser.add_argument('--source', choices=('local', 'chatgpt', 'hosted', 'shortcuts'), default='local',
                        help='Identity source for Dot commands (default: local)')
    parser.add_argument('--version', action='version', version='dots ' + __version__)
    parser.add_argument('--no-color', action='store_true', help='Disable terminal colors')
    register(parser.add_subparsers(dest='command', metavar='COMMAND'),
             (command for _, commands in COMMANDS for command in commands))
    return parser


def menu_groups():
    for title, commands in COMMANDS:
        rows, variants = [], []
        for command in commands:
            arguments = []
            for name, options in command.arguments:
                if name and not name.startswith('-'):
                    if isinstance(options.get('choices'), dict):
                        variants.extend((command.name + ' ' + choice, '', help) for choice, help in options['choices'].items())
                    else:
                        arguments.append('[' + name.upper() + ']' if options.get('nargs') == '?' else name.upper())
            rows.append((command.name, ' '.join(arguments), command.help))
        yield title, rows + variants
