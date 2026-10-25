"""Recognize modified Enter sequences that prompt_toolkit treats as plain Enter."""
from prompt_toolkit.keys import Keys


SHIFT_ENTER = ('\x1b[13;2u', '\x1b[27;2;13~')
CTRL_ENTER = ('\x1b[13;5u', '\x1b[27;5;13~')


def modified_enter(input_device):
    """Map distinct terminal sequences to Alt+Enter for this input only.

    Kitty/CSI-u and xterm modifyOtherKeys terminals can report the modifier.
    A terminal that reports both keys as CR cannot be distinguished here.
    """
    parser = getattr(input_device, 'vt100_parser', None)
    if parser is None:
        return lambda: None
    original = parser._get_match

    def match(prefix):
        if prefix in SHIFT_ENTER or prefix in CTRL_ENTER:
            return Keys.Escape, Keys.ControlM
        return original(prefix)

    parser._get_match = match
    return lambda: setattr(parser, '_get_match', original)
