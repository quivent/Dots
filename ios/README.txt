Dots for iPhone

LOCAL CODEX SESSIONS
The Mac relay can expose explicitly selected existing Codex sessions through
the same paired-phone connection, including the public HTTPS Mac tunnel.
The local bridge attaches to ~/.codex/app-server-control/app-server-control.sock
using WebSocket JSON-RPC. It never starts another harness, resumes a thread,
changes its instructions, or overrides its model, tools or permissions.

Configuration: ~/.local/share/dots/local-codex.json (0600):
  {"sessions": [{"thread_id": "YOUR-THREAD-UUID", "name": "Session name"}]}
Optional codex_home selects a different local profile. Rebuild the native CLI
after source changes and restart com.quivent.dots.mobile to load configuration.
Only selected sessions are exposed; a session must already be loaded in the
existing daemon before a phone can send to it.

Local Codex chats show existing user/assistant history, including commentary,
and recent turn status. Reasoning and tool payloads are excluded. Every send
requires approval. It steers an active turn with its expected turn ID, or starts
a turn when idle. A race is reported without falling back to another operation.
Stop interrupts the current turn; child agents, external jobs and Goals have
separate controls. Native approvals/questions stay in Codex on the Mac.

Send identities and outcomes persist in private local-codex.sqlite. Uncertain
writes are never replayed, including after a restart. Reading a matching native
clientId reconciles delivery. Opening/history reads never start model turns.
The Mac must remain awake and reachable. Invited hosted-only devices cannot
access Mac sessions through the server router.

Native SwiftUI app based on the layout, theme, and interaction patterns in
~/Complex/ios. iOS 17 or later. No third-party iOS packages.

The app has Chats, Crew, Dots, and Account tabs, plus Bank on the hosted server.
Crew keeps connected local and hosted Codex agents and crew chats together,
with orange avatars. Chats keeps account Dot conversations and people chats;
the Dots catalog keeps account Dots. Workers stay in Crew across days.
Set up a Dot opens an action flow:
name it -> Create Dot -> Set up chat (when needed) -> Open chat. Each forward
button performs its operation; completed steps stay checked in the same sheet.
Finish later preserves the Dot; Finish setup resumes it from the Dots tab. The
empty Chats screen can also continue an existing Dot without recreating it.
Existing chats open directly. Activity, tasks, and pause are supported.
Pause and Resume are user controls; resulting state is verified with a provider read.

BUILD
  cd ~/Dots/ios
  make open

Select Joshy in Xcode and Run. The project uses the same signing team as Complex.
Generate a simulator build with make build. To test, pass a simulator destination:
  make test DESTINATION='platform=iOS Simulator,name=CrewTest iPhone'

CONNECTIONS
Connect through your Mac is the primary option. Open Dots Mac in the Mac menu
bar, choose Pair iPhone, select your Mac on the phone, and enter the six-digit
code. Bluetooth is the default; Wi-Fi discovery is also available. A single
nearby Bluetooth Mac is selected automatically. The keyboard closes after the
sixth digit, and Pair this Mac confirms the connection.

Connect ChatGPT directly opens a temporary, app-owned web session. After signing in,
tap Use this account. Account routing is taken from that session and GET /tbo
must succeed before the credentials are saved to this device's Keychain.
No Safari session, ChatGPT app credential store, or other app's files are read.
Embedded browser sign-in may be blocked by the provider. In that case, use an
explicit ChatGPT account session, or the optional Mac daemon below.
Public Sign in with ChatGPT OAuth does not grant Dots/conversation access.
An OpenAI Platform API key is not a substitute for an account session.

MAC COMPANION AND DAEMON
The installed companion is ~/Applications/Dots Mac.app. It starts at login.
The background service is ~/Library/LaunchAgents/com.quivent.dots.mobile.plist
and runs ~/Dots/dist/dots mobile on port 8769. No virtual environment is used.
Bluetooth traffic goes through the companion to the local daemon. The Mac
keeps the account login; the phone keeps its own revocable connection token.

To install on another Mac, build the native CLI, then run:
  dots auth
  dots mobile --host 0.0.0.0 --install-daemon
  python3 macos/build.py --install
  open -a "$HOME/Applications/Dots Mac.app" --args --pair
Allow Bluetooth when macOS and iOS ask. Wi-Fi also requires local network
permission. Bluetooth characteristics require encrypted OS pairing. Wi-Fi uses
HTTP on your local network; use a trusted private network or Tailscale.

Codes expire after two minutes, work once, and lock after five wrong guesses.
Choose Pair iPhone again for a fresh code. Disconnect all phones in the Mac
menu revokes phone tokens. The root token is never sent over Bluetooth or
advertised. Private token files live in ~/.local/share/dots (mode 0600).
Logs are in ~/Library/Logs/Dots; requests do not log credentials or message text.
The Mac must be awake and signed in. iOS can retain a Bluetooth connection while backgrounded and reconnects
from the saved Mac ID when reopened. Range and OS scheduling affect availability.

CONTEXT AND CREDITS
Chat shows full context counters only when the service explicitly reports them.
Otherwise the single context meter says Estimate / full usage unknown and shows
an approximate count for loaded text. This excludes hidden instructions, memories,
tools and unloaded history. The planning target is 1,000,000 tokens, not a verified
model limit. The final 10% is visibly reserved; new sends and retries stop at
900,000 including a draft estimate. A smaller reported limit gets its own 10%
reserve. Unknown full input and reply size prevent a guaranteed provider limit.
The compact details button opens Context & credits and full conversation export.
Saving does not reset model context. Draft coding/tool warnings are estimates of
intent; active task notices come from reported task statuses. These are usage
notices, not price quotes or a guarantee about whether credits will be charged.

PROTOCOL AND CURRENT LIMITS
This app uses experimental internal account endpoints, as the CLI does.
The public OAuth flow only authorizes identity/eligible public API use; it does
not authorize access to ChatGPT conversations or other account context.

Create Dot uses the observed first-party creation request, including
create_thread=true and should_initialize=true. A root thread must be returned
before the app confirms creation. When the server returns a messaging room too,
the flow goes straight to Open chat. Otherwise Set up chat first re-reads the
profile, then creates a missing room with POST /tbo/{id}/messaging-room. It never
creates another Dot to retry chat setup. Appearance and connected apps remain
optional actions in the official ChatGPT app. No separate initialization call
is invented. Live creation and initialization were verified on Joshy with
the user-requested Pocket Dot on 2026-10-20. The server supplied its chat room
during creation; the separate room-creation write is still live-test pending.

Native text history and sending use /messaging/rooms/{id}/messages. The service
may require client integrity/attestation that this app cannot provide. Rejection
is shown as an error; no integrity checks are bypassed. Live mobile sign-in,
separate room creation and message sending still require an account test.
Bluetooth pairing/reconnect, Dot creation, and history reads have been verified
on Joshy. History pages use 25 items; the live service rejects limit=50.

Messages use a stable request_id/idempotency_token. An ambiguous send is kept
in Keychain, shown as unconfirmed, and never retried automatically. An explicit
retry keeps the same token. Ambiguous profile creation blocks new creation until
the user refreshes and reviews the catalog. Reads refresh while chat is active;
streaming, attachments, voice, background notifications, and full onboarding are
not implemented. Account changes discard in-memory data and reject stale replies.

TESTING AND PREVIEW
XCTest covers routing, session headers, pagination, separate setup operations,
unknown outcomes, idempotency, history reconciliation, and hidden-content filtering.
UI tests use DEBUG-only sample data, not a live account. Launch with -demo for a
clearly labelled preview, or -signed-out for the connection screen. Neither flag
is active in Release builds. Python tests cover the optional relay independently.

Sources checked 2026-10-20:
https://learn.chatgpt.com/docs/dots/getting-started
https://developers.openai.com/siwc/token-sharing-open-source
../research/dot-protocol.json

CHAT POLISH
Messages from calpico-member actors belong to the Dot even when role=user.
Your messages are blue on the right; Dot messages are purple on the left.
Inline Markdown formatting and hyperlinks render natively. Sending persists the
pending message first, clears the composer immediately, and retains the keyboard.
Unconfirmed writes keep their original request ID and require explicit retries.
History failures appear inline and polling continues rather than showing repeated
modal alerts. Polling waits one second when awaiting a reply, two seconds otherwise,
plus request time. Replies are not streamed token by token.

The visible Context toolbar action opens counters when reported, a text estimate,
conversation viewing/export, reset limitations, and measured last-fetch duration.
No verified provider context-reset operation is exposed. Rebooting, reconnecting,
exporting, or creating a new Dot does not establish a fresh token allowance; a new
Dot can start with relevant ChatGPT memory. No memory was erased during testing.

APPROVAL BEFORE WORK
Conversation, reasoning, and read-only research lookups may proceed. Detected
coding, separate-job, credit-spending, and external-action requests require an
Approve and send action. Cancel leaves the draft untouched. Approval is stored
with the pending message and its original request ID for retries; approval of one
request does not grant permission to another. Detection is a heuristic, not a
provider-wide execution gate.

The provider controls actual execution state. The user controls Pause and Resume
from the chat toolbar or Dot details. The app reads the provider state afterward;
it never resumes automatically on launch or reconnect. Sending stays disabled
while a Dot is paused, but its conversations remain readable.

The current connection reports provider Custom rules as read-only (canEdit=false).
No provider policy was changed. These client controls cannot prevent every job a
cloud Dot starts independently. The hosted hub design retains the requirement for
an enforceable source approval boundary. Pocket was not resumed during this update.
