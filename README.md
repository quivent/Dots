# Dots

On macOS or Linux, from this checkout run `make` to build and install the CLI, then `dots setup` to open onboarding. Without make, use `python3 -m pip install .` (Windows: `py -m pip install .`). This installs the `dots` console command and its dependencies. Pipx is an optional isolated alternative. See [INSTALL.md](INSTALL.md) for macOS prerequisites, wheel installation, upgrades, and removal. Run `dots --help` for all commands.

First-time setup: run `dots setup` to open ChatGPT onboarding.

Optional local setup desk: run `dots serve`. It opens `http://127.0.0.1:8768/setup.html` with launcher actions, live local checks, and trial-note saving. You can also open [setup.html](setup.html) directly for instructions and copy buttons.

`dots setup` requests the Dot entry page directly. Complete the introduction there, name the Dot, and use [FIRST-MESSAGE.md](FIRST-MESSAGE.md) for the first trial. [Official setup](https://learn.chatgpt.com/docs/dots/getting-started)

Setup is independently testable: `dots setup check`, `dots setup app`, `dots setup auth`, and `dots setup api` each inspect or run one part. A blocked API connection does not stop local launch or guide commands.

The expanded CLI includes account `list`, `create`, `use`, `show`, `activity`, `tasks`, `pause`, `resume`, and `room` commands. They use experimental internal Dot routes and require an explicit account credential; standalone browser sign-in and live authenticated operation remain unverified. Local shortcut behavior uses `--local`. See [LAUNCHER.md](LAUNCHER.md) for authentication, every command, and exact limits.

## What you are evaluating

A persistent cloud agent that can retain context, continue work between conversations and delegate tasks to Work or Codex. The practical question: can it carry a small responsibility through to a useful result with little supervision? [Dots overview](https://learn.chatgpt.com/docs/dots)

## Ways to interact

| Method | Start interaction | Status in this project |
|---|---|---|
| ChatGPT conversation | Open your dot and send a message | Documented; account trial pending |
| Voice | Open its conversation and press the phone button | Documented; trial pending |
| iPhone shortcut | Shortcuts → ChatGPT → **Open your dot** → select dot → Messaging, Dictation or Call | Rolling out; requires Dot access |
| Slack | Connect through the dot’s profile → **Add**, then DM it or mention it in an added channel | Documented; not connected here |

The same dot is accessible across supported devices. Mobile web is unsupported. Text messaging is described as coming soon, so it is not a current setup route. [Messaging and shortcuts](https://learn.chatgpt.com/docs/dots/channels)

## Let it work with this folder

In the ChatGPT desktop app, open the dot’s profile → **Computers** → **Your computer** → **Allow access** and confirm. Keep this Mac online with ChatGPT open while it works locally. Its cloud computer is separate; existing Codex access or Work Sync does not grant the dot access automatically. [Computer connection](https://learn.chatgpt.com/docs/dots/computers-and-apps)

Then send the local-work continuation in [FIRST-MESSAGE.md](FIRST-MESSAGE.md). That request identifies the actual folders and keeps the first trial small.

## Project locations

| Content | Location |
|---|---|
| Research, prompts and observed results | `~/Dots` |
| Tracker configuration, tasks, checks and runtime | `~/tracker-factory/trackers/dots` |
| Open or serve this tracker | `track ~/Dots` |

Use Tracker Desk’s **Dots** entry to view the work. The registry records its central location; no project-local tracker is needed.

## Evidence boundary

Official documentation checked **2026-10-17**. No Dot conversation, call, shortcut or local-computer connection has been tested on this account. Record actual results in [TRIALS.md](TRIALS.md); documentation is not evidence of a successful trial. No recurring work was requested or configured.
