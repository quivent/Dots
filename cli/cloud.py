"""CLI commands for account-backed Dot operations."""
import getpass
import json
import sys

from .api import ApiError, DotClient, SERVICE, credential_store, credentials, encode_id


def add_commands(sub):
    auth = sub.add_parser('auth', help='Sign in with ChatGPT, reusing an existing login when available',
        description='With no subcommand, reuse the existing ChatGPT sign-in or start the first-party browser login, '
        'then verify Dot account access. The CLI never displays tokens or reads browser/session files. '
        'Explicit tokens are an advanced alternative: DOTS_ACCESS_TOKEN and DOTS_ACCOUNT_ID, '
        'or auth login --account-id ACCOUNT_ID. OpenAI platform API keys do not provide Dot account access.')
    actions = auth.add_subparsers(dest='auth_action')
    login = actions.add_parser('login', help='Sign in with ChatGPT; --account-id selects advanced manual-token input')
    login.add_argument('--account-id', help='Advanced: validate and save a supplied token for this account ID')
    login.add_argument('--token-stdin', action='store_true', help='Read token from stdin instead of a hidden prompt')
    check = actions.add_parser('status', help='Report credential source without displaying secrets')
    check.add_argument('--check', action='store_true', help='Also test read-only account access')
    actions.add_parser('logout', help='Remove the CLI credential from the OS store (environment is unaffected)')
    create = sub.add_parser('create', help='Create a cloud Dot (experimental account API)')
    create.add_argument('name', nargs='?', help='Dot display name')
    create.add_argument('--local', action='store_true', help='Save a local pending shortcut and open onboarding instead')
    create.add_argument('--no-open', action='store_true', help='With --local, save the shortcut without opening onboarding')
    create.add_argument('--json', action='store_true', help='Print the returned cloud profile as JSON')
    kind = create.add_mutually_exclusive_group()
    kind.add_argument('--first', dest='additional', action='store_false', default=None,
                      help='Create the first Dot without a catalog lookup')
    kind.add_argument('--additional', dest='additional', action='store_true',
                      help='Create an additional Dot without a catalog lookup')
    listing = sub.add_parser('list', help='List account Dots; --local lists saved conversation shortcuts')
    listing.add_argument('--local', action='store_true', help='Read only the local shortcut registry')
    listing.add_argument('--json', action='store_true', help='Print machine-readable JSON')
    use = sub.add_parser('use', help='Select the account’s primary Dot; --local selects a saved shortcut')
    use.add_argument('name', help='Dot ID or unique name; local shortcut name with --local')
    use.add_argument('--by-id', action='store_true', help='Treat NAME as a literal Dot ID; skip catalog lookup')
    use.add_argument('--local', action='store_true', help='Select only the local launcher shortcut')
    use.add_argument('--json', action='store_true', help='Print the API response as JSON')
    for command, help_text in [('show', 'Inspect a Dot profile'),
                                ('activity', 'Read Dot activity from the account'),
                                ('tasks', 'List tasks or inspect a task by ID'),
                                ('room', 'Create or recover a Dot messaging room'),
                                ('pause', 'Request a pause of the Dot runtime'),
                                ('resume', 'Request resumption of the Dot runtime')]:
        p = sub.add_parser(command, help=help_text + ' (experimental)')
        p.add_argument('dot', nargs='?', help='Dot ID or unique name; defaults to the only or primary Dot')
        p.add_argument('--by-id', action='store_true', help='Treat DOT as a literal ID; skip catalog lookup')
        p.add_argument('--json', action='store_true', help='Print machine-readable JSON')
        if command == 'tasks':
            p.add_argument('--task', help='Inspect one task ID instead of listing tasks')
        if command == 'activity':
            p.add_argument('--local', action='store_true', help='Read local launch history instead')
            p.add_argument('--open', action='store_true', help='Open the Dot activity page after reading it')


def output(value, raw=False, title='Dots'):
    from .ui import console
    from rich.table import Table
    from rich.text import Text
    if raw:
        print(json.dumps(value, indent=2, ensure_ascii=False))
    elif isinstance(value, list):
        if not value:
            console.print('No records returned.')
            return
        table = Table(title=title, box=None)
        table.add_column('ID', style='green')
        table.add_column('Name / title')
        table.add_column('Status')
        for item in value:
            if not isinstance(item, dict):
                raise ApiError('Unexpected record in internal API response. Try --json.')
            table.add_row(Text(str(item.get('id', item.get('thread_id', '')))),
                Text(str(item.get('display_name', item.get('title', item.get('name', ''))))),
                Text(str(item.get('status', item.get('state', '')))))
        console.print(table)
    else:
        # Render unrecognized profile fields faithfully instead of inventing a schema.
        from rich.json import JSON
        console.print(JSON.from_data(value))


def run(args, launcher):
    """Return an exit code if handled, else None for local launcher commands."""
    if args.command == 'auth':
        action = args.auth_action
        if action is None or (action == 'login' and not args.account_id):
            if getattr(args, 'token_stdin', False):
                raise ApiError('--token-stdin requires --account-id for manual token input.')
            from .auth import sign_in
            token, account, source = credentials()
            if token and not account:
                raise ApiError('The explicit token is missing its account ID. Set DOTS_ACCOUNT_ID or remove the override to use ChatGPT sign-in.')
            rejected_saved = False
            # At most: saved override, existing app login, fresh first-party login.
            for attempt in range(3):
                if not token or not account:
                    token, account = sign_in()
                    source = 'ChatGPT sign-in'
                try:
                    DotClient(token, account).list()
                    break
                except ApiError as error:
                    if attempt == 2 or error.status != 401 or source not in ('existing ChatGPT sign-in', 'OS credential store'):
                        raise
                    if source == 'OS credential store':
                        rejected_saved = True
                        token, account, source = credentials(ignore_saved=True)
                    else:
                        token, account, source = '', '', 'none'
            if rejected_saved:
                # Remove the rejected override only after a replacement login works.
                credential_store().delete_password(SERVICE, 'account')
            print('Authenticated with ChatGPT. Dot account access verified (' + source + ').')
        elif action == 'login':
            store = credential_store()
            token = sys.stdin.readline().strip() if args.token_stdin else getpass.getpass('ChatGPT account access token: ').strip()
            if not token:
                raise ApiError('No account token supplied.')
            DotClient(token, args.account_id).list()  # Verify before replacing stored credentials.
            store.set_password(SERVICE, 'account', json.dumps({'token': token, 'account_id': args.account_id}))
            print('Account access verified. Credential saved in the OS credential store.')
        elif action == 'logout':
            store = credential_store()
            if store.get_password(SERVICE, 'account'):
                store.delete_password(SERVICE, 'account')
            print('Saved CLI credential removed. Existing ChatGPT sign-in and environment credentials are unaffected.')
        else:
            token, account, source = credentials()
            result = {'credential_source': source, 'token_present': bool(token), 'account_id_present': bool(account),
                      'api': 'experimental internal Dot API', 'verified': False}
            if getattr(args, 'check', False):
                result['dot_count'] = len(DotClient(token, account).list())
                result['verified'] = True
            output(result, True)
        return 0
    if args.command not in ('list', 'create', 'use', 'show', 'activity', 'tasks', 'pause', 'resume', 'room'):
        return None
    from .ui import show_list, show_activity
    if getattr(args, 'local', False):
        if getattr(args, 'by_id', False) or getattr(args, 'additional', None) is not None:
            raise ApiError('--by-id, --first, and --additional apply to account commands only.')
        if args.command == 'list':
            entries = launcher.list_dots()
            output({'source': 'local_registry', 'dots': entries}, True) if args.json else show_list(entries)
        elif args.command == 'create':
            output(launcher.create(args.name, args.no_open), args.json)
        elif args.command == 'use':
            output(launcher.use(args.name), args.json)
        else:
            if args.dot:
                raise ApiError('A Dot ID is not used with activity --local.')
            events = launcher.history()
            output({'source': 'local_launcher', 'events': events}, True) if args.json else show_activity(events)
            if args.open:
                launcher.launch('dot' if launcher.settings()['url'] else 'setup')
        return 0
    client = DotClient()
    if args.command == 'list':
        output(client.list(), args.json, 'Account Dots')
    elif args.command == 'create':
        if args.no_open:
            raise ApiError('--no-open applies to --local only. Cloud creation does not launch a browser.')
        if not args.name:
            raise ApiError('Supply a name: dots create NAME. For graphical onboarding, run dots setup onboard.')
        name = launcher.validate_name(args.name)
        output(client.create(name, additional=args.additional), args.json)
    else:
        target = args.name if args.command == 'use' else args.dot
        if args.by_id and not target:
            raise ApiError('Supply a Dot ID with --by-id.')
        dot_id = target if args.by_id else client.resolve(target)
        path = client.path(dot_id)
        if args.command == 'use':
            result = client.request('PUT', '/tbo/primary', {'tbo_id': dot_id})
        elif args.command == 'show':
            result = client.request('GET', path)
        elif args.command in ('activity', 'tasks'):
            if args.command == 'tasks' and args.task:
                result = client.request('GET', path + '/tasks/' + encode_id(args.task, 'task'))
            else:
                result = client.pages(path + '/' + args.command, limit=5 if args.command == 'activity' else 25)
        elif args.command == 'room':
            result = client.request('POST', path + '/messaging-room')
        else:
            result = client.request('POST', path + '/runtime/' + args.command)
        output(result, args.json, args.command.capitalize())
        if args.command == 'activity' and args.open:
            # This is navigation, not task submission or evidence that a task ran.
            try:
                launcher.launch('activity', url='https://chatgpt.com/dots/' + encode_id(dot_id))
            except ValueError as error:
                raise ApiError('Activity loaded, but its page could not be opened. ' + str(error)) from None
    return 0
