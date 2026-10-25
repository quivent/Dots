# Dots

Read the interface guides with `dots guide`, `dots guide terminal`, `dots guide desktop`, `dots guide mobile`, or `dots guide sources`. `dots terminal guide` and `dots terminal --help` show the terminal guide with Markdown formatting; add `--plain` to print raw Markdown.

On macOS or Linux, from this checkout run `make -C cli` to build and install the CLI, then `dots setup` to see the setup steps. You can also run `make` inside `cli/`. Run `dots setup run` to execute prerequisites through account discovery. Without make, use `python3 -m pip install .` (Windows: `py -m pip install .`). This installs the `dots` console command and its dependencies. Pipx is an optional isolated alternative. See [INSTALL.md](INSTALL.md) for macOS prerequisites, wheel installation, upgrades, and removal. Run `dots --help` for all commands.

Start with `dots setup`. Use `dots installation` to list the individual commands without running them. Run `dots` for the grouped command menu. `dots setup` and `dots installation` list all ten operations through profile inspection, including bundled creation work and conditional actions. `dots setup run` runs prerequisites only: update → preflight → auth → list --source chatgpt.

Optional local setup desk: run `dots web`. It opens `http://127.0.0.1:8768/setup.html` with launcher actions, live local checks, and trial-note saving. You can also open [setup.html](setup.html) directly for instructions and copy buttons.

`dots setup onboard` requests the Dot entry page directly. Complete the introduction there, name the Dot, and use [FIRST-MESSAGE.md](FIRST-MESSAGE.md) for the first trial. [Official setup](https://learn.chatgpt.com/docs/dots/getting-started)

`dots auth` signs in when needed and verifies access. `dots preflight` checks local readiness and current Dot account access without starting sign-in. `dots setup` shows the steps; `dots setup onboard` opens Dot onboarding. Already signed in through ChatGPT/Codex? The CLI reuses that login automatically.

Terminal commands default to locally saved identities for actual ChatGPT Dots. Run `dots import --source chatgpt` to save your existing Dots, `dots list` to see them, and `dots use NAME` to select the default. `dots create NAME` creates an actual account Dot and saves its identity here; it does not create a Codex worker. Account creation restrictions still apply. The account API and local auth handoff are experimental. See [LAUNCHER.md](LAUNCHER.md) for every command and exact limits.

Use `--source chatgpt` for direct account discovery and controls, `--source hosted` for the separate hosted Codex catalog, and `--source shortcuts` for old URL shortcuts. Hosted entries are labeled as using Codex allowance and this terminal client does not send chat to them. `dots rename NAME NEW_NAME` changes a local alias; add `--source chatgpt` to change the provider's name.

Chat directly in your terminal with `dots chat Pocket` (replace Pocket with your Dot's name). Use `dots chat Pocket --message "Hello"` for one message and a reply wait. `/refresh` reads recent messages, `/wait` continues waiting, and `/quit` exits. Paused Dots stay paused; use `dots resume Pocket` explicitly when you want it running. This talks to the same existing cloud Dot used by ChatGPT and the phone relay; `dots run` remains the clipboard/app launcher. Omit the name to use the selected saved Dot.

Dot conversations do not count toward ChatGPT usage limits. Tasks a Dot starts or manages in Work or Codex do count toward those products' limits. The terminal adds no Codex inference layer; it cannot impose a provider-wide block on delegation. [Official Dots usage](https://learn.chatgpt.com/docs/dots)

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

In the ChatGPT desktop app, open the dot’s profile → **Computers** → **Your computer** → **Allow access** and confirm. Keep this computer online with ChatGPT open while it works locally. Its cloud computer is separate; existing Codex access or Work Sync does not grant the dot access automatically. [Computer connection](https://learn.chatgpt.com/docs/dots/computers-and-apps)

Then send the local-work continuation in [FIRST-MESSAGE.md](FIRST-MESSAGE.md). That request identifies the actual folders and keeps the first trial small.

## Project locations

Installed releases use `~/Dots` as the workspace. Set `DOTS_PROJECT` to choose another folder. `dots setup onboard`, `dots web`, and prompt-launch commands initialize missing starter documents without replacing existing files. `dots preflight` reports workspace readiness and checks the current connection without changing files. `dots doctor` adds a full troubleshooting report.

Trial results belong in local `FIRST-RESULT.md`. The guide saves private notes to `dots-trials.md` in the runtime directory, separately from the tracked trial template. Set `DOTS_DATA_HOME` to choose the runtime directory. No separate tracker installation is required.

## Evidence boundary

Official documentation checked **2026-10-17**. No Dot conversation, call, shortcut or local-computer connection has been tested on this account. Record actual results in local `FIRST-RESULT.md` or the guide’s private notes file; documentation is not evidence of a successful trial. No recurring work was requested or configured.
