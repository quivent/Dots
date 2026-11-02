"""Serialized JSONL transport from the Qwen terminal to the existing Dot client."""
from contextlib import ExitStack, redirect_stdout
import json
import sys

from .api import ApiError, DotClient
from .chat import Chat, message_text, terminal_text
from .main import Launcher
from .registry import Registry
from .relay import conversation_client


PROFILE_FIELDS = ('id', 'display_name', 'is_paused', 'status', 'last_check_in_at')


def public_profile(profile):
    return {key: value for key in PROFILE_FIELDS
            if isinstance(value := profile.get(key), (str, bool))}


class BridgeChat(Chat):
    def __init__(self, *args):
        super().__init__(*args)
        self.messages = {}

    def display(self, items):
        for item in reversed(items):
            text, mine = message_text(item)
            if text:
                self.messages[item['id']] = {
                    'id': item['id'], 'text': terminal_text(text), 'mine': bool(mine),
                }
                self.rendered[item['id']] = text
            elif item.get('deleted_at'):
                self.messages.pop(item['id'], None)
            self.seen.add(item['id'])


class Backend:
    def __init__(self, launcher=None, client_factory=None):
        self.launcher = launcher or Launcher()
        self.client_factory = client_factory or conversation_client
        self.connection = ExitStack()
        self.chat = None

    def close(self):
        self.chat = None
        self.connection.close()

    def snapshot(self):
        chat = self.require_chat()
        return {'name': terminal_text(chat.name), 'profile': public_profile(chat.profile),
                'pending': bool(chat.pending), 'messages': list(chat.messages.values())}

    def require_chat(self):
        if self.chat is None:
            raise ApiError('Choose a Dot before opening a conversation.')
        return self.chat

    def connect(self, params):
        dot = params.get('dot')
        if dot is not None and (not isinstance(dot, str) or not dot.strip()):
            raise ApiError('Dot target must be a nonempty name or ID.')
        by_id = params.get('by_id', False)
        if not isinstance(by_id, bool):
            raise ApiError('by_id must be a boolean.')
        if by_id and not dot:
            raise ApiError('Supply a Dot ID with by_id.')
        source = params.get('source', 'local')
        if source not in ('local', 'chatgpt'):
            raise ApiError('Terminal chat supports ChatGPT Dots only.')
        remote_id = dot
        if source == 'local':
            entry = Registry(self.launcher).resolve(dot, by_id)
            if entry['backend'] != 'chatgpt':
                raise ApiError('Hosted entries are Codex workers; choose a ChatGPT Dot.')
            remote_id = entry.get('remote_id')
            if not remote_id:
                raise ApiError('Creation is unconfirmed. Import the existing Dot before opening chat.')
        client = self.client_factory()
        if source == 'chatgpt' and not by_id:
            remote_id = client.resolve(dot)
        self.close()
        guard = Launcher(runtime=self.launcher.runtime / 'chat')
        connection = ExitStack()
        try:
            connection.enter_context(guard.locked())
            chat = BridgeChat(client, remote_id, guard.runtime)
            chat.display(chat.history())
        except BaseException:
            connection.close()
            raise
        self.connection, self.chat = connection, chat
        return self.snapshot()

    def request(self, method, params):
        if not isinstance(method, str) or not isinstance(params, dict):
            raise ApiError('Use a method string and an object for params.')
        if method == 'list':
            data = Registry(self.launcher).read()
            return [{key: entry.get(key) for key in
                     ('id', 'display_name', 'backend', 'status', 'is_paused')}
                    | {'selected': entry['id'] == data.get('selected')}
                    for entry in data['agents']]
        if method == 'connect':
            return self.connect(params)
        if method == 'close':
            self.close()
            return {'closed': True}
        chat = self.require_chat()
        if method == 'refresh':
            chat.refresh()
        elif method == 'send':
            text = params.get('text')
            if not isinstance(text, str):
                raise ApiError('Message text must be a string.')
            chat.send(text)
            message_id = chat.pending['message_id']
            chat.messages[message_id] = {
                'id': message_id, 'text': terminal_text(text), 'mine': True,
            }
        elif method == 'abandon':
            previous = chat.pending
            chat.pending = None
            try:
                chat.save()
            except OSError:
                chat.pending = previous
                raise
        elif method == 'status':
            chat.profile = chat.client.request('GET', chat.client.path(chat.dot_id))
            result = self.snapshot()
            try:
                response = chat.client.request('GET', chat.client.path(chat.dot_id) + '/tasks',
                                               query={'limit': 5})
                tasks = response.get('data') if isinstance(response, dict) else None
                if not isinstance(tasks, list) or not all(isinstance(t, dict) for t in tasks):
                    raise ApiError('Unexpected task status response.')
                result['tasks'] = [{key: terminal_text(task[key])
                                    for key in ('id', 'title', 'status', 'state') if key in task}
                                   for task in tasks]
            except ApiError as error:
                result['tasks'] = []
                result['task_error'] = terminal_text(str(error))
            return result
        else:
            raise ApiError('Unknown backend method: ' + terminal_text(method))
        return self.snapshot()


def serve(backend=None, input_stream=None, output_stream=None):
    backend = backend or Backend()
    input_stream = input_stream or sys.stdin
    output_stream = output_stream or sys.stdout
    try:
        for line in input_stream:
            identity = None
            method = None
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ApiError('Request must be a JSON object.')
                identity = request.get('id')
                if not isinstance(identity, (str, int)) or isinstance(identity, bool):
                    raise ApiError('Request id must be a string or integer.')
                method = request.get('method')
                with redirect_stdout(sys.stderr):
                    result = backend.request(method, request.get('params', {}))
                response = {'id': identity, 'result': result}
            except (ValueError, OSError) as error:
                response = {'id': identity, 'error': {'message': terminal_text(str(error)),
                            'pending': bool(backend.chat and backend.chat.pending)}}
            except Exception:
                response = {'id': identity, 'error': {'message': 'Dot backend request failed.',
                            'pending': bool(backend.chat and backend.chat.pending)}}
            output_stream.write(json.dumps(response, ensure_ascii=False) + '\n')
            output_stream.flush()
            if method == 'close' and 'result' in response:
                break
    finally:
        backend.close()


def main():
    serve()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
