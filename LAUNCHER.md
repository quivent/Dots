# Dots CLI

Run `make` to build and install the CLI, then `dots setup` to open Dot onboarding. Windows: `py -m pip install .`. Linux: `make` also works. Requires Python 3.10+. See [INSTALL.md](INSTALL.md).

## Independent setup steps

Run any step directly. There is no required sequence, completed-step state, or pipeline that prevents the working parts from running.

| Command | One action | What success establishes |
|---|---|---|
| `dots setup check` | Inspect local prerequisites | CLI, app detection, credential presence, local-guide availability; no API call |
| `dots setup app` | Launch the installed desktop app | Launch request accepted; no navigation or onboarding claim |
| `dots setup` or `dots setup open` | Request the Dot entry page | Uses `codex://dots` on desktop; `/dots` browser fallback |
| `dots setup web` | Open `https://chatgpt.com/dots` | Browser launch requested |
| `dots setup auth` | Inspect CLI credential presence | Presence only; no account access claim |
| `dots setup api` | Read the account Dot catalog | Read access works; no write access claim |
| `dots serve` | Start the local guide | Guide works independently of cloud authentication |

Each setup command supports `--json`. Failed API access does not block app launch, the local guide, prompts, or saved shortcuts. Keep the guide server running; Ctrl+C stops it. `--port PORT` and `--no-open` are available on `serve`.

The installed desktop app must support the Dot route and the account must have access. The direct desktop route was found in first-party application source; actual navigation has not been visually verified here. [Official onboarding](https://learn.chatgpt.com/docs/dots/getting-started)

## Account credentials

Cloud commands use **experimental internal ChatGPT routes**, discovered in application version 26.1013.40934. They are not a published Dot API. The default backend URL is confirmed in that application's source; account/workspace routing may differ. No authenticated live call has been verified in this workspace. Source details: [research/dot-protocol.json](research/dot-protocol.json).

An OpenAI platform API key does not supply personal Dot account access. This CLI has no verified standalone browser sign-in flow. It accepts an authorized ChatGPT account access token and the matching account/workspace ID that you already hold; it does not extract desktop/browser sessions. Installing or opening ChatGPT does not sign the CLI in.

To validate and save an existing credential:

```sh
dots auth login --account-id ACCOUNT_ID
```

Paste the token into the hidden prompt. It is checked with a read-only catalog request before saving in macOS Keychain, Windows Credential Manager, or a supported Linux Secret Service/KWallet backend. No plaintext fallback. For a secret manager or other authorized automation, `--token-stdin` reads one token line from stdin. Avoid putting tokens in command arguments, shell history, or guide notes.

Alternatively, supply `DOTS_ACCESS_TOKEN` and `DOTS_ACCOUNT_ID` in the process environment. Environment tokens take precedence over saved credentials. Tokens expire; automatic refresh is not implemented.

| Command | Effect |
|---|---|
| `dots auth status` | Show credential source and presence, without secrets |
| `dots auth status --check` | Also verify catalog read access |
| `dots auth logout` | Remove the CLI's stored credential; environment credentials remain |

If no authorized account credential is available, cloud commands remain blocked. Use graphical onboarding and the independent local commands below. Public API agents are project-scoped and are not a replacement for account Dots. [API agent reference](https://developers.openai.com/api/reference/typescript/resources/beta/subresources/agents/methods/create)

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
