# Dots backend E2E plan

Status: baseline dry-run complete; implementation verification pending.

## Boundary

Exercise the existing Qwen Ink application with `DOTS_BACKEND=1`, using a JSONL subprocess fixture in place of Python. Do not send a real provider message, change authentication, create a Dot, or resume a paused Dot. Python bridge tests use mocked `DotClient` and temporary runtime directories. Each fixture request is recorded so rendered output alone cannot conceal duplicate sends or local-agent execution.

## Baseline dry-run

Executed against the global CLI on 2026-10-25:

```sh
qwen --version
qwen --help
```

Both returned 0. Version: `0.26.1`. Help advertises Qwen model-provider authentication, local core tools and the normal Qwen agent CLI. There is no Dots/backend/selected-Dot option or ChatGPT Dot authentication choice. This confirms the public CLI integration gap. Environment-only behavior is not established by help output; no interactive baseline was started because it could load user customizations or credentials. The post-change test must observe JSONL requests to prove routing.

## Build and focused verification

From the Dots root:

```sh
python3 -m unittest tests.test_tui_bridge tests.test_chat
```

From `qwen-code`:

```sh
npm run build
npm run typecheck
npm run bundle
```

Run changed TypeScript unit tests from `qwen-code/packages/cli`, not the repository root. Exact test filenames will be recorded with results once the implementation exists.

## Offline fixture contract

Create a temporary executable at `/tmp/dots-e2e-<unique>/fixture-python`. It accepts the normal Python command arguments without importing Python code, reads `{id, method, params}` JSON lines from stdin, writes only `{id, result}` or `{id, error: {message}}` JSON lines to stdout, and logs request metadata to a file in that temporary directory. Never log credentials. Set `DOTS_PYTHON` to its absolute path, `DOTS_ROOT` to the Dots checkout, `DOTS_DOT=fixture-dot`, and `QWEN_RUNTIME_DIR` to the temporary directory's `runtime` subdirectory.

The fixture supports `connect`, `refresh`, `send`, `status`, `abandon` and `close`. A snapshot is `{name, profile, pending, messages}`, where messages contain stable `id`, `text`, and `mine` fields. Connect returns a historical user message plus Markdown assistant content. Sending records exactly one request, sets pending, and refresh later supplies a new assistant reply. Separate fixture modes cover paused state, uncertain delivery, malformed JSON and subprocess exit.

## Group A: startup and history

Unique terminal session: `dots-backend-startup-<unique>`; size 120x36.

```sh
tmux new-session -d -s dots-backend-startup-<unique> -x 120 -y 36 \
  'cd /Users/jay/Dots/qwen-code && DOTS_BACKEND=1 DOTS_DOT=fixture-dot DOTS_PYTHON=/tmp/dots-e2e-<unique>/fixture-python DOTS_ROOT=/Users/jay/Dots QWEN_RUNTIME_DIR=/tmp/dots-e2e-<unique>/runtime node dist/cli.js'
tmux capture-pane -t dots-backend-startup-<unique> -p -S -100
```

Expected: actual Qwen application layout and composer appear; fixture history is visible; no model-provider authentication dialog. Request log shows one connect and subsequent refresh reads, zero sends. Resize to 60x20 and then 120x36: composer remains usable and transcript reflows.

## Group B: send, receive, and draft preservation

Unique terminal session: `dots-backend-send-<unique>` with independent fixture/runtime/log.

Send `DOTS_E2E_SINGLE_SEND` as text, wait for the composer to show it, then send Enter separately. Poll the log/rendered output until the reply arrives, with a 15-second deadline. Immediately type `DRAFT_MUST_STAY` before the fixture releases the reply.

Expected: one `send` request containing only the submitted text, one outgoing message, and the new assistant reply. The draft remains in the composer when polling updates the transcript. Enter during pending delivery must not issue another send. A changed message with the same provider ID updates rather than duplicates its existing history item. Multiline pasted text remains message data even when it begins with `/`.

## Group C: commands and no local agent

Unique terminal session: `dots-backend-commands-<unique>` with independent fixture/runtime/log.

Exercise `/status`, `/refresh`, `/wait`, `/abandon`, `/help`, `/quit` separately, with the UI idle between submissions. Also submit a Qwen local-agent command such as `/model`, shell-prefixed text, and unsupported attachment input.

Expected: supported commands route to the appropriate read or explicit tracking action; help/quit stay local to presentation. Unsupported local-agent features produce a clear message and issue no model requests, shell commands, tool calls, MCP calls, or internal prompts. No command automatically resumes a paused Dot. Normal text with shell syntax is either sent literally or rejected without execution.

## Group D: delivery errors and cleanup

Independent sessions: `dots-backend-paused-<unique>`, `dots-backend-uncertain-<unique>`, `dots-backend-crash-<unique>`.

- Paused: send is rejected, pending stays false, no resume request appears.
- Uncertain: fixture records one send then returns a delivery error; refresh reconciles the pending state, never resends. Repeating Enter must not duplicate the request.
- Transport failure: malformed response or child exit yields a visible error, no silent transport restart or automatic resend.
- Quit/EOF: child receives close or stdin EOF, exits, and releases the backend lock after in-flight ownership settles. No fixture process remains.

Clean each session with `tmux kill-session -t <name>` if it did not exit itself. Remove only its dedicated temporary directory after recording results.

## Parallelism

Groups A-D may run in separate test-engineer agents only after the bundle exists. Each must have a unique fixture executable, runtime, log, and tmux session; none may touch user credentials or real messaging rooms. Build/typecheck remain sequential prerequisites.

## Results

- Baseline version/help: PASS as described above.
- Python bridge tests: pending.
- TypeScript focused tests: pending.
- Build/typecheck/bundle: pending.
- Offline terminal groups: pending.
- Real provider send: intentionally not exercised by this plan.

### Offline compiled terminal verification

Executed against `/Users/jay/Dots/qwen-code/packages/cli/dist/index.js` in tmux session `dots-backend-fresh-5cgroqlt`, initially 100x32, then 60x20. Isolated fixture artifacts: `/var/folders/jr/v0r5p12d4wd23287rz1r_bl00000gn/T/dots-backend-e2e-5cgroqlt/`.

The executable `fixture-python` replaced the entire Python worker process. It accepted `-u -m cli.tui_bridge`, used no account or network code, and logged JSONL requests. Its status response was aligned with the implemented snapshot-plus-tasks schema. The startup command set `DOTS_BACKEND=1`, `DOTS_DOT=fixture-dot`, `DOTS_POLL=0.3`, `DOTS_ROOT=/Users/jay/Dots`, `DOTS_PYTHON=<fixture executable>`, `DOTS_FIXTURE_LOG=<fresh-requests.jsonl>`, and isolated `QWEN_RUNTIME_DIR`.

Observed results:

- PASS: actual upstream Qwen logo/header/composer/transcript appeared; no provider authentication picker.
- PASS: `OFFLINE_HISTORY_MARKER` and rendered bold Markdown appeared from the connect snapshot.
- PASS: request log contains exactly one `send` with text `DOTS_E2E_SINGLE_SEND`; delayed `OFFLINE_REPLY_MARKER` appeared after refresh polling.
- PASS: `DRAFT_MUST_STAY` remained in the composer while the reply arrived.
- PASS: `/status` issued exactly one `status`, displayed `OFFLINE_STATUS_MARKER`, and did not increase send count. Upstream command completion required a second Enter to submit a completed slash command.
- PASS: resizing to 60x20 retained the composer and `/help commands · Ctrl+C exit` footer and reflowed history.
- PASS: `/quit` exited the terminal session; the fixture logged EOF; final send count remained one.
- Presentation finding, reported for correction: rotating upstream Tips still appeared after startup despite `hideTips`, advertising Qwen resume/context features. Composer placeholder also advertised `@path/to/file` despite text-only Dot messaging.

Evidence files: `fresh-startup.txt`, `fresh-send.txt`, `fresh-status.txt`, `fresh-narrow.txt`, and `fresh-requests.jsonl` in the fixture directory. An earlier session used stale compiled output with `MessageType.LLM` and omitted assistant content; that run is not evidence for the corrected build. The fresh build used `MessageType.GEMINI` and rendered both history and replies correctly.

Pending scenario groups: paused/uncertain transport failures and malformed-child response terminal scenarios. Focused backend/hook tests may cover these, but this terminal run does not establish them. No live provider send was performed.

### Bundle entry verification caught a separate startup defect

The first final-artifact check used `qwen-code/dist/cli.js`, rather than the compiled package entry. It exposed `Failed to initialize session: SkillManager not available` and an indefinitely initializing interface. The fixture connected and loaded history, but zero sends occurred because there was no active composer. Root cause identified and reported: esbuild bundles `packages/cli/src/cli.ts`, while the Dots startup dispatch initially existed only in `packages/cli/index.ts`; the bundled bootstrap therefore entered ordinary Qwen initialization. This finding invalidated that first bundle check. Captured `final-bundle-startup-failure.txt` and `bundle-before-entry-fix.jsonl`; session cleaned through Ctrl-C and fixture EOF. Waiting for the source bootstrap fix and rebundle before rerunning final-artifact and slow-send shutdown checks.

### Final bundled artifact and in-flight shutdown: PASS

After adding Dots dispatch to the actual bundled `src/cli.ts` bootstrap and rebuilding (`All bundle assets copied`), reran `node /Users/jay/Dots/qwen-code/dist/cli.js` with the isolated fixture.

- PASS: history and Markdown rendered in Qwen's application; composer became usable; no authentication picker.
- PASS: after a two-second startup wait and a completed message/reply, no rotating `Tips:` line or `@path` placeholder appeared.
- PASS: `DOTS_FINAL_BUNDLE_SEND` produced exactly one logged `send`, the expected reply, and clean worker EOF on quit.
- PASS: a separate fixture slept three seconds inside `send`. Submitted `DOTS_SLOW_SEND`, observed its logged send, then requested `/quit` while the send was still in flight (less than two seconds after it began). The frontend remained alive during that operation. Worker EOF occurred 3.004 seconds after send began, and the final request log contained exactly one send. The frontend exited after worker completion; there was no resend.

Final terminal sessions `dots-bundle-final-5cgroqlt` and `dots-bundle-slow-5cgroqlt` both exited. Evidence in the same isolated artifact directory: `final-bundle-startup.txt`, `final-bundle-reply.txt`, `final-bundle-slow-during-quit.txt`, `final-bundle-result.txt`, `dots-bundle-final-5cgroqlt.jsonl`, and `dots-bundle-slow-5cgroqlt.jsonl`. This final bundle run supersedes the earlier bundle-entry failure. No account backend, provider request, live send, or authentication mutation was used.
