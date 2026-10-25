"""Transcript rendering, wrapping and navigation without network or clipboard I/O."""
import unittest
import os
from unittest.mock import Mock, patch

from prompt_toolkit.data_structures import Point
from prompt_toolkit.mouse_events import MouseButton, MouseEvent, MouseEventType
from rich.text import Text

from cli.chat_transcript import Transcript, response_block


class TranscriptTests(unittest.TestCase):
    def setUp(self):
        self.copy = Mock()
        self.screen = Transcript(Mock(), self.copy)

    def plain(self):
        return '\n'.join(''.join(fragment[1] for fragment in line) for line in self.screen.lines)

    def test_markdown_and_code_are_rendered_instead_of_printing_source(self):
        text = '# A heading\n\n**Bold words** and `inline()`\n\n- One\n- Two\n\n```python\ndef greet(name):\n    return "Hello " + name\n```\n\n| Key | Value |\n| --- | --- |\n| a | b |'
        self.screen.response(response_block('Dot', text, 1), 1)
        with patch.dict(os.environ):
            os.environ.pop('NO_COLOR', None)
            self.screen.create_content(80, 20)
        plain = self.plain()
        for expected in ('A heading', 'Bold words', 'inline()', 'One', 'Two', 'def greet(name):', 'return', 'Key', 'Value', '[Copy #1]'):
            self.assertIn(expected, plain)
        for marker in ('# A heading', '**Bold words**', '```python', '| --- |'):
            self.assertNotIn(marker, plain)
        code_styles = {fragment[0] for line in self.screen.lines
                       if 'greet' in ''.join(fragment[1] for fragment in line) for fragment in line}
        self.assertGreater(len(code_styles), 1, 'Python tokens should have different styles')

    def test_new_messages_follow_at_bottom_but_do_not_pull_a_reader_down(self):
        self.screen.print(Text('\n'.join(f'Line {i}' for i in range(100))))
        self.screen.create_content(40, 10)
        self.assertGreater(self.screen.top, 0)
        self.screen.scroll(-9)
        old_top = self.screen.top
        self.screen.print(Text('New incoming reply'))
        self.screen.create_content(40, 10)
        self.assertEqual(self.screen.top, old_top)
        self.assertFalse(self.screen.follow)
        self.screen.latest()
        self.screen.create_content(40, 10)
        self.assertEqual(self.screen.top, len(self.screen.lines) - 10)
        self.assertTrue(self.screen.follow)

    def test_long_lines_rewrap_on_resize_and_keep_the_copy_target(self):
        self.screen.response(response_block('Dot', 'word ' * 100, 7), 7)
        self.screen.create_content(70, 8)
        wide_count = len(self.screen.lines)
        self.screen.scroll(-1000)
        self.screen.create_content(25, 8)
        self.assertGreater(len(self.screen.lines), wide_count)
        self.assertEqual(self.screen.top, 0)
        target = next(i for i, line in enumerate(self.screen.lines)
                      if '[Copy #7]' in ''.join(fragment[1] for fragment in line))
        self.assertEqual(self.screen.copy_lines[target], 7)
        self.screen.mouse_handler(MouseEvent(Point(1, target), MouseEventType.MOUSE_UP, MouseButton.LEFT, ()))
        self.copy.assert_called_once_with(7)

    def test_mouse_wheel_clamps_to_history_bounds(self):
        self.screen.print(Text('\n'.join(str(i) for i in range(40))))
        self.screen.create_content(40, 10)
        before = self.screen.top
        self.screen.mouse_handler(MouseEvent(Point(0, 0), MouseEventType.SCROLL_UP, MouseButton.NONE, ()))
        self.assertEqual(self.screen.top, before - 3)
        self.screen.scroll(-1000)
        self.assertEqual(self.screen.top, 0)
        self.screen.scroll(1000)
        self.assertEqual(self.screen.top, len(self.screen.lines) - 10)
        self.assertTrue(self.screen.follow)

    def test_updated_response_replaces_its_rendering_without_changing_copy_number(self):
        self.screen.response(response_block('Dot', 'Old version', 2), 2)
        self.screen.response(response_block('Dot', '**New version**', 2), 2)
        self.screen.create_content(60, 10)
        self.assertNotIn('Old version', self.plain())
        self.assertIn('New version', self.plain())
        self.assertEqual(list(self.screen.copy_lines.values()), [2])
