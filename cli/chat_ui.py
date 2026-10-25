"""@purpose Keep terminal composition and incoming Dot messages independent.
@owns Transcript/composer layout, serialized chat I/O, copy controls and delivery state.
"""
import asyncio
import subprocess

from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.margins import ScrollbarMargin
from prompt_toolkit.mouse_events import MouseEventType
from prompt_toolkit.utils import get_cwidth

from rich.text import Text

from .api import ApiError
from .chat import MAX_MESSAGE_CHARS, terminal_text
from .ui import console
from .terminal_keys import modified_enter
from .qwen_layout import HEADER_HEIGHT, header, input_rule


class Conversation:
    def __init__(self, chat, poll):
        self.chat, self.poll = chat, poll
        self.lock = asyncio.Lock()
        self.sending = None
        self.status = 'Waiting for reply' if chat.pending else 'Connected'
        self.refresh_error = None
        self.session = None
        self.wake = asyncio.Event()
        self.closed = False
        self.commands = set()
        self.command_names = set()
        self.copy_page = 0
        self.copy_notice = ''
        self.screen = None

    def print(self, *objects, **kwargs):
        (self.screen or console).print(*objects, **kwargs)

    def install_transcript(self, session):
        from .chat_transcript import Transcript
        self.screen = Transcript(self.invalidate, self.start_copy,
                                 getattr(self.chat, 'transcript', ()))
        self.chat.output = self.screen
        history = Window(self.screen, wrap_lines=False, always_hide_cursor=True,
                         get_vertical_scroll=lambda window: self.screen.top,
                         right_margins=[ScrollbarMargin(display_arrows=True)])
        def composer_height():
            width = max(1, session.output.get_size().columns - 6)
            rows = sum(max(1, (get_cwidth(line) + width - 1) // width)
                       for line in session.default_buffer.document.lines)
            return Dimension.exact(min(6, rows) + 1
                                   + sum(fragment[1].count('\n') for fragment in self.toolbar()))
        composer = HSplit([session.layout.container], height=composer_height)
        def banner():
            name = terminal_text(getattr(self.chat, 'name', 'Dot chat'))
            paused = (getattr(self.chat, 'profile', {}) or {}).get('is_paused')
            lines = header(session.output.get_size().columns, name, self.status, paused)
            return [('fg:#67e8f9' if i == 0 else 'fg:#a7f3d0' if i == 1
                     else 'fg:#94a3b8', line + ('\n' if i < HEADER_HEIGHT - 1 else ''))
                    for i, line in enumerate(lines)]
        def top_rule():
            name = terminal_text(getattr(self.chat, 'name', 'Dot chat'))
            return [('fg:#67e8f9', input_rule(session.output.get_size().columns,
                                            name[:32]))]
        def bottom_rule():
            return [('fg:#475569', input_rule(session.output.get_size().columns))]
        session.layout.container = HSplit([
            Window(FormattedTextControl(banner), height=HEADER_HEIGHT),
            history,
            Window(FormattedTextControl(top_rule), height=1),
            composer,
            Window(FormattedTextControl(bottom_rule), height=1),
        ])
        session.app.full_screen = True
        session.app.renderer.full_screen = True
        bindings = KeyBindings()

        @bindings.add('<bracketed-paste>', eager=True)
        def paste(event):
            text = event.data.replace('\r\n', '\n').replace('\r', '\n')
            event.current_buffer.insert_text(text)
            event.current_buffer.cursor_position = len(event.current_buffer.text)
            self.screen.latest()

        @bindings.add('c-s', eager=True)
        @bindings.add('enter', eager=True)
        def send(event):
            event.current_buffer.validate_and_handle()

        @bindings.add('c-j', eager=True)
        @bindings.add('escape', 'enter', eager=True)
        def newline(event):
            event.current_buffer.insert_text('\n')
            self.screen.latest()

        @bindings.add('pageup', eager=True)
        def page_up(event):
            self.screen.scroll(-max(1, self.screen.height - 1))

        @bindings.add('pagedown', eager=True)
        def page_down(event):
            self.screen.scroll(max(1, self.screen.height - 1))

        @bindings.add('c-end', eager=True)
        def latest(event):
            self.screen.latest()

        @bindings.add('<scroll-up>', eager=True)
        def wheel_up(event):
            self.screen.scroll(-3)

        @bindings.add('<scroll-down>', eager=True)
        def wheel_down(event):
            self.screen.scroll(3)

        # Mouse packets include a position, so route wheel events over the
        # composer and copy footer as well as the transcript itself.
        def route_wheel(app):
            wrappers = {}
            for row in app.renderer.mouse_handlers.mouse_handlers.values():
                for column, handler in list(row.items()):
                    if handler not in wrappers:
                        def routed(event, original=handler):
                            if event.event_type == MouseEventType.SCROLL_UP:
                                self.screen.scroll(-3)
                            elif event.event_type == MouseEventType.SCROLL_DOWN:
                                self.screen.scroll(3)
                            else:
                                return original(event)
                        wrappers[handler] = routed
                    row[column] = wrappers[handler]
        session.app.after_render += route_wheel
        return bindings

    def invalidate(self):
        if self.session:
            self.session.app.invalidate()

    async def refresh(self):
        async with self.lock:
            if self.closed:
                return
            pending = bool(self.chat.pending)
            try:
                await asyncio.to_thread(self.chat.refresh)
            except (ApiError, OSError) as error:
                # Report a connection problem once, rather than every poll.
                message = terminal_text(str(error))
                if message != self.refresh_error:
                    self.print(Text('Receive: ' + message, style='yellow'))
                self.refresh_error = message
                self.status = 'Reconnecting · draft stays here'
            else:
                self.refresh_error = None
                if self.sending and not self.sending.done():
                    self.status = 'Sending · keep composing'
                else:
                    self.status = 'Waiting for reply · keep composing' if self.chat.pending else 'Connected'
                if pending and not self.chat.pending:
                    self.status = 'Reply received'
            self.invalidate()

    async def receive(self):
        while not self.closed:
            await self.refresh()
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=self.poll)
            except asyncio.TimeoutError:
                pass
            self.wake.clear()

    async def deliver(self, text):
        self.status = 'Sending · keep composing'
        self.invalidate()
        try:
            async with self.lock:
                await asyncio.to_thread(self.chat.send, text)
            self.status = 'Sent · waiting for reply'
        except (ApiError, OSError) as error:
            self.print(Text(terminal_text(str(error)), style='yellow'))
            self.status = 'Delivery uncertain · /wait to check' if self.chat.pending else 'Not sent'
            # Restore a rejected draft without replacing anything already being typed.
            if not self.chat.pending and self.session and not self.session.default_buffer.text:
                self.session.default_buffer.text = text
        finally:
            self.invalidate()

    def submit(self, text):
        if (self.sending and not self.sending.done()) or self.chat.pending:
            self.print(Text('Previous message still pending. Your draft is kept; /wait checks delivery, /abandon stops tracking.', style='yellow'))
            return False
        if self.screen:
            self.screen.latest()
        message = Text()
        message.append('You: ', style='bold #67e8f9')
        message.append(terminal_text(text))
        if self.screen:
            from .chat_transcript import outgoing_block
            self.print(outgoing_block(terminal_text(text)))
        else:
            self.print(message)
        self.sending = asyncio.create_task(self.deliver(text))
        return True

    async def abandon(self):
        async with self.lock:
            previous = self.chat.pending
            self.chat.pending = None
            try:
                self.chat.save()
            except OSError:
                self.chat.pending = previous
                raise
        self.status = 'Tracking stopped'
        self.invalidate()
        self.print(Text('Stopped tracking. This does not cancel or undo delivery. Repeating the message may duplicate work.', style='yellow'))

    async def show_status(self):
        async with self.lock:
            await asyncio.to_thread(self.chat.show_status)

    def command(self, operation, name=None):
        # Keep the editor active while commands wait for serialized network I/O.
        # Repeated /status must not build an unbounded queue of requests.
        name = name or operation.__name__
        if name in self.command_names:
            return
        self.command_names.add(name)

        async def perform():
            try:
                await operation()
            except (ApiError, OSError) as error:
                self.print(Text(terminal_text(str(error)), style='yellow'))
            finally:
                self.command_names.discard(name)
                self.invalidate()

        task = asyncio.create_task(perform())
        self.commands.add(task)
        task.add_done_callback(self.commands.discard)

    async def copy_response(self, number=None):
        responses = getattr(self.chat, 'responses', {}).copy()
        if not responses:
            raise ApiError('No responses to copy yet.')
        number = max(responses) if number is None else number
        if number not in responses:
            raise ApiError(f'No response #{number}. Use a number shown beside a response.')
        from .main import Launcher
        try:
            command = Launcher().clipboard_command(responses[number])
        except ValueError as error:
            raise ApiError(str(error)) from None
        try:
            result = await asyncio.to_thread(
                subprocess.run, command['argv'], input=command['input'],
                encoding='utf-8', capture_output=True, timeout=10)
        except subprocess.TimeoutExpired:
            raise ApiError('Clipboard copy timed out. Try again.') from None
        if result.returncode:
            raise ApiError('Could not copy the response to the system clipboard.')
        self.copy_notice = f'Copied response #{number}'
        self.invalidate()

    def start_copy(self, number=None):
        if 'copy' in self.command_names:
            return
        self.copy_notice = ''
        self.invalidate()
        self.command(lambda: self.copy_response(number), name='copy')

    def toolbar(self):
        reading = 'History · ' if self.screen and not self.screen.follow else ''
        fragments = [('fg:#94a3b8', reading + 'PgUp/PgDn history · Ctrl-End latest · /quit')]
        draft = self.session.default_buffer.text if self.session else ''
        fragments.append(('', '\n'))
        def send_click(event):
            if event.event_type != MouseEventType.MOUSE_UP:
                return NotImplemented
            if self.session:
                self.session.default_buffer.validate_and_handle()
        fragments.append(('bold fg:#67e8f9', '[Send]', send_click))
        fragments.append(('fg:#94a3b8',
                          f' {len(draft):,}/{MAX_MESSAGE_CHARS:,} · Enter send · Shift+Enter newline · Ctrl-S send'))
        responses = getattr(self.chat, 'responses', {}).copy()
        if not responses:
            return fragments
        # Keep the controls small enough for narrow terminals, and retain access
        # to every response rather than truncating the set to recent replies.
        width = self.session.output.get_size().columns if self.session else 80
        page_size = max(1, min(3, (width - 22) // 12))
        numbers = sorted(responses)
        pages = (len(numbers) + page_size - 1) // page_size
        self.copy_page = min(self.copy_page, pages - 1)
        end = len(numbers) - self.copy_page * page_size
        visible = numbers[max(0, end - page_size):end]

        def button(label, action):
            def click(event):
                if event.event_type != MouseEventType.MOUSE_UP:
                    return NotImplemented
                action()
                self.invalidate()
            return ('bold fg:#67e8f9', label, click)

        def page(delta):
            self.copy_page = max(0, min(pages - 1, self.copy_page + delta))

        fragments.append(('', '\n'))
        for number in visible:
            fragments.append(button(f'[Copy #{number}] ', lambda n=number: self.start_copy(n)))
        if self.copy_page < pages - 1:
            fragments.append(button('[Older] ', lambda: page(1)))
        if self.copy_page:
            fragments.append(button('[Newer]', lambda: page(-1)))
        if self.copy_notice:
            fragments.append(('', '\n' + self.copy_notice))
        return fragments

    async def run(self, session):
        self.session = session
        session.app.erase_when_done = True
        restore_keys = modified_enter(session.input)
        bindings = self.install_transcript(session)
        accepted = asyncio.Queue()
        original_accept = session.default_buffer.accept_handler

        def accept(buffer):
            accepted.put_nowait(buffer.text)
            return False

        session.default_buffer.accept_handler = accept
        async def edit():
            try:
                await session.prompt_async(
                    [('fg:#67e8f9 bold', '> ')], bottom_toolbar=self.toolbar,
                    mouse_support=True, key_bindings=bindings, multiline=True, refresh_interval=.25)
            except EOFError:
                return 0
            except KeyboardInterrupt:
                # Return the interrupt to the owner task so asyncio cannot
                # cancel worker ownership before the journal/POST has finished.
                return 130
            return 0
        prompt = asyncio.create_task(edit())
        receiver = asyncio.create_task(self.receive())
        next_text = None
        try:
            while True:
                next_text = asyncio.create_task(accepted.get())
                done, _ = await asyncio.wait((prompt, next_text), return_when=asyncio.FIRST_COMPLETED)
                if prompt in done:
                    if await prompt == 130:
                        raise KeyboardInterrupt
                    return 0
                text = next_text.result()
                # A pasted document is message data, even when its first line
                # is a path or slash-prefixed code. Commands occupy one line.
                stripped = text.strip()
                command = stripped if '\n' not in stripped and '\r' not in stripped else ''
                if command in ('/quit', '/exit'):
                    return 0
                if command == '/status':
                    self.command(self.show_status)
                elif command in ('/refresh', '/wait'):
                    self.status = 'Checking for replies · keep composing'
                    self.invalidate()
                    self.wake.set()
                elif command == '/abandon':
                    self.command(self.abandon)
                elif command.split(maxsplit=1)[0:1] == ['/copy']:
                    parts = command.split()
                    if len(parts) == 1:
                        self.start_copy()
                    elif len(parts) == 2 and parts[1].isascii() and parts[1].isdigit() and len(parts[1]) <= 9:
                        self.start_copy(int(parts[1]))
                    else:
                        self.print(Text('Usage: /copy [response number] · /copy copies the latest response', style='yellow'))
                elif command.startswith('/'):
                    self.print(Text('Commands: /refresh /wait /status /abandon /copy [N] /quit', style='cyan'))
                elif text.strip() and not self.submit(text):
                    if not session.default_buffer.text:
                        session.default_buffer.text = text
                        session.default_buffer.cursor_position = len(text)
        finally:
            restore_keys()
            self.closed = True
            self.wake.set()
            if next_text and not next_text.done():
                next_text.cancel()
            if session.app.is_running and not prompt.done() and not session.app.is_done:
                session.app.exit()
            # Finish worker threads before releasing the room. The application
            # stays alive across submissions, so sending never clears the screen.
            operations = [prompt, receiver, *self.commands]
            if self.sending:
                operations.append(self.sending)
            if next_text:
                operations.append(next_text)
            results = await asyncio.gather(*operations, return_exceptions=True)
            session.default_buffer.accept_handler = original_accept
            for result in results:
                if isinstance(result, BaseException) and not isinstance(result, (EOFError, asyncio.CancelledError)):
                    raise result


def interactive(chat, poll):
    from prompt_toolkit import PromptSession
    from prompt_toolkit.patch_stdout import patch_stdout
    # Rich emits ANSI styles. The proxy's default write() replaces ESC with '?',
    # exposing sequences such as '?[1m' in the transcript. Message content is
    # sanitized separately by terminal_text; preserve Rich's generated controls.
    with patch_stdout(raw=True):
        return asyncio.run(Conversation(chat, poll).run(PromptSession()))
