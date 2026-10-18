# Dots CLI

Run `make` to build and install the CLI, then `dots setup` to open Dot onboarding. Windows: `py -m pip install .`. Linux: `make` also works. Requires Python 3.10+. See [INSTALL.md](INSTALL.md).

## Sign in, check, or set up

| Command | Action |
|---|---|
| `dots auth` | Reuse an existing ChatGPT login, or start first-party browser sign-in when missing; then verify Dot account access |
| `dots check` | Verify the current login and read-only Dot access; never starts a login flow |
| `dots setup` | Open Dot onboarding in ChatGPT |
| `dots doctor` | Check local app, prompts, saved conversation, and result file |
| `dots serve` | Open the local guide independently of cloud access |

If you are already signed into ChatGPT/Codex on this computer, Dot commands reuse that login automatically. You do not need to paste a token or run `auth` again. `dots create NAME` uses the same authentication source. `dots check` and `dots setup` accept `--json`.

When no reusable login exists, run `dots auth`. It starts the first-party `codex login` flow and then checks Dot access. This requires a local app-server executable, found through `codex` on PATH or the bundled macOS ChatGPT app. Set `DOTS_CODEX` to its executable if needed. If neither is installed, install ChatGPT/Codex first. No Dot is created by `auth`, `check`, or `setup`.

App launch, local tools, authentication, connection checks, creation, and room repair are independent commands. A failed connection check does not block `dots app`, `dots setup`, `dots doctor`, or `dots serve`.

## Authentication and verification

The local app-server protocol confirms the existing ChatGPT account and hands off a token through its experimental `getAuthStatus` RPC. The token is used in memory; the CLI does not display it, save another copy, or read browser/session credential files. Existing-login reuse and an authenticated `GET /tbo` catalog request were verified on 2026-10-18. Dot creation, initialization, and activity have not yet been verified live. A new browser login is covered by mocked tests; the active login was retained during testing.

Cloud commands use internal ChatGPT routes observed in application version 26.1013.40934, rather than a published Dot API. The local auth handoff is also experimental; app updates can change it. Source details: [research/dot-protocol.json](research/dot-protocol.json). [Official login caching](https://learn.chatgpt.com/docs/auth#login-caching)

`dots setup` uses the observed `codex://dots` desktop route and `/dots` browser fallback. An accepted launch does not establish that onboarding completed. [Official onboarding](https://learn.chatgpt.com/docs/dots/getting-started)

### Advanced credential alternatives

Normally, use `dots auth`. Explicit credentials take precedence: `DOTS_ACCESS_TOKEN` plus `DOTS_ACCOUNT_ID` in the process environment, then a credential saved by this CLI, then the existing app-server login. An OpenAI platform API key does not provide personal Dot access.

`dots auth login --account-id ACCOUNT_ID` validates an existing account token from a hidden prompt before saving it in macOS Keychain, Windows Credential Manager, or supported Linux Secret Service/KWallet. `--token-stdin` reads one token line from a secret manager or authorized automation. No plaintext fallback. Avoid putting tokens in command arguments, shell history, or guide notes.

`dots auth status` reports credential source and presence without secrets; `--check` additionally checks account read access. `dots auth logout` removes only this CLI's explicitly saved credential. It does not sign out ChatGPT/Codex or clear environment overrides. Use first-party sign-out controls to end the shared login. Explicit tokens expire and are not automatically refreshed by this CLI.

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
| `dots doctor` | Inspect local readiness |
| `dots status` | Show local configuration and history |
| `dots folder` | Open the project folder |
| `dots web` | Open ChatGPT in the default browser |
| `dots guide` | Open the official setup instructions |
| `dots serve` | Start the local guide with launcher buttons |

`open`, `app`, `copy`, and `run` accept `--preset first|local|followup` or `--prompt TEXT`, plus `--dry-run`. Launch and clipboard actions never claim task submission. `dots COMMAND --help` lists every argument. Use `dots --no-color COMMAND` for plain output.

## Local guide and storage

`dots serve` binds to `127.0.0.1:8768`. It serves only allowlisted pages/documents; writes require same-origin checks and a per-process token. Account credentials and cloud control routes are not exposed to the guide server. The guide's switches record manual confirmations, not actual permissions.

The source checkout is the workspace; installed releases default to `~/Dots`. `DOTS_PROJECT` changes the workspace. `DOTS_DATA_HOME` changes local settings/history storage. Existing tracker settings remain supported. `serve` copies missing starter documents without overwriting existing files. History records launch actions, not prompt text. Credentials are stored separately in the OS credential store or supplied through the process environment.
