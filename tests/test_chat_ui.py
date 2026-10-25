"""Exercise simultaneous terminal composition and delivery with an offline Dot."""
import asyncio
from contextlib import redirect_stdout
import io
import subprocess
import threading
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from prompt_toolkit import PromptSession
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.data_structures import Point
from prompt_toolkit.mouse_events import MouseButton, MouseEvent, MouseEventType

from cli.api import ApiError
from cli.chat_ui import Conversation
from cli.chat import Chat


class FakeChat:
    def __init__(self):
        self.pending = None
        self.posts = []
        self.receives = 0
        self.release_send = threading.Event()
        self.release_send.set()
        self.failure = None

    def send(self, text):
        self.pending = {'request_id': 'one'}
        self.posts.append(text)
        self.release_send.wait(2)
        if self.failure:
            self.pending = None
            raise self.failure

    def refresh(self):
        self.receives += 1
        return not self.pending

    def save(self):
        pass


class ChatUITests(unittest.IsolatedAsyncioTestCase):
    async def until(self, predicate):
        for _ in range(200):
            if predicate():
                return
            await asyncio.sleep(.005)
        self.fail('Expected terminal state did not arrive')

    async def test_background_receive_does_not_replace_typed_draft(self):
        chat = FakeChat()
        with create_pipe_input() as input, patch('cli.chat_ui.console.print'):
            session = PromptSession(input=input, output=DummyOutput())
            ui = Conversation(chat, .01)
            task = asyncio.create_task(ui.run(session))
            await self.until(lambda: session.app.is_running)
            self.assertTrue(session.app.erase_when_done)
            input.send_text('a draft that must stay')
            await self.until(lambda: session.default_buffer.text == 'a draft that must stay')
            count = chat.receives
            await self.until(lambda: chat.receives > count + 1)
            self.assertEqual(session.default_buffer.text, 'a draft that must stay')
            input.send_bytes(b'\x01\x0b'); input.send_text('/quit'); input.send_bytes(b'\x13')
            self.assertEqual(await task, 0)

    async def test_sending_allows_composition_and_blocks_a_duplicate(self):
        chat = FakeChat(); chat.release_send.clear()
        ui = Conversation(chat, .01)
        with patch('cli.chat_ui.console.print'):
            self.assertTrue(ui.submit('first'))
            await self.until(lambda: bool(chat.posts))
            # This runs while the POST is still blocked in its worker thread.
            self.assertFalse(ui.submit('second'))
            self.assertFalse(ui.sending.done())
            chat.release_send.set()
            await ui.sending
        self.assertEqual(chat.posts, ['first'])
        self.assertEqual(ui.status, 'Sent · waiting for reply')

    async def test_pending_send_keeps_the_unsent_draft_in_the_editor(self):
        chat = FakeChat(); chat.pending = {'request_id': 'earlier'}
        with create_pipe_input() as input, patch('cli.chat_ui.console.print'):
            session = PromptSession(input=input, output=DummyOutput())
            ui = Conversation(chat, .01); task = asyncio.create_task(ui.run(session))
            await self.until(lambda: session.app.is_running)
            input.send_text('keep me'); input.send_bytes(b'\x13')
            await self.until(lambda: session.default_buffer.text == 'keep me')
            self.assertEqual(chat.posts, [])
            # Replace the restored draft with an explicit exit command.
            input.send_bytes(b'\x01\x0b'); input.send_text('/quit'); input.send_bytes(b'\x13')
            self.assertEqual(await task, 0)

    async def test_rejected_send_restores_empty_editor(self):
        chat = FakeChat(); chat.failure = ApiError('Rejected', status=403)
        ui = Conversation(chat, .01); ui.session = Mock(); ui.session.default_buffer.text = ''
        with patch('cli.chat_ui.console.print'):
            ui.submit('unsent text'); await ui.sending
        self.assertEqual(ui.session.default_buffer.text, 'unsent text')
        self.assertEqual(chat.posts, ['unsent text'])

    async def test_receive_failures_are_reported_once_and_can_recover(self):
        chat = FakeChat(); chat.refresh = Mock(side_effect=[ApiError('Offline'), ApiError('Offline'), True])
        ui = Conversation(chat, .01)
        with patch('cli.chat_ui.console.print') as output:
            await ui.refresh(); await ui.refresh(); await ui.refresh()
        self.assertEqual(output.call_count, 1)
        self.assertEqual(ui.status, 'Connected')

    async def test_receive_survives_filesystem_failure_and_recovers(self):
        chat = FakeChat()
        chat.refresh = Mock(side_effect=[OSError('Disk full'), True, True])
        ui = Conversation(chat, .01)
        with patch('cli.chat_ui.console.print') as output:
            task = asyncio.create_task(ui.receive())
            await self.until(lambda: chat.refresh.call_count >= 2)
            ui.closed = True; ui.wake.set()
            await task
        self.assertEqual(ui.status, 'Connected')
        self.assertEqual(output.call_count, 1)

    async def test_status_keeps_editor_active_and_exit_waits_for_status(self):
        chat = FakeChat(); entered = threading.Event(); release = threading.Event()
        def show_status():
            entered.set(); release.wait(2)
        chat.show_status = Mock(side_effect=show_status)
        with create_pipe_input() as input, patch('cli.chat_ui.console.print'):
            session = PromptSession(input=input, output=DummyOutput())
            ui = Conversation(chat, .01); task = asyncio.create_task(ui.run(session))
            await self.until(lambda: session.app.is_running)
            input.send_text('/status'); input.send_bytes(b'\x13')
            await self.until(lambda: entered.is_set() and session.app.is_running)
            input.send_text('next draft')
            await self.until(lambda: session.default_buffer.text == 'next draft')
            input.send_bytes(b'\x01\x0b'); input.send_text('/quit'); input.send_bytes(b'\x13')
            await self.until(lambda: ui.closed)
            self.assertFalse(task.done())
            release.set()
            self.assertEqual(await task, 0)
        chat.show_status.assert_called_once()

    async def test_failed_abandon_keeps_pending(self):
        chat = FakeChat(); chat.pending = {'request_id': 'earlier'}
        chat.save = Mock(side_effect=OSError('Read only'))
        ui = Conversation(chat, .01)
        with self.assertRaises(OSError):
            await ui.abandon()
        self.assertEqual(chat.pending, {'request_id': 'earlier'})

    async def test_background_commands_are_deduplicated_and_report_failures(self):
        chat = FakeChat(); chat.show_status = Mock(side_effect=ApiError('Status unavailable'))
        ui = Conversation(chat, .01)
        with patch('cli.chat_ui.console.print') as output:
            ui.command(ui.show_status)
            ui.command(ui.show_status)
            await asyncio.gather(*ui.commands)
            self.assertEqual(chat.show_status.call_count, 1)
            self.assertIn('Status unavailable', output.call_args.args[0].plain)
            ui.command(ui.show_status)
            await asyncio.gather(*ui.commands)
        self.assertEqual(chat.show_status.call_count, 2)

    async def test_send_styles_label_only_and_sanitizes_user_controls(self):
        chat = FakeChat(); ui = Conversation(chat, .01)
        with patch('cli.chat_ui.console.print') as output:
            ui.submit('body\x1b[31m')
            message = output.call_args.args[0]
            self.assertEqual(message.plain, 'You: body[31m')
            self.assertFalse(message.style)
            self.assertEqual([(span.start, span.end) for span in message.spans], [(0, 5)])
            await ui.sending

    async def test_copy_passes_whole_response_as_stdin_and_does_not_touch_draft(self):
        chat = FakeChat(); chat.responses = {1: 'First', 2: '日本語\n[code] $(literal)'}
        ui = Conversation(chat, .01); ui.session = Mock()
        ui.session.default_buffer.text = 'draft stays'
        with patch('cli.main.Launcher.clipboard_command', return_value={
                'argv': ['fixture-clipboard'], 'input': chat.responses[2]}), \
                patch('cli.chat_ui.subprocess.run', return_value=Mock(returncode=0)) as run:
            await ui.copy_response()
        run.assert_called_once_with(['fixture-clipboard'], input=chat.responses[2],
                                    encoding='utf-8', capture_output=True, timeout=10)
        self.assertEqual(ui.session.default_buffer.text, 'draft stays')
        self.assertEqual(ui.copy_notice, 'Copied response #2')
        self.assertEqual(chat.posts, [])

    async def test_every_response_has_accessible_mouse_copy_button(self):
        chat = FakeChat(); chat.responses = {i: f'Reply {i}' for i in range(1, 8)}
        ui = Conversation(chat, .01)
        event = MouseEvent(Point(0, 0), MouseEventType.MOUSE_UP, MouseButton.LEFT, ())
        found = set()
        with patch.object(ui, 'start_copy') as copy:
            while True:
                fragments = ui.toolbar()
                for fragment in fragments:
                    if fragment[1].startswith('[Copy #'):
                        number = int(fragment[1].split('#')[1].split(']')[0])
                        fragment[2](event)
                        copy.assert_called_with(number)
                        found.add(number)
                older = next((f for f in fragments if f[1].startswith('[Older]')), None)
                if older is None:
                    break
                older[2](event)
        self.assertEqual(found, set(chat.responses))

    async def test_copy_failures_are_reported_without_claiming_success(self):
        chat = FakeChat(); chat.responses = {1: 'Reply'}; ui = Conversation(chat, .01)
        for failure in (Mock(returncode=1), subprocess.TimeoutExpired('copy', 10)):
            with patch('cli.main.Launcher.clipboard_command', return_value={'argv': ['copy'], 'input': 'Reply'}), \
                    patch('cli.chat_ui.subprocess.run', **({'side_effect': failure} if isinstance(failure, Exception)
                                                           else {'return_value': failure})), \
                    patch('cli.chat_ui.console.print') as output:
                ui.start_copy(1)
                await asyncio.gather(*ui.commands)
                self.assertTrue(output.called)
                self.assertEqual(ui.copy_notice, '')
                self.assertEqual(ui.status, 'Connected')
        with self.assertRaisesRegex(ApiError, 'No response #99'):
            await ui.copy_response(99)

    async def test_copy_command_keeps_the_repl_available(self):
        chat = FakeChat(); chat.responses = {1: 'Reply'}
        entered = threading.Event(); release = threading.Event()
        def copy(*args, **kwargs):
            entered.set(); release.wait(2); return Mock(returncode=0)
        with create_pipe_input() as input, patch('cli.chat_ui.console.print'), \
                patch('cli.main.Launcher.clipboard_command', return_value={'argv': ['copy'], 'input': 'Reply'}), \
                patch('cli.chat_ui.subprocess.run', side_effect=copy):
            session = PromptSession(input=input, output=DummyOutput())
            ui = Conversation(chat, .01); task = asyncio.create_task(ui.run(session))
            await self.until(lambda: session.app.is_running)
            input.send_text('/copy 1'); input.send_bytes(b'\x13')
            await self.until(lambda: entered.is_set() and session.app.is_running)
            input.send_text('draft while copying')
            await self.until(lambda: session.default_buffer.text == 'draft while copying')
            release.set()
            await self.until(lambda: ui.copy_notice == 'Copied response #1')
            self.assertEqual(session.default_buffer.text, 'draft while copying')
            input.send_bytes(b'\x01\x0b'); input.send_text('/quit'); input.send_bytes(b'\x13')
            self.assertEqual(await task, 0)
        self.assertEqual(chat.posts, [])

    async def test_page_keys_and_wheel_scroll_history_without_changing_draft(self):
        from rich.text import Text
        chat = FakeChat()
        chat.transcript = [(Text('\n'.join(f'History line {i}' for i in range(100))), None)]
        with create_pipe_input() as input, patch('cli.chat_ui.console.print'):
            session = PromptSession(input=input, output=DummyOutput())
            ui = Conversation(chat, .01); task = asyncio.create_task(ui.run(session))
            await self.until(lambda: session.app.is_running and ui.screen.top > 0)
            input.send_text('unsent draft')
            await self.until(lambda: session.default_buffer.text == 'unsent draft')
            bottom = ui.screen.top
            input.send_bytes(b'\x1b[5~')
            await self.until(lambda: ui.screen.top < bottom)
            page_top = ui.screen.top
            input.send_bytes(b'\x1b[<64;3;3M')
            await self.until(lambda: ui.screen.top < page_top)
            wheel_top = ui.screen.top
            ui.screen.print(Text('New incoming message'))
            await asyncio.sleep(.03)
            self.assertEqual(ui.screen.top, wheel_top)
            input.send_bytes(b'\x1b[6~')
            await self.until(lambda: ui.screen.top > wheel_top)
            input.send_bytes(b'\x1b[1;5F')
            await self.until(lambda: ui.screen.follow)
            self.assertEqual(session.default_buffer.text, 'unsent draft')
            self.assertEqual(chat.posts, [])
            input.send_bytes(b'\x01\x0b'); input.send_text('/quit'); input.send_bytes(b'\x13')
            self.assertEqual(await task, 0)

    async def test_sends_keep_one_application_running_and_eof_exits(self):
        chat = FakeChat(); resets = []
        with create_pipe_input() as input, patch('cli.chat_ui.console.print'):
            session = PromptSession(input=input, output=DummyOutput())
            session.app.on_reset += lambda app: resets.append(True)
            ui = Conversation(chat, .01); task = asyncio.create_task(ui.run(session))
            await self.until(lambda: session.app.is_running)
            input.send_text('first'); input.send_bytes(b'\x13')
            await self.until(lambda: chat.posts == ['first'] and ui.sending.done())
            chat.pending = None
            input.send_text('second'); input.send_bytes(b'\x13')
            await self.until(lambda: chat.posts == ['first', 'second'] and ui.sending.done())
            self.assertEqual(len(resets), 1)
            input.send_bytes(b'\x04')
            self.assertEqual(await task, 0)

    async def test_long_bracketed_paste_returns_to_bottom_sends_once_and_displays_reply(self):
        from rich.text import Text
        posts = []
        old = {'id': 'old', 'account_user_id': 'human', 'content': {'text': 'Earlier'}}
        client = Mock(); client.path.return_value = '/tbo/fixture'
        def request(method, path, **kwargs):
            if path == '/tbo/fixture':
                return {'display_name': 'Fixture', 'messaging_room_id': 'room', 'is_paused': False}
            if method == 'POST':
                posts.append(kwargs['body'])
                return {'id': 'accepted'}
            if posts:
                return {'items': [
                    {'id': 'reply', 'role': 'assistant', 'content': {'text': '**Received the entire block.**'}},
                    {'id': 'accepted', 'account_user_id': 'human', 'request_id': posts[0]['request_id'],
                     'content': {'text': posts[0]['content']['text']}}, old]}
            return {'items': [old]}
        client.request.side_effect = request
        with tempfile.TemporaryDirectory() as directory, create_pipe_input() as input:
            chat = Chat(client, 'fixture', Path(directory))
            chat.transcript = [(Text('\n'.join(f'Earlier {i}' for i in range(100))), None)]
            session = PromptSession(input=input, output=DummyOutput())
            ui = Conversation(chat, .01); task = asyncio.create_task(ui.run(session))
            await self.until(lambda: session.app.is_running and ui.screen.top > 0)
            ui.screen.scroll(-20)
            self.assertFalse(ui.screen.follow)
            block = '/Users/jay/source.py\n' + 'line of source\n' * 3000
            input.send_bytes(b'\x1b[200~' + block.encode() + b'\x1b[201~')
            await self.until(lambda: session.default_buffer.text == block)
            self.assertEqual(session.default_buffer.cursor_position, len(block))
            self.assertTrue(ui.screen.follow)
            await self.until(lambda: ui.screen.top == max(0, len(ui.screen.lines) - ui.screen.height))
            await self.until(lambda: session.app.layout.current_window.render_info is not None
                             and session.app.layout.current_window.render_info.displayed_lines[-1]
                             == session.default_buffer.document.line_count - 1)
            self.assertFalse(posts, 'Pasting must wait for Ctrl-S or Send')
            self.assertIn(f'{len(block):,}/50,000', ''.join(f[1] for f in ui.toolbar()))
            input.send_bytes(b'\x13')
            await self.until(lambda: bool(posts) and chat.pending is None and 'reply' in chat.rendered)
            self.assertEqual(len(posts), 1)
            self.assertEqual(posts[0]['content']['text'], block)
            self.assertEqual(chat.responses[1], '**Received the entire block.**')
            await self.until(lambda: bool(ui.screen.copy_lines))
            input.send_text('/quit'); input.send_bytes(b'\x13')
            self.assertEqual(await task, 0)

    async def test_alt_enter_inserts_newline_and_ctrl_s_sends_multiline_draft(self):
        chat = FakeChat()
        with create_pipe_input() as input:
            session = PromptSession(input=input, output=DummyOutput())
            ui = Conversation(chat, .01); task = asyncio.create_task(ui.run(session))
            await self.until(lambda: session.app.is_running)
            input.send_text('first'); input.send_bytes(b'\x1b\r'); input.send_text('second')
            await self.until(lambda: session.default_buffer.text == 'first\nsecond')
            self.assertEqual(chat.posts, [])
            input.send_bytes(b'\x13')
            await self.until(lambda: chat.posts == ['first\nsecond'])
            input.send_text('/quit'); input.send_bytes(b'\x13')
            self.assertEqual(await task, 0)

    async def test_unmarked_paste_never_sends_or_executes_lines_even_when_slow(self):
        for ending in ('\n', '\r'):
            with self.subTest(ending=repr(ending)), create_pipe_input() as input:
                chat = FakeChat()
                session = PromptSession(input=input, output=DummyOutput())
                ui = Conversation(chat, .01); task = asyncio.create_task(ui.run(session))
                await self.until(lambda: session.app.is_running)
                lines = ['/quit', '', '/status', '```python', 'print("keep all lines")', '```']
                for line in lines:
                    # A terminal can stream a paste over multiple reads without
                    # bracketed-paste markers. Timing must never authorize send.
                    input.send_text(line + ending)
                    await asyncio.sleep(.03)
                expected = '\n'.join(lines) + '\n'
                await self.until(lambda: session.default_buffer.text == expected)
                self.assertEqual(chat.posts, [])
                self.assertFalse(ui.closed)
                self.assertTrue(session.app.is_running)
                send = next(f for f in ui.toolbar() if f[1] == '[Send]')
                send[2](MouseEvent(Point(0, 0), MouseEventType.MOUSE_UP, MouseButton.LEFT, ()))
                await self.until(lambda: chat.posts == [expected])
                input.send_bytes(b'\x04')
                self.assertEqual(await task, 0)

    async def test_chunked_bracketed_paste_waits_for_ctrl_s(self):
        chat = FakeChat()
        with create_pipe_input() as input:
            session = PromptSession(input=input, output=DummyOutput())
            ui = Conversation(chat, .01); task = asyncio.create_task(ui.run(session))
            await self.until(lambda: session.app.is_running)
            block = 'first\n\n/quit\nlast\n'
            payload = b'\x1b[200~' + block.encode() + b'\x1b[201~'
            for offset in range(0, len(payload), 3):
                input.send_bytes(payload[offset:offset + 3])
                await asyncio.sleep(.005)
            await self.until(lambda: session.default_buffer.text == block)
            self.assertEqual(chat.posts, [])
            input.send_bytes(b'\x13')
            await self.until(lambda: chat.posts == [block])
            input.send_bytes(b'\x04')
            self.assertEqual(await task, 0)

    async def test_exit_waits_for_single_inflight_send_before_unlocking(self):
        chat = FakeChat(); chat.release_send.clear()
        with create_pipe_input() as input, patch('cli.chat_ui.console.print'):
            session = PromptSession(input=input, output=DummyOutput())
            ui = Conversation(chat, .01); task = asyncio.create_task(ui.run(session))
            await self.until(lambda: session.app.is_running)
            input.send_text('one message'); input.send_bytes(b'\x13')
            await self.until(lambda: bool(chat.posts))
            input.send_text('/quit'); input.send_bytes(b'\x13'); await asyncio.sleep(.03)
            self.assertFalse(task.done())
            chat.release_send.set()
            self.assertEqual(await task, 0)
        self.assertEqual(chat.posts, ['one message'])

    async def test_exit_waits_for_inflight_receive_before_releasing_room(self):
        chat = FakeChat(); entered = threading.Event(); release = threading.Event()
        def refresh():
            entered.set(); release.wait(2); return True
        chat.refresh = refresh
        with create_pipe_input() as input, patch('cli.chat_ui.console.print'):
            session = PromptSession(input=input, output=DummyOutput())
            ui = Conversation(chat, .01); task = asyncio.create_task(ui.run(session))
            await self.until(lambda: session.app.is_running and entered.is_set())
            input.send_text('/quit'); input.send_bytes(b'\x13'); await asyncio.sleep(.03)
            self.assertFalse(task.done())
            release.set(); self.assertEqual(await task, 0)

    async def test_next_draft_can_be_typed_while_post_is_inflight(self):
        chat = FakeChat(); chat.release_send.clear()
        with create_pipe_input() as input, patch('cli.chat_ui.console.print'):
            session = PromptSession(input=input, output=DummyOutput())
            ui = Conversation(chat, .01); task = asyncio.create_task(ui.run(session))
            await self.until(lambda: session.app.is_running)
            input.send_text('first'); input.send_bytes(b'\x13')
            await self.until(lambda: bool(chat.posts))
            input.send_text('next draft')
            await self.until(lambda: session.default_buffer.text == 'next draft')
            self.assertFalse(ui.sending.done())
            chat.release_send.set(); await ui.sending
            input.send_bytes(b'\x01\x0b'); input.send_text('/quit'); input.send_bytes(b'\x13')
            self.assertEqual(await task, 0)
        self.assertEqual(chat.posts, ['first'])

    @unittest.skipUnless(__import__('os').name == 'posix', 'Requires a PTY')
    def test_real_terminal_mouse_copies_response_and_preserves_composition(self):
        import fcntl
        import os
        import pty
        import select
        import struct
        import sys
        import termios
        import time
        code = '''
from unittest.mock import Mock, patch
from cli.chat_ui import interactive
from cli.chat_transcript import response_block
class Chat:
 pending=None
 responses={1:'Clipboard café\\nsecond line'}
 transcript=[(response_block('Fixture', responses[1], 1), 1)]
 def refresh(self):return True
 def save(self):pass
 def send(self,text):print('POSTED:'+text)
copies=0
def copied(*args,**kwargs):
 global copies
 copies+=1
 assert kwargs['input'] == Chat.responses[1]
 print('COPIED_COMPLETE_RESPONSE_'+str(copies))
 return Mock(returncode=0)
with patch('cli.main.Launcher.clipboard_command',return_value={'argv':['fixture-copy'],'input':Chat.responses[1]}),patch('cli.chat_ui.subprocess.run',side_effect=copied):
 interactive(Chat(),.03)
'''
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 80, 0, 0))
        environment = dict(os.environ, TERM='xterm-256color')
        environment.pop('PROMPT_TOOLKIT_NO_CPR', None)
        process = subprocess.Popen([sys.executable, '-c', code], stdin=slave, stdout=slave,
                                   stderr=slave, env=environment)
        os.close(slave)
        data = b''; answered = 0

        def read_until(marker):
            nonlocal data, answered
            deadline = time.monotonic() + 8
            while (marker not in data if marker else process.poll() is None) and time.monotonic() < deadline:
                if select.select([master], [], [], .1)[0]:
                    try:
                        data += os.read(master, 65536)
                    except OSError:
                        break
                    # Act as a terminal reporting the initial cursor position;
                    # prompt_toolkit uses this to place clickable footer rows.
                    requests = data.count(b'\x1b[6n')
                    while answered < requests:
                        os.write(master, b'\x1b[1;1R'); answered += 1
            if marker:
                self.assertIn(marker, data, data[-2000:])
        try:
            read_until(b'[Copy #1]')
            os.write(master, b'retained draft')
            read_until(b'retained draft')
            os.write(master, b'\x1b[<0;3;24M\x1b[<0;3;24m')
            read_until(b'COPIED_COMPLETE_RESPONSE_1')
            # The inline button is on row 4: title, sender, Markdown body, Copy.
            os.write(master, b'\x1b[<0;3;4M\x1b[<0;3;4m')
            read_until(b'COPIED_COMPLETE_RESPONSE_2')
            os.write(master, b'\x13')
            read_until(b'POSTED:retained draft')
            os.write(master, b'/quit\x13')
            read_until(None)
            self.assertEqual(process.wait(timeout=5), 0)
            self.assertEqual(data.count(b'COPIED_COMPLETE_RESPONSE'), 2)
        finally:
            if process.poll() is None:
                process.kill(); process.wait()
            os.close(master)

    @unittest.skipUnless(__import__('os').name == 'posix', 'Requires a PTY')
    def test_real_terminal_reply_and_typing_do_not_duplicate_send(self):
        import json
        import fcntl
        import os
        import pty
        import select
        import struct
        import subprocess
        import sys
        import termios
        import time
        code = '''
import time
from cli.chat_ui import interactive
from cli.ui import console
from rich.text import Text
class Chat:
 pending=None
 def __init__(self):self.start=time.monotonic();self.received=False
 def refresh(self):
  if not self.received and time.monotonic()-self.start>.8:
   console.print(Text('INCOMING_CHECK'));self.received=True
  return True
 def send(self,text):console.print(Text('POSTED:'+text))
 def save(self):pass
interactive(Chat(),.03)
'''
        master, slave = pty.openpty()
        # PTYs start with zero rows/columns on some hosts. Use an actual screen
        # size so prompt wrapping, redraw and the status toolbar are exercised.
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 80, 0, 0))
        process = subprocess.Popen([sys.executable, '-c', code], stdin=slave, stdout=slave,
                                   stderr=slave, env=dict(os.environ, TERM='xterm-256color',
                                                         PROMPT_TOOLKIT_NO_CPR='1'))
        os.close(slave)
        data = b''
        def read_until(marker):
            nonlocal data
            deadline = time.monotonic() + 8
            while (marker not in data if marker else process.poll() is None) and time.monotonic() < deadline:
                if select.select([master], [], [], .1)[0]:
                    try:data += os.read(master, 65536)
                    except OSError:break
            if marker:
                self.assertIn(marker, data, data[-2000:])
        try:
            read_until(b'You')
            os.write(master, b'composing here')
            read_until(b'INCOMING_CHECK')
            os.write(master, b'\x13')
            read_until(b'POSTED:composing here')
            os.write(master, b'/quit\x13')
            read_until(None)
            self.assertEqual(process.wait(timeout=5), 0)
            self.assertEqual(data.count(b'POSTED:composing here'), 1)
            # Exercise the real Rich -> stdout proxy -> terminal path. A plain
            # marker alone passes even when every styled send label is broken.
            self.assertRegex(data, rb'\x1b\[[0-9;]*mYou: ')
            self.assertNotIn(b'?[1mYou:', data)
            self.assertNotIn(b'?[0m', data)
        finally:
            if process.poll() is None:process.kill();process.wait()
            os.close(master)
