"""Terminal chrome adapted from Qwen Code's Header and BaseTextInput.

Copyright 2025 Google LLC and Qwen contributors. Apache-2.0.
Source: https://github.com/QwenLM/qwen-code/tree/7670e07/packages/cli/src/ui/components
The Ink layout is rendered here with prompt_toolkit so Dots keeps its Python backend.
"""

from prompt_toolkit.utils import get_cwidth


LOGO = ('  ●     ●  ', '     ●     ', '  ●     ●  ', '     ●     ', '  ●     ●  ', '           ')
HEADER_HEIGHT = 6


def fit(text, width):
    """Fit user-facing content inside a fixed terminal column width."""
    width = max(0, width)
    result = ''
    for char in text:
        if get_cwidth(result + char) > width:
            return result[:-1] + '…' if result and width > 1 else result
        result += char
    return result + ' ' * max(0, width - get_cwidth(result))


def header(width, name, status, paused):
    """Qwen-style logo and info panel, with a compact narrow-terminal mode."""
    width = max(8, width)
    show_logo = width >= 72
    panel_width = min(58, width - 17 if show_logo else width - 2)
    inner = panel_width - 4
    state = 'Paused' if paused else 'Active'
    contents = (
        '>_ Dots',
        name,
        f'ChatGPT Dot  ·  {state}',
        status,
    )
    panel = ['╭' + '─' * (panel_width - 2) + '╮']
    panel.extend('│ ' + fit(line, inner) + ' │' for line in contents)
    panel.append('╰' + '─' * (panel_width - 2) + '╯')
    if show_logo:
        return ['  ' + logo + '  ' + line for logo, line in zip(LOGO, panel)]
    return [' ' + line for line in panel]


def input_rule(width, label=''):
    """Port Qwen Code's full-width top rule and right-aligned label."""
    width = max(1, width)
    decoration = ' ' + label + ' ──' if label else ''
    if get_cwidth(decoration) >= width:
        decoration = ''
    return '─' * max(0, width - get_cwidth(decoration)) + decoration
