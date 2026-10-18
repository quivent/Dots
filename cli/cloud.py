"""CLI commands for account-backed Dot operations."""
import getpass
import json
import sys

from .api import ApiError, DotClient, SERVICE, credential_store, credentials, encode_id


def output(value, raw=False, title='Dots'):
    from .ui import console, show_table
    from rich.table import Column
    if raw:
        print(json.dumps(value, indent=2, ensure_ascii=False))
    elif isinstance(value, list):
        if not value:
            console.print('No records returned.')
            return
        if any(not isinstance(item, dict) for item in value):
            raise ApiError('Unexpected record in internal API response. Try --json.')
        show_table((Column('ID', style='green'), 'Name / title', 'Status'),
                   ((item.get('id', item.get('thread_id', '')),
                     item.get('display_name', item.get('title', item.get('name', ''))),
                     item.get('status', item.get('state', ''))) for item in value), title=title)
    else:
        # Render unrecognized profile fields faithfully instead of inventing a schema.
        from rich.json import JSON
        console.print(JSON.from_data(value))


def run(args, launcher):
    """Execute an account command selected by the command catalog."""
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
