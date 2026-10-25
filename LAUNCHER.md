# Dots CLI

Run `make -C cli` from the project root (or `make` inside `cli/`) to build and install the CLI, then `dots setup` to see the individual setup commands. Use `dots setup run` to execute prerequisites through account discovery. Windows: `py -m pip install .`. Linux: `make -C cli` also works. Requires Python 3.10+. See [INSTALL.md](INSTALL.md).

## Interface guides

`dots guide` shows the guide index. Choose `dots guide terminal`, `dots guide desktop`, `dots guide mobile`, or `dots guide sources`. The terminal guide is also available as `dots terminal guide`, `dots terminal`, and `dots terminal --help`. Guides render Markdown headings, command blocks, tables, and links with Rich; they need no external Glow installation. `--plain` prints the original Markdown for piping or saving, and `--no-color` before the command disables terminal styling. Guide commands display text only and never authenticate, import identities, send messages, or start services.

## Saved Dots and sources

The terminal defaults to `--source local`: a private registry of actual provider identities, not a locally running model. Save existing account Dots with `dots import --source chatgpt`, then use `dots list`, `dots use Pocket`, and `dots chat Pocket`. Importing reads metadata only; it sends no messages and starts no model turns. `dots create NAME` creates an actual ChatGPT Dot and saves/selects that exact identity locally. Both local and explicit ChatGPT creation use the same account API and save the result. Provider restrictions on additional Dots still apply; no Codex substitute is created when creation fails.

| Source | Meaning |
|---|---|
| `local` (default; `--local` is an alias where available) | Saved identities and local selection; live chat and controls go to that saved identity's provider |
| `chatgpt` | Direct discovery and control of account Dots through the existing ChatGPT sign-in |
| `hosted` | Separate hosted Codex worker/room catalog; these conversations use Codex allowance, and terminal chat to this source is disabled |
| `shortcuts` | The older URL shortcut registry used by `dots open` and `dots run` |

Sources can be specified before or after the command, such as `dots --source chatgpt list` or `dots list --source chatgpt`. There is no fallback to another source when a name is missing. Saved names resolve to provider IDs, so renaming or changing the current directory cannot select a different agent accidentally.

`dots import DOT --source chatgpt --name ALIAS` saves one Dot under a local alias; `--by-id` avoids account name lookup. Reimporting the same identity refreshes its metadata and preserves its alias and selection. `dots rename OLD NEW` renames the local alias only. Use `dots rename DOT NEW --source chatgpt` for a provider rename. `dots use NAME` selects the local default; `dots use DOT --source chatgpt` changes the provider's primary Dot. `dots forget NAME` removes a saved reference only, without deleting, pausing, or changing the provider Dot.

The private registry is `agents/registry.json` under the configured runtime directory (`DOTS_DATA_HOME`). It stores IDs, aliases, source, selection, and last-observed metadata, without credentials or conversation text. `dots list` works offline; saved pause metadata may be stale, so chat reads the live profile before sending. Existing shortcut files are preserved separately and are never interpreted as agent sessions.

Catalog discovery finishes before a name is reserved, so a failed read leaves no stale reservation. A name is then reserved before the creation request. An uncertain outcome remains marked `creating`, with a start timestamp and the last reported creation error; no automatic retry or duplicate creation is attempted. Inspect `dots show NAME` and `dots list --source chatgpt` to reconcile. If the provider created the Dot, run `dots import ID --by-id --source chatgpt --name NAME` to recover the pending reference in place. If creation did not succeed, `dots forget NAME` removes the local reference before an explicit retry. Forgetting does not cancel or undo provider creation. A definitive server rejection removes the reservation automatically.

Live check on 2026-10-25: the existing login and account catalog worked, and the catalog contained `Pocket`. An additional creation request for `Polly` was rejected with HTTP 403 and `Additional dots are not enabled`. This is an account restriction; changing the local name or skipping catalog discovery does not enable additional Dots.

Actual Dots execute in the cloud; the Mac and terminal are clients/relays. Conversations with a Dot do not count toward ChatGPT usage limits, while tasks delegated to Work or Codex use those products' limits. This CLI does not start a Codex agent or add model calls to a Dot conversation. It also cannot enforce a provider-wide prohibition on delegated work. [Official Dots usage](https://learn.chatgpt.com/docs/dots)

Hosted reads use `DOTS_HUB_URL` (default `https://dots.kosmos.institute`) and a separate `DOTS_HUB_TOKEN` or private `DOTS_HUB_TOKEN_FILE` (default `~/.local/share/dots/mobile-token`). ChatGPT account credentials are never sent to that hub. `dots import --source hosted` can save hosted identities for inspection/control; they remain labeled as Codex workers and cannot be used by terminal chat. New hosted workers are provisioned separately. No production server changes or new model sessions are made by this unification.

## Set up

| Command | Action |
|---|---|
| `dots update` | Update this CLI from the public GitHub repository |
| `dots auth` | Reuse an existing ChatGPT login, or start first-party browser sign-in when missing; then verify Dot account access |
| `dots preflight` | Check local readiness and current Dot account access without signing in |
| `dots installation` | List the individual setup commands without running them |
| `dots setup` | Show the individual setup commands; no actions run |
| `dots setup run` | Run prerequisites: update → preflight → auth → list --source chatgpt in order |
| `dots setup onboard` | Open Dot onboarding in ChatGPT |
| `dots doctor` | Full troubleshooting: local state, account access, tools, assets, and private-note permissions |
| `dots web` | Open the local guide independently of cloud access |

Preflight does not open a login flow or create files. A missing login is reported as `auth_required`, allowing the following `dots auth` step to sign in. Connection errors are reported separately and return a failure status. `dots doctor` additionally inspects configuration/history parsing, app-server availability, clipboard support, guide assets, and private-note permissions. Neither diagnostic command creates a Dot or changes account state.

If you are already signed into ChatGPT/Codex on this computer, Dot commands reuse that login automatically. You do not need to paste a token or run `auth` again. `dots create NAME` uses the same authentication source. `dots preflight`, `dots setup`, and `dots setup onboard` accept `--json`. The interactive runner does not.

When no reusable login exists, run `dots auth`. It starts the first-party `codex login` flow and then checks Dot access. This requires a local app-server executable, found through `codex` on PATH or the bundled macOS ChatGPT app. Set `DOTS_CODEX` to its executable if needed. If neither is installed, install ChatGPT/Codex first. No Dot is created by `auth`, `preflight`, or `setup`.

App launch, local tools, authentication, connection checks, creation, and room repair are independent commands. A failed connection check does not block `dots app`, `dots setup`, `dots doctor`, or `dots web`.

Mistyped commands get a short correction or help command, without a usage dump. The former `dots setup steps` command points to `dots installation`; corrections never execute a command.

The main screen uses three colored command groups: Setup, Dots, and Manage. `dots` and `dots --help` show the same indented command tree; `dots COMMAND --help` lists options.

The terminal setup plan lists ten operations: CLI update, prerequisites, authentication, catalog discovery, profile creation, conversation creation, initialization, conditional room recovery, optional primary selection, and final profile inspection. Conversation creation and initialization are currently requested by `dots create NAME`; independent commands for those operations are not implemented. Updates check the available version first and install only a newer CLI, preserving satisfied dependencies. Installation progress stays concise; errors show a short message and the path to a private log. Raw installer output is never printed. Updates install the latest public `quivent/Dots` main branch into the Python environment running this CLI. The updater uses pip with the same installation policy as make: the user site for global Python, or the active virtual environment. It bootstraps pip once if missing and retains satisfied dependencies. Each runner step starts a fresh CLI process so it uses the updated code.

`dots setup` and `dots installation` show the same plan; both accept `--json` and perform no setup actions.

The setup display and runner share one plan definition. The runner executes only the four prerequisite commands, prints each before execution, and stops on failure with the independent retry command. It does not create a Dot or open graphical onboarding. Remaining operations are shown with their current command and bundled, conditional, or optional status; no saved completion flags block independent commands. `dots setup onboard` remains a separate graphical alternative.

## Authentication and verification

The local app-server protocol confirms the existing ChatGPT account and hands off a token through its experimental `getAuthStatus` RPC. The token is used in memory; the CLI does not display it, save another copy, or read browser/session credential files. Existing-login reuse and an authenticated `GET /tbo` catalog request were verified on 2026-10-18. Dot creation, initialization, and activity have not yet been verified live. A new browser login is covered by mocked tests; the active login was retained during testing.

Cloud commands use internal ChatGPT routes observed in application version 26.1013.40934, rather than a published Dot API. The local auth handoff is also experimental; app updates can change it. Source details: [research/dot-protocol.json](research/dot-protocol.json). [Official login caching](https://learn.chatgpt.com/docs/auth#login-caching)

`dots setup onboard` uses the observed `codex://dots` desktop route and `/dots` browser fallback. An accepted launch does not establish that onboarding completed. [Official onboarding](https://learn.chatgpt.com/docs/dots/getting-started)

### Advanced credential alternatives

Normally, use `dots auth`. Explicit credentials take precedence: `DOTS_ACCESS_TOKEN` plus `DOTS_ACCOUNT_ID` in the process environment, then a credential saved by this CLI, then the existing app-server login. An OpenAI platform API key does not provide personal Dot access.

`dots auth login --account-id ACCOUNT_ID` validates an existing account token from a hidden prompt before saving it in macOS Keychain, Windows Credential Manager, or supported Linux Secret Service/KWallet. `--token-stdin` reads one token line from a secret manager or authorized automation. No plaintext fallback. Avoid putting tokens in command arguments, shell history, or guide notes.

`dots auth status` reports credential source and presence without secrets; `--check` additionally checks account read access. `dots auth logout` removes only this CLI's explicitly saved credential. It does not sign out ChatGPT/Codex or clear environment overrides. Use first-party sign-out controls to end the shared login. Explicit tokens expire. If a saved token is rejected, `dots auth` verifies the shared ChatGPT login (or starts sign-in) before removing the rejected saved override. Invalid saved records are ignored. Environment overrides remain explicit and are never silently removed.

## Direct account commands

Select `--source chatgpt` to use account IDs, account names, and the provider primary selection directly.

| Command | Request / behavior |
|---|---|
| `dots --source chatgpt list` | Read all catalog pages from `GET /tbo` |
| `dots --source chatgpt create NAME` | Read catalog, then make one `POST /tbo` creation request |
| `dots --source chatgpt use DOT` | Select the account's primary Dot with `PUT /tbo/primary` |
| `dots --source chatgpt show [DOT]` | Read a Dot profile |
| `dots --source chatgpt rename DOT NEW_NAME` | Rename with one `PATCH /tbo/{id}`; use `--by-id` to skip name lookup |
| `dots --source chatgpt activity [DOT]` | Read all activity pages |
| `dots --source chatgpt activity DOT --open` | Read activity, then open the Dot's web page |
| `dots --source chatgpt tasks [DOT]` | Read all task-history pages |
| `dots --source chatgpt tasks DOT --task TASK_ID` | Read one task |
| `dots --source chatgpt pause [DOT]` | Request a runtime pause |
| `dots --source chatgpt resume [DOT]` | Request a runtime resume |
| `dots --source chatgpt room [DOT]` | Explicitly create/recover a messaging room |

`DOT` accepts an ID or a unique display name. Omitted targets use the only Dot or the account's primary Dot; ambiguous names fail with instructions to use an ID. The cloud management commands in this table support `--json`. Pause/resume output preserves the server response: an unconfirmed status is not reported as a confirmed change.


### Terminal chat

Run `dots chat Pocket` to read recent messages and start an interactive conversation. An omitted target uses the selected or only saved Dot. `--by-id` treats the target as a local registry ID. Add `--source chatgpt` to address provider IDs directly and use the account primary selection. The Dot needs an existing messaging room; use `dots room DOT` explicitly if one is missing. Chat never creates a Dot, creates a room, or resumes a paused Dot automatically.

`dots chat Pocket --message "Hello"` sends one message and waits for new Dot messages. Use `--timeout 120` and `--poll 2` to adjust the reply wait and polling interval, in positive seconds. Exit status is 0 after a new Dot message is found, 2 when the reply wait expires, 1 on an error, or 130 on Ctrl-C. Redirected input requires `--message`; it is not silently submitted. Replies are polled, not token streamed, and a new Dot message is not proof that all delegated work has completed.

Interactive commands: `/refresh` reads messages, `/wait` continues polling a pending message, `/quit` (or Ctrl-D) exits, and `/abandon` explicitly stops tracking a pending message. Abandoning does not cancel delivery or provider work; sending the same text again can duplicate work. While a message is pending, further sends are blocked. Another participant's new Dot reply may satisfy the wait; the internal API does not provide a reliable causal completion signal.

Each send makes one POST with a fresh request/idempotency identity. Before that request, a private recovery record is saved under the runtime directory's `chat/` subdirectory. It contains request, message, and baseline history IDs, without message text or credentials. Interrupted or uncertain sends remain pending across restarts and are checked against history, never automatically resent. Chat sessions sharing a runtime are serialized. A successful POST confirms acceptance, while a timeout waiting for a reply does not imply failed delivery. Internal account routes remain experimental. Sending and reply recovery are covered by simulated API tests; live Pocket history reads are verified, but a live send has not been performed for this change.

Creation requests `create_thread: true`, `should_initialize: true`, and the appropriate first/additional flag. It does not subsequently create a room, change the account primary, launch a window, or submit a user task. The returned identity is saved and selected locally. Inspect the returned profile with `dots show DOT`. If the messaging room is missing, run `dots room DOT` independently. Onboarding initialization is requested from the server; completion is not inferred from profile creation.

Writes are never automatically retried. A timeout or server failure can mean the write succeeded even though its response was lost. Inspect `dots list`, `dots show`, or `dots activity` before repeating a write. Incomplete creation responses report an unknown outcome rather than inviting duplicate creation.

For recovery when catalog discovery is broken, `dots show DOT_ID --by-id --source chatgpt` sends the profile request directly. The same `--by-id` option works with `use`, `activity`, `tasks`, `room`, `pause`, and `resume`. These operations do not depend on `dots list`. To make creation independent of catalog discovery, choose `dots create NAME --first` or `dots create NAME --additional`; this sends only the creation request. Without either flag, creation reads the catalog to choose automatically.

## Local tools

These do not require account credentials. The earlier shortcut-only behavior is retained explicitly with `--source shortcuts`. The `--local` flag now means saved Dot identities, matching the terminal default.

| Command | Actual effect |
|---|---|
| `dots create NAME --source shortcuts` | Save a pending shortcut and open graphical onboarding |
| `dots create NAME --source shortcuts --no-open` | Save the pending shortcut only |
| `dots configure URL --name NAME` | Save an actual conversation link |
| `dots configure ''` | Clear the selected conversation link |
| `dots list --source shortcuts` | List saved shortcuts |
| `dots use NAME --source shortcuts` | Select the shortcut used by `open` and `run` |
| `dots activity --source shortcuts` or `dots history` | Read local launch history |
| `dots open` | Open the saved conversation |
| `dots run --preset local` | Copy a task and open ChatGPT; paste and send yourself |
| `dots app` | Launch the desktop app |
| `dots copy --preset first` | Copy a prompt |
| `dots prompt local` | Print a prompt |
| `dots doctor` | Full troubleshooting diagnostics |
| `dots status` | Show local configuration and history |
| `dots web` | Start the local guide with launcher buttons |

`open`, `app`, `copy`, and `run` accept `--preset first|local|followup` or `--prompt TEXT`, plus `--dry-run`. Launch and clipboard actions never claim task submission. `dots COMMAND --help` lists every argument. Use `dots --no-color COMMAND` for plain output.

## Local guide and storage

`dots web` binds to `127.0.0.1:8768`. It serves only allowlisted pages/documents; writes require same-origin checks and a per-process token. Account credentials and cloud control routes are not exposed to the guide server. The guide's switches record manual confirmations, not actual permissions.

The source checkout is the workspace; installed releases default to `~/Dots`. `DOTS_PROJECT` changes the workspace. `DOTS_DATA_HOME` changes local settings/history storage. Existing tracker settings remain supported. `setup onboard`, `web`, and prompt-launch commands create missing starter documents and linked guide files without overwriting existing files; `doctor` and dry runs remain read-only. Starter prompts require no separate tracker installation. History records launch actions, not prompt text. Credentials are stored separately in the OS credential store or supplied through the process environment.

The guide saves entered notes in the private runtime file `dots-trials.md`, created with owner-only permissions on POSIX systems. It never appends them to tracked `TRIALS.md`. That document is a reusable template. Workspace initialization adds missing ignore rules while preserving existing entries. Ignore rules protect new local results and note files; they do not untrack files already committed to an existing repository.

URL launch failures return an error. If the desktop Dot protocol handler fails, onboarding tries the HTTPS route. A successful launch means the request was accepted, not that navigation or onboarding finished. Activity opening uses the same launch/error handling and reports fetched activity separately from navigation failure.

### Receiving while composing

Interactive `dots chat` keeps checking for incoming messages while the input line
is open. Replies print above the prompt without replacing your draft. Sending runs
in the background; the status line distinguishes sending, waiting and receive
connection errors. You can compose the next message immediately. If you press
Enter while an earlier message is pending, the unsent draft stays in the editor.
The terminal view uses a Qwen Code derived banner and composer layout. Its
connection and runtime labels describe the selected ChatGPT Dot.
`/wait` and `/refresh` request another receive check without blocking composition.
The transcript supports mouse-wheel scrolling and Page Up/Page Down while the
composer stays active. New replies do not move your reading position when you
have scrolled up. Ctrl-End returns to the latest messages and follows new replies.
Messages render Markdown headings, lists, links, tables and fenced code blocks;
code blocks use syntax highlighting for their stated language. Resizing rewraps
the transcript to the available width.
Outgoing terminal messages support up to 50,000 characters; the provider may
apply its own limits. This does not change the provider's model context window.
Bracketed paste returns the transcript and composer to the bottom without sending
the draft. Press Enter, Ctrl-S, or click Send to send the entire block. Shift+Enter,
Ctrl+Enter, Ctrl+J, and Alt+Enter insert newlines when the terminal reports the
modified key distinctly. Alt+Enter and Ctrl+J remain available when it does not.
Terminals that paste without bracketed-paste markers can submit lines containing
Enter; enable bracketed paste in your terminal when pasting multiline text. Commands such as `/quit` also use Enter. The
footer shows the current character count. Multiline pasted paths or code that
start with `/` are sent as message text rather than interpreted as commands.

Each visible Dot response has a session-local number. Click its `Copy #N` button
under the response or in the prompt footer to copy the whole response to the
system clipboard. Use
`Older` and `Newer` to reach every response's button. `/copy N` works by keyboard;
`/copy` copies the latest response. Copying preserves multiline text and never
sends a message or changes the draft. Response text stays in memory only.
`/quit` finishes any in-flight journal/network operation before releasing the
conversation lock. Nothing is automatically resent or resumed. `--message` keeps
its existing bounded reply wait and `--timeout` behavior.
