Cherry relay deployment — 20 October 2026

Host: root@88.216.68.234 (Ubuntu 24.04)

The public endpoint now routes hosted chats to a persistent server hub.
ChatGPT account Dots still use the Mac bridge and need it awake. Hosted
Codex agents run independently on this server. Offline writes are not queued.

Route:
Phone -> https://dots.kosmos.institute -> chat router loopback:18770
  hosted chats -> per-agent Unix WebSocket -> native Codex app-server
  account Dots -> loopback:18769 -> reverse SSH -> Mac:8769 -> provider.

The Mac LaunchAgent com.quivent.dots.cherry-connector reconnects automatically.
Its separate SSH key is ~/.ssh/dots-cherry-connector. The server account
dots-connector has no interactive command access. Its authorized key permits
only the relay listener and relay destination; it is not a root credential.
ChatGPT account Dot credentials remain on the Mac. The separate dots-ops
Codex login is on the server. The hub stores only device credential hashes.

No Tailscale is required. The server's newly installed Tailscale package and
private-listener service were removed at the user's request. Existing Tailscale
on the Mac was not changed.

DNS: Vercel A record dots -> 88.216.68.234, record ID
rec_4a2e1138947451aae46f4456. The apex and wildcard records are unchanged.
HTTPS: /etc/caddy/dots-public.caddy, imported by /etc/caddy/Caddyfile.
The existing HAProxy TLS router sends only the new hostname to Caddy; SimpleX
remains the default backend. Caddy obtains and renews the TLS certificate.
Config backups have suffix .before-dots-20261020T190036Z.
The proxy forwards /v1/*, except /v1/pairing/* administration is blocked.
Pairing via /v1/pair still requires a one-use code created locally on the Mac.
Requests use the existing device credential; HTTPS alone is not authentication.
Access logging is not enabled for this site. Body limit: 64KB.

Use https://dots.kosmos.institute in the iOS app's network connection screen.
The existing app labels that network choice "Wi-Fi"; it also works over cellular
with this HTTPS address. Pair through the Mac pairing action using the server
address. Never use the public IP over plain HTTP. Phone setup and cellular
sending/receiving have not yet been verified.

Verified: server -> tunnel -> Mac health returns 200 with a credential;
missing credential returns 401; read-only provider catalog returns 200. These
checks also passed through public HTTPS with certificate verification enabled.
Public pairing administration returns 403 and HTTP redirects to HTTPS.
No provider messages were sent or Dot runtime state changed during setup.

Disable bridge:
  launchctl bootout gui/$(id -u)/com.quivent.dots.cherry-connector
Remove the Dots import from Caddyfile and the dots.kosmos.institute use_backend
line from haproxy.cfg, validate both configs, then reload Caddy and HAProxy.
Remove the specific Vercel DNS record above if retiring the hostname.

The central history database, durable queues, source adapters and phone hub
integration remain the implementation described in ARCHITECTURE.md.

Phone connection update

The installed iOS app now has Account -> Connect to Dots server. It verifies the
phone's existing pairing credential through public HTTPS before switching from
Bluetooth or local network. Direct ChatGPT credentials are never forwarded to
this hostname. Pending sends or uncertain creation block changing transport.
Dot creation remains available through Set up a Dot -> Create Dot -> Set up chat.
This creates provider-backed Dots, not server Codex workers.

Server maintenance roles

Codex CLI 0.163.0 is installed at /opt/dots-codex (no Python environment).
The separate dots-ops Unix user owns /var/lib/dots-ops and is not in sudo.
The existing ubuntu account was left unchanged. The two Codex profiles are:
  monitor: read-only sandbox, no privilege escalation.
  maintainer: writable workspace, manual user review of requested escalation.
Both are on demand; no AI scheduler, autonomous maintenance loop or recurring
credit-consuming task was started. They are CLI profiles, not cloud Dot accounts.

Start an interactive worker from the Mac terminal:
  ssh -t root@88.216.68.234 'runuser -u dots-ops -- dots-ops monitor'
  ssh -t root@88.216.68.234 'runuser -u dots-ops -- dots-ops maintainer'

The maintainer can prepare patches and run tests under
/var/lib/dots-ops/maintainer. It cannot change production configuration or run
sudo. Live privileged maintenance still needs the owner to approve and execute
the specific operation; no general-purpose privileged execution broker exists.
Root-owned profile files require proposals and explicit approval before live
changes. Those instructions supplement the OS boundary, not replace it.

The Ubuntu sandbox required an AppArmor userns rule scoped to this root-owned
Codex binary. /etc/apparmor.d/dots-codex grants that permission while leaving
system-wide user namespace restrictions enabled. Tested: monitor writes denied;
maintainer workspace writes allowed; writes under /etc denied.

Device authentication was attempted but did not complete in the CLI after the
browser step. The documented auth-cache SSH fallback transferred the existing
Mac Codex login into the account's private .codex/auth.json (0600). Login status
then reported Logged in using ChatGPT. No token contents were displayed.

Hosted workers are exposed through the shared router and phone catalog.
The iOS app can create shared rooms and review native operation approvals.

Named hosted agents

Wavesmith, Oscillator and Belle were created at the user's request as separate
persisted Codex sessions under dots-ops. Their registry is
/var/lib/dots-ops/agents.json; workspaces are /var/lib/dots-ops/agents/NAME
(lowercase). Each has a root-owned named Codex profile, workspace permissions
and on-request approvals routed to the user. No role specialization was assumed.
No turn/start or model task was issued during creation. All three sessions were
verified by resuming from a new local app-server process. They now have three independently supervised daemon processes. They remain
Codex sessions, not ChatGPT cloud Dots. No model turns were needed for setup.

Resume one interactively:
  ssh -t root@88.216.68.234 'runuser -u dots-ops -- dots-agent Wavesmith'
Substitute Oscillator or Belle. The iPhone can now list these sessions and create shared rooms with them.

Hosted chat hub — current deployment

Services: dots-chat-router, dots-agent@wavesmith, dots-agent@oscillator,
dots-agent@belle. All run as dots-ops, with no sudo/root access. Each native
daemon uses its own Unix WebSocket listener and saved thread. There is no MCP.
The router uses Ubuntu python3-websocket; no virtual environment is used.

History, room membership, message identities and approval state persist in
/var/lib/dots-ops/chat-hub/chats.sqlite (SQLite WAL). Restart marks unfinished
jobs unknown and pending approvals stale; it never replays a model turn.
Every hosted send requires explicit approval of its Codex turns. Members
respond to approved user messages only, without autonomous agent-to-agent loops.
Native command/file permission requests are forwarded for one-operation review.
Each agent shares its saved model session across rooms. Pause affects all rooms
containing that agent. Creating a shared room does not reset agent context.
Reported context is guarded at 90% of min(1M, reported model window), including
a text estimate for the forwarded transcript. Unknown context stays unknown.

Mac LaunchAgent com.quivent.dots.device-sync watches paired-phones.json and
retries every 120 seconds. deploy/sync-chat-devices.py sends only SHA256 hashes
to /etc/dots-hub/device-hashes.json. Pairing/revocation propagation requires the
Mac online; existing hosted chats continue with their last synchronized hashes.

Check without starting model turns:
  systemctl is-active dots-chat-router dots-agent@wavesmith dots-agent@oscillator dots-agent@belle
  cd /opt/dots-hub && python3 -m unittest -v test_chat_router
  Authenticated GET /v1/tbo lists the hosted agents and shared rooms.

Back up live history using SQLite backup(), not by copying its WAL database:
  python3 -c 'import sqlite3; s=sqlite3.connect("/var/lib/dots-ops/chat-hub/chats.sqlite"); d=sqlite3.connect("/var/backups/dots-chat-hub.sqlite"); s.backup(d); d.close(); s.close()'
Keep backups private. Provider-created additional account Dots still return a
provider 403; hosted chat setup does not bypass that account restriction.

Research Bank

dots-bank is a separate, non-AI systemd service. It owns the SQLite WAL database
/var/lib/dots-bank/research.sqlite as the unprivileged dots-bank user. Agents
never need to write research files. The router talks HTTP over the private
/run/dots-bank/bank.sock Unix socket; peer UID and filesystem permissions limit
access to dots-ops and root. No new public port, MCP or model subscription.

The three hosted Codex agents have native bank_save, bank_search and bank_get
tools. Tools run only during an approved chat turn, with author, chat and thread
attribution supplied by the router. Repeating identical content within that turn
returns the same saved entry. Saving/searching does not launch another model.
The installed 0.163 protocol registers tools on thread/start only. All three
original sessions were verified empty before Bank-enabled sessions were created;
their previous IDs remain in agents.json and agents.before-bank.json. No model
turn was started. enable-bank-tools.py refuses to replace nonempty sessions.
Native tools persist in session metadata and restore on resume.

Entries contain title, synthesis, source URLs, tags, uncertainty and creation
time. Entries are append-only; corrections may identify a superseded entry.
Source links are supplied by the author, not independently verified by storage.
Search matches words in stored content; it is not a model or embedding service.
Research content is returned as data, never as agent instructions.

The iPhone Bank tab browses/searches entries and shares full synthesis text.
GET /v1/bank/entries?q=... and GET /v1/bank/entries/ID use normal phone auth.
There is no unauthenticated Bank access or public save/delete endpoint. Pocket
and other ChatGPT account Dots do not currently have these native Bank tools.

Checks: runuser -u dots-ops -- python3 -m unittest -v test_research_bank test_chat_router
Live authenticated empty-bank read and native tool registration/resume verified;
test data stays in temporary databases. A private initial SQLite backup is at
/var/backups/dots-research-bank.sqlite. No recurring/offsite backup is configured.
To refresh that backup as root, use SQLite backup() from research.sqlite to that
destination with umask 077; never copy an open WAL database alone.

People and participant-scoped rooms (21 October 2026)
  GET /v1/hosted/people lists the owner and non-revoked invited people, marking
  the caller with is_self. POST /v1/hosted/people/me updates that caller's name.
  Owner phone credentials share one owner identity; each invited credential
  currently represents a separate person. This is not a full multi-device
  user-account directory yet.
  POST /v1/hosted/rooms accepts people IDs and optional agent members. The caller
  is always included. Without agents, at least one other person is required.
  These messages are persisted and polled over HTTPS without any Codex jobs,
  tool access, model approval or context guard. Retries retain request identity
  and are bound to the sending person. History includes per-viewer sender_is_self
  and display names; legacy messages cannot be retroactively attributed reliably.
  New explicit-participant rooms filter catalog, profiles, history, posting,
  runtime controls, tasks and native approvals by membership. Legacy rooms keep
  existing shared-workspace access. Device revocation still blocks all requests.
  New tables people/private_rooms/room_people and nullable author_id columns
  migrate existing SQLite databases without replacing rooms or message history.
  A private database and router backup precede deployment. Removing only the
  new code keeps old room records readable by old clients but does NOT preserve
  new room privacy: restore the prior backup for an actual rollback, or keep the
  updated membership checks. Agent sessions remain shared across their rooms;
  room membership does not isolate an agent's native memory.

Automatic chat discovery
  GET /v1/hosted/rooms returns the caller's complete authorized hosted catalog
  without contacting the Mac or provider. Both apps check it every two seconds
  while active and immediately on returning to the foreground. iPhone previously
  refreshed its catalog only at launch or manually; this caused rooms created on
  another phone to stay absent. The ordinary provider catalog remains separate.
  A slower provider response cannot overwrite a more recent hosted snapshot.
  Failed discovery preserves the visible catalog and local chat state and shows
  a non-blocking retry notice. Reads create no jobs or model turns. This is
  foreground synchronization, not APNs/FCM or background push notifications.
