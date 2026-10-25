"""Terminal conversations with account Dots. A send is recorded before its single POST."""
import hashlib
from datetime import datetime
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import time
import uuid

from rich.panel import Panel
from rich.text import Text

from .api import ApiError, DotClient, encode_id
from .ui import console

MAX_MESSAGE_CHARS = 50_000


def terminal_text(value):
    # Provider/user text must not inject terminal escapes or Rich markup.
    return ''.join(c for c in str(value) if c in '\n\t' or (c.isprintable() and c != '\x7f'))


def chat_header(name, paused):
    heading = Text('●  ', style='#a7f3d0')
    heading.append(terminal_text(name), style='bold #a7f3d0')
    heading.append('  ·  ' + ('paused' if paused else 'Dot conversation'), style='yellow' if paused else 'dim')
    heading.append('\n\n')
    for index, (command, description) in enumerate((('/refresh', 'history'), ('/wait', 'pending reply'),
                                                    ('/status', 'runtime'), ('/abandon', 'stop tracking'),
                                                    ('/copy [N]', 'copy response'), ('/quit', 'leave'))):
        if index in (2, 4):
            heading.append('\n')
        heading.append(command, style='bold #67e8f9')
        heading.append(' ' + description + '   ', style='dim')
    heading.append('\n\nReplies arrive automatically; you can keep composing.', style='dim')
    console.print(Panel(heading, title='dots', title_align='left', border_style='#475569', padding=(1, 2)))
    console.print(Text('Tasks delegated to Work or Codex can use those products’ allowance.', style='dim'))
    console.print()


def message_text(item):
    if item.get('deleted_at'):
        return '', False
    if isinstance(item.get('raw_messages'), list):
        parts = []
        for message in item['raw_messages']:
            if not isinstance(message, dict):
                continue
            author, metadata = message.get('author') or {}, message.get('metadata') or {}
            if not isinstance(author, dict) or not isinstance(metadata, dict):
                raise ApiError('Unexpected messaging content response.')
            if (author.get('role') != 'assistant' or message.get('channel') == 'analysis'
                    or metadata.get('is_hidden') or metadata.get('hidden')):
                continue
            content = message.get('content') or {}
            if not isinstance(content, dict) or not isinstance(content.get('parts', []), list):
                raise ApiError('Unexpected messaging content response.')
            parts.extend(p for p in content.get('parts', []) if isinstance(p, str))
        return '\n\n'.join(parts), False
    content = item.get('content') or {}
    sender = item.get('account_user_id')
    if (not isinstance(content, dict) or not isinstance(content.get('text', ''), str)
            or (sender is not None and not isinstance(sender, str))):
        raise ApiError('Unexpected messaging content response.')
    mine = item.get('sender_is_self', bool(sender) and not sender.startswith('calpico-member')
                    and item.get('role') != 'assistant')
    return content.get('text', ''), mine


def newest_first(items):
    """Room pages arrive chronologically; normalize before display/reply checks."""
    try:
        times = {item['id']: datetime.fromisoformat(item['created_at'].replace('Z', '+00:00')).timestamp()
                 for item in items}
    except (KeyError, ValueError, TypeError, AttributeError):
        # Older adapters without timestamps already supplied newest-first pages.
        return items
    return sorted(items, key=lambda item: times[item['id']], reverse=True)


class Chat:
    def __init__(self, client, dot_id, directory):
        self.client, self.dot_id = client, dot_id
        self.profile = client.request('GET', client.path(dot_id))
        self.name = self.profile.get('display_name') or dot_id
        self.room = self.profile.get('messaging_room_id')
        if not self.room:
            raise ApiError('This Dot has no messaging room. Run dots room DOT first.')
        self.path = '/messaging/rooms/' + encode_id(self.room) + '/messages'
        self.state_path = Path(directory) / (hashlib.sha256(self.room.encode()).hexdigest() + '.json')
        self.pending = json.loads(self.state_path.read_text()) if self.state_path.exists() else None
        self.seen = set()
        self.rendered = {}
        self.responses = {}
        self.response_numbers = {}
        self.transcript = []
        self.output = None

    def paused_notice(self):
        command = 'dots resume ' + shlex.quote(terminal_text(self.name))
        return ('This Dot is paused on the server. History is available. '
                'To wake it and send messages, run:\n' + command)

    def show_status(self):
        profile = self.client.request('GET', self.client.path(self.dot_id))
        self.profile = profile
        body = Text()
        rows = [('Dot', self.name),
                ('Runtime', 'Paused' if profile.get('is_paused') else
                 'Not paused' if profile.get('is_paused') is False else 'Unknown'),
                ('Account status', profile.get('status') or 'Not reported'),
                ('Last check-in', profile.get('last_check_in_at') or 'Not reported'),
                ('Delivery', ('Accepted · waiting for a reply' if self.pending.get('message_id')
                              else 'Unconfirmed · /wait to check') if self.pending else 'No pending message')]
        for label, value in rows:
            body.append(label + '  ', style='bold #67e8f9')
            body.append(terminal_text(value) + '\n')
        try:
            tasks = self.client.request('GET', self.client.path(self.dot_id) + '/tasks', query={'limit': 5})
            items = tasks.get('data') if isinstance(tasks, dict) else None
            if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
                raise ApiError('Unexpected task status response.')
            body.append('\nRecent tasks\n', style='bold #a7f3d0')
            if not items:
                body.append('No task activity reported.\n', style='dim')
            for item in items:
                body.append(terminal_text(str(item.get('title') or item.get('id') or 'Task')) + ' · ')
                body.append(terminal_text(str(item.get('status') or item.get('state') or 'Status not reported')) + '\n')
        except ApiError as error:
            body.append('\nTask activity unavailable: ' + terminal_text(str(error)) + '\n', style='yellow')
        body.append('\nLive tool steps, context usage, and credit balances are not exposed by this status view.', style='dim')
        (self.output or console).print(Panel(body, title='Dot status', title_align='left', border_style='#475569'))

    def save(self):
        if self.pending is None:
            self.state_path.unlink(missing_ok=True)
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=self.state_path.parent)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(self.pending, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def history(self, until=None):
        items, cursor, cursors = [], None, set()
        for _ in range(100):
            query = {'limit': 25}
            if cursor:
                query['before'] = cursor
            page = self.client.request('GET', self.path, query=query)
            if (not isinstance(page, dict) or not isinstance(page.get('items'), list)
                    or not all(isinstance(i, dict) and isinstance(i.get('id'), str) for i in page['items'])):
                raise ApiError('Unexpected messaging history response.')
            items.extend(page['items'])
            if until is None or any(i['id'] in until for i in page['items']):
                return newest_first(items)
            cursor = page.get('prev_cursor')
            if not cursor and len(page['items']) >= query['limit']:
                # The first-party client uses the oldest message ID when the
                # room endpoint omits its older-page cursor.
                cursor = newest_first(page['items'])[-1]['id']
            if not cursor:
                return newest_first(items)
            if not isinstance(cursor, str) or cursor in cursors:
                raise ApiError('Messaging history pagination did not advance.')
            cursors.add(cursor)
        raise ApiError('History scan limit reached. Pending delivery remains unconfirmed.')

    def display(self, items):
        for item in reversed(items):  # Messaging pages are newest first.
            text, mine = message_text(item)
            own_echo = mine and self.pending and (
                item['id'] == self.pending['message_id'] or
                (item.get('request_id') or item.get('idempotency_token')) == self.pending['request_id'])
            if own_echo:
                self.rendered[item['id']] = text
                self.seen.add(item['id'])
                continue
            if text and self.rendered.get(item['id']) != text:
                number = None
                if not mine:
                    number = self.response_numbers.setdefault(item['id'], len(self.response_numbers) + 1)
                    self.responses[number] = terminal_text(text)
                from .chat_transcript import outgoing_block, response_block
                block = (response_block(terminal_text(self.name), terminal_text(text), number)
                         if number is not None else outgoing_block(terminal_text(text)))
                self.transcript.append((block, number))
                message = Text()
                message.append(terminal_text('You' if mine else self.name) + ': ',
                               style='bold #67e8f9' if mine else 'bold #a7f3d0')
                message.append(terminal_text(text))
                if self.output:
                    if number is None:
                        self.output.print(block)
                    else:
                        self.output.response(block, number)
                else:
                    console.print(message)
                    if number is None:
                        console.print()
                    else:
                        console.print(Text(f'Response #{number} · /copy {number}', style='dim'))
                self.rendered[item['id']] = text
            self.seen.add(item['id'])

    def send(self, text):
        if self.pending:
            raise ApiError('A message is still pending. Use /wait or /refresh; /abandon explicitly stops tracking it.')
        if not text.strip() or len(text) > MAX_MESSAGE_CHARS or '\0' in text:
            raise ApiError(f'Use a text message of 1–{MAX_MESSAGE_CHARS:,} characters, without NUL characters.')
        profile = self.client.request('GET', self.client.path(self.dot_id))
        if profile.get('is_paused'):
            raise ApiError(self.paused_notice())
        baseline = self.history()
        self.seen.update(i['id'] for i in baseline)
        request_id = str(uuid.uuid4())
        self.pending = {'request_id': request_id, 'message_id': None,
                        'baseline': [i['id'] for i in baseline]}
        try:
            self.save()  # Survives interruption; no message text or credentials on disk.
        except OSError as error:
            # Nothing was posted: do not leave an unsent message blocking chat.
            self.pending = None
            raise ApiError('Could not save delivery tracking; no message was sent. ' + str(error)) from None
        body = {'content': {'text': text, 'attachments': []}, 'request_id': request_id,
                'idempotency_token': request_id,
                'timezone_offset_min': -int(time.localtime().tm_gmtoff / 60) if hasattr(time.localtime(), 'tm_gmtoff') else int((time.altzone if time.daylight and time.localtime().tm_isdst else time.timezone) / 60)}
        try:
            result = self.client.request('POST', self.path, body=body)
        except ApiError as error:
            # A rejected request is safe to correct; network/5xx/408 outcomes stay pending.
            if error.status and 400 <= error.status < 500 and error.status != 408:
                self.pending = None
                self.save()
            raise ApiError(str(error) + ' No automatic retry was made. Use /wait to check an uncertain delivery.') from None
        if not isinstance(result, dict) or not isinstance(result.get('id'), str) or not result['id']:
            raise ApiError('Delivery is unconfirmed. Use /wait to check history; the message will not be resent.')
        self.pending['message_id'] = result['id']
        self.save()

    def refresh(self):
        baseline = set(self.pending['baseline']) if self.pending else self.seen
        # An empty pre-send room still needs pagination to find our accepted
        # message. An empty set asks history to scan through to the oldest page.
        items = self.history(until=baseline) if self.pending or baseline else self.history()
        accepted_index = None
        if self.pending:
            for index, item in enumerate(items):
                if (item['id'] == self.pending['message_id'] or
                        (item.get('request_id') or item.get('idempotency_token')) == self.pending['request_id']):
                    accepted_index = index
                    if not self.pending['message_id']:
                        self.pending['message_id'] = item['id']
                        self.save()
                    break
        self.display(items)
        # Only messages newer than our confirmed user message count as replies.
        # They may come from another conversation participant; no causal claim is made.
        if accepted_index is not None and any(i['id'] not in baseline and
                                              message_text(i)[0] and not message_text(i)[1]
                                              for i in items[:accepted_index]):
            previous = self.pending
            self.pending = None
            try:
                self.save()
            except OSError:
                self.pending = previous
                raise
        return self.pending is None

    def wait(self, timeout, poll):
        if console.is_terminal:
            with console.status(Text('Waiting for a reply…', style='dim cyan'), spinner='dots'):
                return self._wait(timeout, poll)
        return self._wait(timeout, poll)

    def _wait(self, timeout, poll):
        deadline = time.monotonic() + timeout
        while True:
            if self.refresh():
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                console.print(Text('No reply confirmed yet. Use /wait to keep checking. The message will not be resent.', style='yellow'))
                return False
            time.sleep(min(poll, remaining))


def run(args, launcher):
    if getattr(args, 'status', False) and args.message is not None:
        raise ApiError('Use --status or --message, separately.')
    if args.timeout <= 0 or args.poll <= 0:
        raise ApiError('--timeout and --poll must be positive seconds.')
    if args.by_id and not args.dot:
        raise ApiError('Supply a Dot ID with --by-id.')
    if args.message is None and not getattr(args, 'status', False) and not sys.stdin.isatty():
        raise ApiError('Interactive chat needs a terminal. Use --message TEXT for a single message.')
    client = DotClient()
    dot_id = args.dot if args.by_id else client.resolve(args.dot)
    # Independent from launcher actions; serialize sessions sharing this runtime.
    from .main import Launcher
    guard = Launcher(runtime=launcher.runtime / 'chat')
    if getattr(args, 'status', False):
        # Read-only inspection remains available while the REPL owns its lock.
        Chat(client, dot_id, guard.runtime).show_status()
        return 0
    try:
        with guard.locked():
            chat = Chat(client, dot_id, guard.runtime)
            chat_header(chat.name, bool(chat.profile.get('is_paused')))
            chat.display(chat.history())
            if chat.pending:
                console.print(Text('◌ Previous message pending · checking without resending…', style='yellow'))
                chat.refresh()
            if chat.profile.get('is_paused'):
                console.print(Panel(Text(chat.paused_notice()), title='Paused', title_align='left', border_style='yellow'))
            if args.message is not None:
                chat.send(args.message)
                return 0 if chat.wait(args.timeout, args.poll) else 2
            from .chat_ui import interactive
            return interactive(chat, args.poll)
    except KeyboardInterrupt:
        console.print(Text('\nChat closed. Any pending send is saved; it will not be resent automatically.', style='dim'))
        return 130
