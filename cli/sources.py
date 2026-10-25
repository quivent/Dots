"""One source selection for saved identities, account Dots and hosted workers."""
from copy import copy

from .api import ApiError, DotClient
from .registry import Registry
from .ui import output

AGENT_COMMANDS = {'list', 'create', 'import', 'forget', 'use', 'show', 'rename', 'chat',
                  'activity', 'tasks', 'pause', 'resume', 'room'}


def import_dots(args, launcher):
    if args.source not in ('chatgpt', 'hosted'):
        raise ApiError('Choose an import source: dots import --source chatgpt (or --source hosted).')
    if args.source == 'hosted':
        from .hosted import HostedClient
        client = HostedClient()
    else:
        client = DotClient()
    if args.name and not args.dot:
        raise ApiError('--name requires a single Dot target.')
    alias = launcher.validate_name(args.name) if args.name else None
    if args.dot:
        identity = args.dot if args.by_id else client.resolve(args.dot)
        profiles = [client.request('GET', client.path(identity))]
    else:
        if args.by_id:
            raise ApiError('Supply a Dot ID with --by-id.')
        profiles = client.list()
    registry = Registry(launcher)
    entries = [registry.remember(profile, args.source, alias) for profile in profiles]
    output(entries, args.json, 'Saved Dots')
    return 0


def run(args, launcher):
    from . import cloud, chat
    if args.local and args.source not in ('local', None):
        raise ApiError('--local cannot be combined with a different --source.')
    args.source = 'local' if args.local else (args.source or 'local')
    if args.command == 'import':
        return import_dots(args, launcher)
    if args.source == 'shortcuts':
        if args.command not in ('list', 'create', 'use', 'activity'):
            raise ApiError('Shortcuts support list, create, use and activity only; use dots configure for URLs.')
        args.local = True
        return cloud.run(args, launcher)
    args.local = False
    if args.source == 'chatgpt' and args.command != 'create':
        if args.command == 'forget':
            raise ApiError('Forget removes saved references only; omit --source chatgpt.')
        # Direct account commands preserve their original semantics.
        return (chat.run if args.command == 'chat' else cloud.run)(args, launcher)
    if args.source == 'hosted':
        return hosted(args, launcher)
    registry = Registry(launcher)
    if args.command == 'list':
        data = registry.read()
        entries = [{**e, 'selected': e['id'] == data.get('selected'), 'source': 'local'} for e in data['agents']]
        from .ui import show_saved
        output(entries, args.json, render=show_saved)
        return 0
    if args.command == 'create':
        if args.no_open:
            raise ApiError('--no-open applies to --source shortcuts only.')
        if not args.name:
            raise ApiError('Supply a name: dots create NAME')
        name = launcher.validate_name(args.name)
        client = DotClient()
        if not client.token or not client.account_id:
            raise ApiError('No usable ChatGPT sign-in found. Run dots auth before creating a Dot.')
        # Discovery is read-only. Do it before reserving a name so a failed GET
        # cannot leave a creation marked uncertain when no POST was attempted.
        additional = args.additional
        if additional is None:
            additional = bool(client.list())
        reserved = registry.reserve(name)
        if not args.json:
            from rich.console import Console
            Console(stderr=True).print('Creating ' + name + '; initialization can take several minutes.', markup=False)
        try:
            profile = client.create(name, additional=additional)
        except ApiError as error:
            if error.status and 400 <= error.status < 500 and error.status != 408:
                registry.forget(reserved)  # Definitive rejection; no identity to recover.
            else:
                registry.creation_failed(reserved, str(error))
            raise
        entry = registry.remember(profile, reserved_id=reserved['id'])
        registry.select(entry)
        output(entry, args.json)
        return 0
    target = args.name if args.command == 'use' else args.dot
    entry = registry.resolve(target, args.by_id)
    if args.command == 'use':
        registry.select(entry)
        output(entry, args.json)
        return 0
    if args.command == 'forget':
        registry.forget(entry)
        output({'forgotten': entry['display_name'], 'provider_changed': False}, args.json)
        return 0
    if args.command == 'rename':
        output(registry.rename(entry, launcher.validate_name(args.name)), args.json)
        return 0
    if not entry.get('remote_id'):
        if args.command == 'show':
            output(entry, args.json)
            return 0
        raise ApiError('Creation is unconfirmed. Check dots list --source chatgpt; import the existing Dot by ID with dots import ID --by-id --source chatgpt --name NAME to recover this saved name. Nothing will be recreated automatically.')
    remote = copy(args)
    remote.dot, remote.by_id, remote.source = entry['remote_id'], True, entry['backend']
    if entry['backend'] == 'hosted':
        return hosted(remote, launcher)
    if args.command == 'show':
        profile = DotClient().request('GET', DotClient.path(entry['remote_id']))
        entry = registry.remember(profile, alias=entry['display_name'])
        output({'saved': entry, 'profile': profile}, args.json)
        return 0
    return (chat.run if args.command == 'chat' else cloud.run)(remote, launcher)


def hosted(args, launcher):
    if args.command == 'chat':
        raise ApiError('These hosted agents are Codex workers: conversation uses Codex allowance. Terminal chat defaults to actual ChatGPT Dots; run dots import --source chatgpt, then dots chat NAME.')
    if args.command in ('create', 'rename', 'forget', 'room', 'use'):
        raise ApiError('Hosted workers are managed separately. Import an existing hosted identity with dots import --source hosted; saved aliases support use, rename and forget locally.')
    from .hosted import HostedClient
    client = HostedClient()
    if args.command == 'list':
        output([{**e, 'backend': 'hosted', 'conversation_usage': 'Codex allowance'} for e in client.list()], args.json, 'Hosted Codex workers')
        return 0
    if args.by_id and not args.dot:
        raise ApiError('Supply an ID with --by-id.')
    identity = args.dot if args.by_id else client.resolve(args.dot)
    path = client.path(identity)
    if args.command in ('activity', 'tasks'):
        if getattr(args, 'task', None) or getattr(args, 'open', False):
            raise ApiError('Hosted --task and --open are not supported.')
        result = client.request('GET', path + '/' + args.command)
    elif args.command == 'show':
        result = client.request('GET', path)
    elif args.command in ('pause', 'resume'):
        result = client.request('POST', path + '/runtime/' + args.command)
    else:
        raise ApiError('Unsupported hosted operation.')
    output(result, args.json)
    return 0
