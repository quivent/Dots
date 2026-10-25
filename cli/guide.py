"""Read-only Markdown guides, rendered with Rich in the terminal."""
from .ui import console

GUIDES = {
    'overview': '''# Dots guide

Use an actual ChatGPT Dot from the interface that suits you. Its agent runs in the cloud; saved identities and the terminal client live on this computer.

| Guide | Open it |
| --- | --- |
| Terminal chat and saved Dots | `dots guide terminal` |
| ChatGPT desktop and browser | `dots guide desktop` |
| Phone and Mac relay | `dots guide mobile` |
| Sources, identities, and usage | `dots guide sources` |

`dots terminal guide` and `dots terminal --help` also open the terminal guide. Add `--plain` to a guide command for raw Markdown you can pipe into another reader. Guides only display text; they do not sign in, import identities, send messages, or start work.

## Start in the terminal

```sh
dots import --source chatgpt
dots list
dots chat Pocket
```

A paused Dot stays paused until you explicitly resume it. Read `dots guide terminal` for controls and delivery recovery.
''',
    'terminal': '''# Dots in the terminal

Chat with the same actual Dot you use in ChatGPT. The terminal defaults to locally saved identities; the Dot continues to run in the cloud.

## Save an existing Dot

```sh
dots import --source chatgpt
dots list
dots use Pocket
dots chat
```

Replace Pocket with your Dot's name. Import saves identity metadata only. `dots use` selects the local default, and `dots chat NAME` targets a specific saved Dot. No local Codex agent is created.

## A paused Dot

Chat can show history while the Dot is paused. When you want it running, explicitly use:

```sh
dots resume Pocket
dots chat Pocket
```

Opening chat never resumes it automatically. `dots pause Pocket` requests a provider runtime pause.

## During a conversation

| Input | Effect |
| --- | --- |
| A normal message | Send once and wait for a new Dot message |
| `/refresh` | Read new messages without sending |
| `/status` | Read runtime, delivery, last check-in, and reported tasks without sending |
| `/copy [N]` | Copy response N to the system clipboard; omit N for the latest response |
| Mouse wheel / Page Up / Page Down | Scroll the transcript while preserving your draft |
| Ctrl-End | Return to the latest messages and follow new replies |
| Ctrl-S / Send button | Send the whole draft or execute a typed slash command |
| Enter / Alt-Enter | Insert a newline; pasting never sends automatically |
| `/wait` | Continue checking for a pending reply |
| `/quit` or Ctrl-D | Exit chat |
| Ctrl-C | Exit and preserve pending delivery state |
| `/abandon` | Stop tracking a pending message; this does not cancel delivery or work |

If delivery is uncertain, use `/wait`; the client never automatically resends a message. Repeating text after abandoning it may duplicate work. Replies are polled, rather than streamed token by token.

## One message and a reply wait

For a status check outside the REPL, use `dots chat Pocket --status`. Status checks only read provider data; they do not send messages or start tasks. Live tool steps, context usage, and credit balances are not exposed by this status view.

```sh
dots chat Pocket --message "Hello" --timeout 120 --poll 2
```

A successful wait returns 0, a reply timeout returns 2, errors return 1, and Ctrl-C returns 130. A timeout does not mean the send failed. Restart chat with the same Dot to check a pending message without resending.

## Create or manage saved Dots

```sh
dots create MyDot
dots show Pocket
dots rename Pocket Desk
dots forget Desk
```

Create requests an actual ChatGPT Dot and saves its identity; provider restrictions still apply. Rename changes your local alias. Forget removes only the saved reference, leaving the provider Dot intact. Use `--source chatgpt` to address the account directly or change its provider name. `dots room NAME` explicitly creates or recovers a missing messaging room.

## Usage and sources

Dot conversations do not count toward ChatGPT usage limits. Tasks the Dot delegates to Work or Codex can use those products' allowance. The terminal adds no Codex inference layer and cannot enforce a provider-wide block on delegation.

Hosted Codex workers are a separate source and their conversations consume Codex allowance. This client does not send terminal chat to them. Use `dots guide sources` for the distinction.

Read the [official Dots usage information](https://learn.chatgpt.com/docs/dots). For individual options, use `dots chat --help`, `dots create --help`, or `dots import --help`. This guide is also available through `dots terminal guide` and `dots terminal --help`.
''',
    'desktop': '''# Dots on desktop

Open your actual Dot in ChatGPT on the desktop or in a desktop browser. It is the same provider Dot available through terminal chat.

## Open ChatGPT

```sh
dots app
```

For guided onboarding, use `dots setup onboard`. This requests navigation; it does not prove that creation or onboarding completed.

## Save a conversation shortcut

Copy the real ChatGPT conversation URL, then run:

```sh
dots configure CONVERSATION_URL --name Pocket
dots use Pocket --source shortcuts
dots open
```

Replace CONVERSATION_URL with the copied HTTPS link. URL shortcuts are separate from saved provider identities. Selecting a shortcut changes `dots open` and the launcher; selecting a default saved Dot changes `dots chat`.

`dots run --preset first` copies a prompt and opens ChatGPT. Paste and send it yourself. For direct terminal sending, use `dots chat Pocket`.

## Connect this computer

In the ChatGPT desktop app, open the Dot's profile, choose Computers, and allow access to this computer. Keep the computer online and ChatGPT open when the Dot needs local files or apps. This grants computer access; it does not move the Dot's agent runtime onto this computer.

For conversation usage and delegated tasks, read `dots guide sources`.
''',
    'mobile': '''# Dots on your phone

Use the same actual ChatGPT Dot on your phone and in the terminal. Saving its identity here does not create another agent or reset its memory.

## ChatGPT mobile app

Open your Dot in the ChatGPT app. Desktop and phone access use the provider's existing identity. The project's terminal can import that identity with `dots import --source chatgpt`.

## This project's phone app and Mac relay

The Dots phone clients can use the deployed Dots server or a paired Mac connection. Pair using the Dots Mac companion's phone-pairing action, then enter the one-use code on the phone. The deployed HTTPS server address is:

```text
https://dots.kosmos.institute
```

A server address alone does not authenticate a device. Use the phone's saved pairing credential or an invitation supplied by the owner. Do not paste your ChatGPT access token into the hub connection.

The Mac companion and relay forward actual Dot messages to ChatGPT. Actual account Dots need that source connection online for this relay route. The terminal talks to the provider directly using the existing ChatGPT sign-in.

## Choose the actual Dot

Pocket is a ChatGPT account Dot. The hosted Belle, Oscillator, and Wavesmith entries are separate Codex workers. Those hosted conversations use Codex allowance. Choose an actual ChatGPT Dot when you want Dot conversation usage behavior.

`dots mobile --help` lists Mac relay options; `dots guide sources` explains the catalogs. This guide starts no services and sends no messages.
''',
    'sources': '''# Dot identities, sources, and usage

The terminal defaults to **local saved identities**. Local describes where the identity and selection are saved; actual ChatGPT Dots execute in the provider's cloud.

| Source | What it contains | Command |
| --- | --- | --- |
| `local` (default) | Saved references to known provider identities | `dots list` |
| `chatgpt` | Actual Dots in your ChatGPT account | `dots list --source chatgpt` |
| `hosted` | Hosted Codex workers and shared rooms | `dots list --source hosted` |
| `shortcuts` | Old browser conversation links | `dots list --source shortcuts` |

## Bring an account Dot into the default list

```sh
dots import --source chatgpt
dots import Pocket --source chatgpt --name Desk
dots use Desk
dots chat
```

Importing the same identity updates its metadata and preserves your alias. Saved names resolve to exact provider IDs. There is no fallback to another source when a name is missing. `dots create NAME` requests an actual ChatGPT Dot and saves/selects it; provider restrictions on additional Dots still apply.

`dots rename OLD NEW` changes a local alias. `dots rename DOT NEW --source chatgpt` changes the provider name. `dots forget NAME` removes only the local reference. Local registry IDs and provider IDs are different; use `--by-id --source chatgpt` when passing a provider ID directly.

## Usage boundary

Dot conversations do not count toward ChatGPT usage limits. Tasks a Dot starts or manages in Work or Codex do count toward those products' limits. The local terminal client adds no model calls, but it cannot prevent the provider Dot from delegating work. See the [official Dots usage information](https://learn.chatgpt.com/docs/dots).

Hosted Codex workers are different: even conversation uses Codex allowance. They can be inspected or imported for identity/control, but this terminal client does not send chat to them. No Codex substitute is created when actual Dot creation is unavailable.

## Storage and credentials

Saved IDs, aliases, selection, and last-observed metadata live in `agents/registry.json` under the runtime directory. `DOTS_DATA_HOME` changes that directory. This registry stores neither credentials nor conversation text. Listing saved identities works offline; live chat requires provider access.

ChatGPT access reuses the existing sign-in. Hosted reads use a separate hub device credential through `DOTS_HUB_TOKEN` or `DOTS_HUB_TOKEN_FILE`, with `DOTS_HUB_URL` selecting the HTTPS origin. ChatGPT credentials are never forwarded to the hosted hub.
''',
}


def render(interface, terminal, plain=False):
    if terminal.no_color:
        from rich.console import Console
        terminal = Console(file=terminal.file, width=terminal.width,
                           force_terminal=False, color_system=None, highlight=False)
    if plain:
        terminal.print(GUIDES[interface], markup=False, highlight=False, soft_wrap=True, end='')
    else:
        from rich.markdown import Markdown
        terminal.print(Markdown(GUIDES[interface], code_theme='monokai'))


def format_terminal_help(terminal):
    from io import StringIO
    from rich.console import Console
    stream = StringIO()
    output = Console(file=stream, width=terminal.width, force_terminal=terminal.is_terminal,
                     no_color=terminal.no_color,
                     color_system=None if terminal.no_color else terminal.color_system, highlight=False)
    render('terminal', output)
    return stream.getvalue()


def run(args, launcher):
    render(getattr(args, 'interface', 'terminal'), console, getattr(args, 'plain', False))
    return 0
