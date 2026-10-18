# Dots CLI

Run `make` to build and install the CLI, then `dots setup` to see the numbered setup commands. Use `dots setup run` to execute them. Windows: `py -m pip install .`. Linux: `make` also works. Requires Python 3.10+. See [INSTALL.md](INSTALL.md).

## Set up

| Command | Action |
|---|---|
| `dots update` | Update this CLI from the public GitHub repository |
| `dots auth` | Reuse an existing ChatGPT login, or start first-party browser sign-in when missing; then verify Dot account access |
| `dots preflight` | Check local readiness and current Dot account access without signing in |
| `dots setup steps` | List the individual setup commands without running them |
| `dots setup` | Show the numbered setup commands; no actions run |
| `dots setup run` | Run update → preflight → auth → setup onboard in order |
| `dots setup onboard` | Open Dot onboarding in ChatGPT |
| `dots doctor` | Full troubleshooting: local state, account access, tools, assets, and private-note permissions |
| `dots serve` | Open the local guide independently of cloud access |

Preflight does not open a login flow or create files. A missing login is reported as `auth_required`, allowing the following `dots auth` step to sign in. Connection errors are reported separately and return a failure status. `dots doctor` additionally inspects configuration/history parsing, app-server availability, clipboard support, guide assets, and private-note permissions. Neither diagnostic command creates a Dot or changes account state.

If you are already signed into ChatGPT/Codex on this computer, Dot commands reuse that login automatically. You do not need to paste a token or run `auth` again. `dots create NAME` uses the same authentication source. `dots preflight`, `dots setup`, and `dots setup onboard` accept `--json`. The interactive runner does not.

When no reusable login exists, run `dots auth`. It starts the first-party `codex login` flow and then checks Dot access. This requires a local app-server executable, found through `codex` on PATH or the bundled macOS ChatGPT app. Set `DOTS_CODEX` to its executable if needed. If neither is installed, install ChatGPT/Codex first. No Dot is created by `auth`, `preflight`, or `setup`.

App launch, local tools, authentication, connection checks, creation, and room repair are independent commands. A failed connection check does not block `dots app`, `dots setup`, `dots doctor`, or `dots serve`.

The main screen uses three colored command groups: Setup, Dots, and Manage. `dots` and `dots --help` show the same indented command tree; `dots COMMAND --help` lists options.

The setup plan starts with `dots update`, followed by `dots preflight`, `dots auth`, and `dots setup onboard`. Updates check the available version first and install only a newer CLI, preserving satisfied dependencies. Installation progress stays concise; errors show a short message and the path to a private log. Raw installer output is never printed. Updates install the latest public `quivent/Dots` main branch into the Python environment running this CLI. The updater reuses uv or pip and runs one install command, without creating a separate installer environment or upgrading pip. Only installations with neither installer bootstrap pip once. Satisfied dependencies are retained; uv targets only the CLI for upgrade. Each runner step starts a fresh CLI process so it uses the updated code.

`dots setup` and `dots setup steps` show the same plan; both accept `--json` and perform no setup actions.

The setup plan and runner share one command list. The runner prints each command before executing it and stops on failure, naming the command to retry. Every step remains directly runnable; no saved completion flags or pipeline state block other commands. The final step requests onboarding navigation and does not claim onboarding is complete.

## Authentication and verification

The local app-server protocol confirms the existing ChatGPT account and hands off a token through its experimental `getAuthStatus` RPC. The token is used in memory; the CLI does not display it, save another copy, or read browser/session credential files. Existing-login reuse and an authenticated `GET /tbo` catalog request were verified on 2026-10-18. Dot creation, initialization, and activity have not yet been verified live. A new browser login is covered by mocked tests; the active login was retained during testing.

Cloud commands use internal ChatGPT routes observed in application version 26.1013.40934, rather than a published Dot API. The local auth handoff is also experimental; app updates can change it. Source details: [research/dot-protocol.json](research/dot-protocol.json). [Official login caching](https://learn.chatgpt.com/docs/auth#login-caching)

`dots setup onboard` uses the observed `codex://dots` desktop route and `/dots` browser fallback. An accepted launch does not establish that onboarding completed. [Official onboarding](https://learn.chatgpt.com/docs/dots/getting-started)

### Advanced credential alternatives

Normally, use `dots auth`. Explicit credentials take precedence: `DOTS_ACCESS_TOKEN` plus `DOTS_ACCOUNT_ID` in the process environment, then a credential saved by this CLI, then the existing app-server login. An OpenAI platform API key does not provide personal Dot access.

`dots auth login --account-id ACCOUNT_ID` validates an existing account token from a hidden prompt before saving it in macOS Keychain, Windows Credential Manager, or supported Linux Secret Service/KWallet. `--token-stdin` reads one token line from a secret manager or authorized automation. No plaintext fallback. Avoid putting tokens in command arguments, shell history, or guide notes.

`dots auth status` reports credential source and presence without secrets; `--check` additionally checks account read access. `dots auth logout` removes only this CLI's explicitly saved credential. It does not sign out ChatGPT/Codex or clear environment overrides. Use first-party sign-out controls to end the shared login. Explicit tokens expire. If a saved token is rejected, `dots auth` verifies the shared ChatGPT login (or starts sign-in) before removing the rejected saved override. Invalid saved records are ignored. Environment overrides remain explicit and are never silently removed.

## Cloud commands

| Command | Request / behavior |
|---|---|
| `dots list` | Read all catalog pages from `GET /tbo` |
| `dots create NAME` | Read catalog, then make one `POST /tbo` creation request |
| `dots use DOT` | Select the account's primary Dot with `PUT /tbo/primary` |
| `dots show [DOT]` | Read a Dot profile |
| `dots activity [DOT]` | Read all activity pages |
| `dots activity DOT --open` | Read activity, then open the Dot's web page |
| `dots tasks [DOT]` | Read all task-history pages |
| `dots tasks DOT --task TASK_ID` | Read one task |
| `dots pause [DOT]` | Request a runtime pause |
| `dots resume [DOT]` | Request a runtime resume |
| `dots room [DOT]` | Explicitly create/recover a messaging room |

`DOT` accepts an ID or a unique display name. Omitted targets use the only Dot or the account's primary Dot; ambiguous names fail with instructions to use an ID. Every cloud command supports `--json`. Pause/resume output preserves the server response: an unconfirmed status is not reported as a confirmed change.

Creation requests `create_thread: true`, `should_initialize: true`, and the appropriate first/additional flag. It does not subsequently create a room, select the Dot, launch a window, or submit a user task. Inspect the returned profile with `dots show DOT`. If the messaging room is missing, run `dots room DOT` independently. Onboarding initialization is requested from the server; completion is not inferred from profile creation.

Writes are never automatically retried. A timeout or server failure can mean the write succeeded even though its response was lost. Inspect `dots list`, `dots show`, or `dots activity` before repeating a write. Incomplete creation responses report an unknown outcome rather than inviting duplicate creation.

For recovery when catalog discovery is broken, `dots show DOT_ID --by-id` sends the profile request directly. The same `--by-id` option works with `use`, `activity`, `tasks`, `room`, `pause`, and `resume`. These operations do not depend on `dots list`. To make creation independent of catalog discovery, choose `dots create NAME --first` or `dots create NAME --additional`; this sends only the creation request. Without either flag, creation reads the catalog to choose automatically.

## Local tools

These do not require account credentials. The earlier shortcut-only behavior is retained explicitly with `--local`.

| Command | Actual effect |
|---|---|
| `dots create NAME --local` | Save a pending shortcut and open graphical onboarding |
| `dots create NAME --local --no-open` | Save the pending shortcut only |
| `dots configure URL --name NAME` | Save an actual conversation link |
| `dots configure ''` | Clear the selected conversation link |
| `dots list --local` | List saved shortcuts |
| `dots use NAME --local` | Select the shortcut used by `open` and `run` |
| `dots activity --local` or `dots history` | Read local launch history |
| `dots open` | Open the saved conversation |
| `dots run --preset local` | Copy a task and open ChatGPT; paste and send yourself |
| `dots app` | Launch the desktop app |
| `dots copy --preset first` | Copy a prompt |
| `dots prompt local` | Print a prompt |
| `dots doctor` | Full troubleshooting diagnostics |
| `dots status` | Show local configuration and history |
| `dots folder` | Open the project folder |
| `dots web` | Open ChatGPT in the default browser |
| `dots guide` | Open the official setup instructions |
| `dots serve` | Start the local guide with launcher buttons |

`open`, `app`, `copy`, and `run` accept `--preset first|local|followup` or `--prompt TEXT`, plus `--dry-run`. Launch and clipboard actions never claim task submission. `dots COMMAND --help` lists every argument. Use `dots --no-color COMMAND` for plain output.

## Local guide and storage

`dots serve` binds to `127.0.0.1:8768`. It serves only allowlisted pages/documents; writes require same-origin checks and a per-process token. Account credentials and cloud control routes are not exposed to the guide server. The guide's switches record manual confirmations, not actual permissions.

The source checkout is the workspace; installed releases default to `~/Dots`. `DOTS_PROJECT` changes the workspace. `DOTS_DATA_HOME` changes local settings/history storage. Existing tracker settings remain supported. `setup onboard`, `serve`, and prompt-launch commands create missing starter documents and linked guide files without overwriting existing files; `doctor` and dry runs remain read-only. Starter prompts require no separate tracker installation. History records launch actions, not prompt text. Credentials are stored separately in the OS credential store or supplied through the process environment.

The guide saves entered notes in the private runtime file `dots-trials.md`, created with owner-only permissions on POSIX systems. It never appends them to tracked `TRIALS.md`. That document is a reusable template. Workspace initialization adds missing ignore rules while preserving existing entries. Ignore rules protect new local results and note files; they do not untrack files already committed to an existing repository.

URL launch failures return an error. If the desktop Dot protocol handler fails, onboarding tries the HTTPS route. A successful launch means the request was accepted, not that navigation or onboarding finished. Activity opening uses the same launch/error handling and reports fetched activity separately from navigation failure.
