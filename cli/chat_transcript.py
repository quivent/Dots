"""@purpose Render and navigate the REPL transcript without moving its composer.
@owns Markdown/code rendering, wrapped scroll position and inline copy targets.
"""
import io
import threading

from prompt_toolkit.data_structures import Point
from prompt_toolkit.formatted_text import ANSI, to_formatted_text
from prompt_toolkit.formatted_text.utils import split_lines
from prompt_toolkit.layout import UIContent, UIControl
from prompt_toolkit.mouse_events import MouseEventType
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.text import Text


def response_block(name, text, number):
    return Group(Text(name + ':', style='bold #a7f3d0'),
                 Markdown(text, code_theme='monokai', hyperlinks=False),
                 Text(f'[Copy #{number}]', style='bold #67e8f9'))


def outgoing_block(text):
    return Group(Text('You: ', style='bold #67e8f9'),
                 Markdown(text, code_theme='monokai', hyperlinks=False))


class Transcript(UIControl):
    def __init__(self, invalidate, copy, initial=()):
        self.invalidate, self.copy = invalidate, copy
        self.blocks = list(initial)
        self.response_positions = {number: i for i, (_, number) in enumerate(self.blocks)
                                   if number is not None}
        self.lock = threading.Lock()
        self.version = 0
        self.cache_key = None
        self.lines = [[]]
        self.copy_lines = {}
        self.top = 0
        self.height = 1
        self.follow = True

    def print(self, *objects, **kwargs):
        with self.lock:
            for obj in objects or ('',):
                self.blocks.append((obj, None))
            self.version += 1
        self.invalidate()

    def response(self, block, number):
        with self.lock:
            if number in self.response_positions:
                self.blocks[self.response_positions[number]] = (block, number)
            else:
                self.response_positions[number] = len(self.blocks)
                self.blocks.append((block, number))
            self.version += 1
        self.invalidate()

    def create_content(self, width, height):
        width = max(1, width)
        with self.lock:
            key = (self.version, width)
            blocks = self.blocks.copy() if key != self.cache_key else None
        if blocks is not None:
            lines, targets = [], {}
            for block, number in blocks:
                stream = io.StringIO()
                renderer = Console(file=stream, width=width, force_terminal=True,
                                   color_system='truecolor', highlight=False)
                renderer.print(block, markup=False)
                rendered = list(split_lines(to_formatted_text(ANSI(stream.getvalue()))))
                # ANSI parsing can represent the final newline as [('', '')],
                # which is truthy. Copy targets must point at the visible label.
                while rendered and not ''.join(fragment[1] for fragment in rendered[-1]).strip():
                    rendered.pop()
                lines.extend(rendered)
                if number is not None and rendered:
                    targets[len(lines) - 1] = number
                lines.append([])
            self.lines, self.copy_lines = lines or [[]], targets
            self.cache_key = key
        self.height = max(1, height)
        maximum = max(0, len(self.lines) - self.height)
        self.top = maximum if self.follow else min(self.top, maximum)
        return UIContent(get_line=lambda i: self.lines[i], line_count=len(self.lines),
                         cursor_position=Point(0, self.top), show_cursor=False)

    def scroll(self, rows):
        maximum = max(0, len(self.lines) - self.height)
        self.top = max(0, min(maximum, self.top + rows))
        self.follow = self.top == maximum
        self.invalidate()

    def latest(self):
        self.follow = True
        self.invalidate()

    def mouse_handler(self, event):
        if event.event_type == MouseEventType.SCROLL_UP:
            self.scroll(-3)
        elif event.event_type == MouseEventType.SCROLL_DOWN:
            self.scroll(3)
        elif event.event_type == MouseEventType.MOUSE_UP and event.position.y in self.copy_lines:
            self.copy(self.copy_lines[event.position.y])
        else:
            return NotImplemented
