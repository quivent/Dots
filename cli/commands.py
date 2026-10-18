"""One command catalog for argument parsing, dispatch, and the terminal menu."""
from typing import NamedTuple


class Command(NamedTuple):
    name: str
    help: str
    arguments: tuple = ()
    handler: str = 'cloud'
    children: tuple = ()
    description: str = None


def arg(name, help=None, **options):
    return name, dict(options, help=help)


def flag(name, help):
    return arg(name, help, action='store_true')


JSON = flag('--json', 'Print machine-readable JSON')
LOCAL = flag('--local', 'Use saved local conversation shortcuts')
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
        Command('setup', 'Show the setup steps', (
            arg('setup_action', 'Choose run or onboard; omit to list every operation.', nargs='?', choices=SETUP_ACTIONS), JSON), 'setup'),
        Command('installation', 'Show the full setup plan', (JSON,), 'setup'),
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
            flag('--no-open', 'With --local, save the shortcut without opening onboarding'), JSON,
            (None, (arg('--first', 'Create the first Dot without a catalog lookup', dest='additional', action='store_false', default=None),
                    arg('--additional', 'Create an additional Dot without a catalog lookup', dest='additional', action='store_true'))))),
        Command('use', 'Select the primary Dot', (arg('name', 'Dot ID or unique name; local shortcut name with --local'), BY_ID, LOCAL, JSON)),
        Command('show', 'Inspect a Dot', (DOT, BY_ID, JSON)),
        Command('open', 'Open the saved conversation', PROMPT, 'launch'),
        Command('run', 'Copy a task and open ChatGPT', PROMPT, 'launch'),
        Command('copy', 'Copy a prompt', PROMPT, 'launch'),
        Command('prompt', 'Print a saved prompt', (
            arg('preset', 'Prompt to print (default: first)', choices=PRESETS, nargs='?', default='first'),), 'prompt'),
    )),
    ('Manage', (
        Command('activity', 'Read Dot activity', (DOT, BY_ID, JSON, LOCAL, flag('--open', 'Open the Dot activity page after reading it'))),
        Command('tasks', 'List or inspect tasks', (DOT, BY_ID, JSON, arg('--task', 'Inspect one task ID instead of listing tasks'))),
        Command('pause', 'Request a runtime pause', (DOT, BY_ID, JSON)),
        Command('resume', 'Request a runtime resume', (DOT, BY_ID, JSON)),
        Command('room', 'Create or recover a messaging room', (DOT, BY_ID, JSON)),
        Command('configure', 'Save a conversation shortcut', (
            arg('url', 'Paste the conversation URL; empty string clears it'), arg('--name', 'Name this local conversation shortcut')), 'configure'),
        Command('web', 'Open the local setup guide', (
            arg('--port', 'Local HTTP port (default: 8768; 0 selects a free port)', type=int, default=8768),
            flag('--no-open', 'Start the local server without opening a browser')), 'serve'),
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
    for command in commands:
        parser = subparsers.add_parser(command.name, help=command.help, description=command.description)
        parser.set_defaults(handler=command.handler)
        add_arguments(parser, command.arguments)
        if command.children:
            register(parser.add_subparsers(dest=command.name + '_action'), command.children)


def build_parser():
    from . import __version__
    from .ui import DotsParser
    parser = DotsParser(prog='dots', description='Manage account Dots and local setup tools.')
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
