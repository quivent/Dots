# Install the Dots CLI

Requires Python 3.10+ with pip. No compiler or manual venv setup is needed.

Run the appropriate command from the downloaded source folder:

| macOS (Terminal) | Windows (PowerShell / Command Prompt) | Linux (Terminal) |
| --- | --- | --- |
| `make` | `py -m pip install .` | `make` |

Then, on any platform:

```sh
dots setup
```

On macOS and Linux, `make` builds and installs the CLI. `python3 -m pip install .` is the equivalent command without make.

If Windows has `python` rather than the `py` launcher, use `python -m pip install .`.

Or, if you downloaded the wheel:

```sh
python3 -m pip install ./dots_cli-0.2.12-py3-none-any.whl
```

On Windows, use `py -m pip install .\dots_cli-0.2.12-py3-none-any.whl` for the wheel.

After installation, run `dots` for the command menu or `dots setup` for the individual setup plan. Use `dots setup run` to execute prerequisites through account discovery. Use `dots --help` for other commands. Pip installs the package, formatting and OS credential-store dependencies, and the `dots` console command.
A virtual environment is not an application requirement, and there is no separate venv setup step.

## Optional isolated install

If you already use pipx, `pipx install .` is an alternative. Pipx manages a private environment automatically so CLI dependencies do not share your other Python packages.

If pip reports **externally-managed-environment**, that Python distribution blocks direct installation. Use `pipx install .` with pipx installed, or another Python installation that permits pip installs. See the [externally managed environment specification](https://packaging.python.org/en/latest/specifications/externally-managed-environments/). The CLI does not require isolation; your Python distribution may require it.

On macOS, pipx can be installed with `brew install pipx`. If pipx reports its commands are not on PATH, follow its `pipx ensurepath` instruction and open a new Terminal.

The package has not been published to PyPI. Do not use `pip install dots-cli` for this project yet. Use the provided source or wheel.

## Sign in and create

If you are already signed into ChatGPT/Codex on this computer, the CLI reuses that login automatically. Otherwise run `dots auth`; it starts first-party ChatGPT sign-in when the local ChatGPT/Codex executable is installed.

| Command | Action |
|---|---|
| `dots update` | Update this CLI from the public GitHub repository |
| `dots auth` | Sign in when needed, then verify Dot account access |
| `dots preflight` | Check local readiness and current Dot account access; no login flow |
| `dots installation` | List the individual setup commands without running them |
| `dots setup` | Show the individual setup commands without running them |
| `dots setup run` | Run prerequisites: update → preflight → auth → list |
| `dots setup onboard` | Open guided Dot onboarding in ChatGPT |
| `dots create NAME` | Create a Dot through the internal account API |
| `dots doctor` | Full read-only troubleshooting report |
| `dots serve` | Run the local guide independently |

`auth`, `preflight`, and `setup` do not create Dots. Existing-login reuse and catalog read access have been verified live; cloud creation is still unverified. The API and app-server token handoff are experimental. See [LAUNCHER.md](LAUNCHER.md) for the authentication sources, manual-token alternatives, executable discovery, and full reference.

Account commands include `list`, `use`, `show`, `activity`, `tasks`, `pause`, `resume`, and `room`. All accept `--json`. Local shortcuts remain independent: `dots list --local`, `dots create NAME --local`, `dots use NAME --local`, `dots activity --local`. `dots run --preset local` copies a prompt and opens ChatGPT; paste and send yourself.

For recovery when catalog discovery is broken, use `dots show DOT_ID --by-id`. The same option works with `use`, `activity`, `tasks`, `room`, `pause`, and `resume`. `dots create NAME --first` or `--additional` skips the creation catalog lookup.

An installed release uses `~/Dots` as its workspace. `dots setup onboard`, `dots serve`, and prompt-launch commands initialize missing workspace documents without overwriting existing ones. `dots preflight` checks readiness and current account access without creating files. `dots doctor` provides broader troubleshooting diagnostics. The starter trial requires no separate tracker. Set `DOTS_PROJECT` to use another folder. `DOTS_DATA_HOME` overrides the local settings/history directory. Existing tracker-runtime settings are retained when that runtime is present.

## Upgrade or remove

Update the installed CLI from the public `quivent/Dots` main branch:

```sh
dots update
```

The command checks for a newer version before installing anything and preserves satisfied dependencies. This works with pip and pipx installations. It reuses uv or pip for one install command; only installations with neither bootstrap pip once. It creates no separate installer environment. Raw installer output is never printed, including on failure; detailed errors go to a private log whose path is shown. Setup starts with this update, then preflight, authentication, and onboarding.

From an updated source checkout, `make` also rebuilds and installs the CLI.

Or install a newer shared wheel with `python3 -m pip install --upgrade /path/to/new.whl`.

```sh
python3 -m pip uninstall dots-cli
```

If installed through pipx instead, update with `pipx install --force .` and remove with `pipx uninstall dots-cli`.

Uninstall removes the application, not workspace files, private trial notes, or saved launcher state.

## Help and output

`dots --help` groups all commands. `dots COMMAND --help` lists every option for that command.
Use `dots --no-color COMMAND` to disable colors. `dots list --json`, `dots activity --json`,
and `dots doctor --json` provide machine-readable output. Redirected output is not colored by default.

## Platform behavior

- macOS: opens the desktop app when available, uses the default browser as fallback, and copies with pbcopy.
- Windows: opens a discoverable ChatGPT.exe, otherwise uses the default browser. Clipboard actions use PowerShell Set-Clipboard with UTF-8 input. Folder actions use Explorer. Settings writes use Windows file locking.
- Linux: uses the default browser and xdg-open. Clipboard actions require wl-copy or xclip; dots prompt prints the text without either.

Connecting a local computer to a Dot still depends on the ChatGPT desktop app and account support. CLI browser support does not establish local-computer support on a platform.

Windows launch plans and Unicode handling are tested with mocked system actions locally. A Windows/macOS/Linux CI matrix is included; native Windows execution has not yet been verified in this workspace.
