# VMFactory persistent studio hub

`vmfactory_hub.py` runs as dots-vmfactory.service on the central relay server,
loopback 18771. Caddy routes `/v1/vmfactory/*` there with immediate flushing.
Requires Ubuntu python3-aiohttp. Existing Dots pairing authenticates owner devices;
hosted-only invite credentials cannot access studio state.

SQLite WAL at `/var/lib/dots-ops/chat-hub/vmfactory-sync.sqlite` stores records and
bounded revision events. Back up with SQLite's backup API; copying only the live
main file can omit WAL transactions. JSON is used on the wire and within flexible
metadata fields. Large world assets are not transferred through this service.

The Mac publisher uses its separate private token; the hub keeps only SHA256 in
`/etc/dots-hub/vmfactory-publisher.sha256`. It can publish studio metadata and
Maestro. Native FSEvents drives discovery updates, with a separate persistent
native daemon observer for visible chat. No periodic state polling is used.

## Additional servers

Keep the existing Codex sessions loaded on the worker server. Install this Dots
checkout and websocket-client there. Create a private mode0600 connector config:

```json
{
  "url":"wss://dots.kosmos.institute/v1/vmfactory/connect?role=publisher",
  "token":"GENERATE_A_UNIQUE_RANDOM_SECRET",
  "server":"Worker server",
  "codex_home":"/root/.codex",
  "agents":[{"id":"worker-one","name":"Worker One","thread_id":"EXISTING_THREAD_UUID"}]
}
```

On the hub, add the SHA256 of that secret as a key in root-owned,
root:dots-ops mode0640 `/etc/dots-hub/vmfactory-publishers.json`:

```json
{"SHA256_HEX":{"agents":["worker-one"],"metadata":false,"source":"worker-server"}}
```

Do not share the Mac publisher secret with other servers. Each scope lists only
that server's stable agent IDs. Then run under the existing user's service manager:

```sh
python3 /path/to/Dots/deploy/crew_connector.py /private/crew-connector.json
```

Only outbound WSS is required. The app lists published workers in Studio → Crew.
The connector observes loaded sessions, rejoins them without config overrides,
and relays visible user/assistant text only. It never answers native approvals.
Only an explicit phone Send or Stop writes to a session. A private SQLite nonce
ledger prevents uncertain requests being automatically sent again. No session is
created or resumed into a second harness. Restarting the connector does not replay
user inputs. Agent execution remains on its host; background iOS reconnects on
foreground. Offline servers reject sends rather than queueing future work.

Tests: `.venv/bin/python -m unittest discover -s deploy -p test_vmfactory_hub.py`.
They cover durable state, persistent push, auth, explicit socket RPC, and two-server
routing/isolation. Use fake daemons for write tests; do not send test turns to crew.

Current rental connector: `root@141.152.237.39:50113`, supervisor program
`vmfactory-crew`, files `/opt/vmfactory-crew`, agent `rental-worker`.
Its existing saved session is `01a19302-ae3d-7b03-a295-8c2d55f9ec25`.
No session was loaded during commissioning, so only saved visible history was
verified. To revoke access, remove the publisher registry entry whose `source`
is `rental-141-152-237-39`; authorization closes within 30 seconds. Stop the
connector with `supervisorctl stop vmfactory-crew` before ending the rental.
No inbound public service or GPU/model process was added on the rental.

Task storage uses normalized `tasks`, `task_dependencies`, `task_references`,
`worker_current` and append-only deduplicated `worker_events` tables. Existing
record blobs migrate transactionally on service startup. The authored source
plan is currently imported from the project, not a substitute for central task
leases/acceptance. Its dates and scope remain visible. Worker observations retain
their original timestamp and never become fresh merely because a phone reconnects.
JSON remains for plan metadata, flexible metric fields and API import/export.

## Shared task database and world collection

The publisher now reads Maestro's existing tracker-factory shared-tasks.sqlite
in mode=ro. The main Tasks and Live Work homes use its tasks/runs/lanes/workers,
not the supplemental 32-item authored workbench JSON. `work_replica.py` stores a
read replica in shared_work_* SQLite tables. Base/end revisions, record changes
and deletions prevent a worker heartbeat resending the full board. Gaps fail
closed and recover from a snapshot; this replica never writes back or grants claims.
The immutable report index is read from the same tracker runtime directory.

Worlds use FMVision's shared exact-ID world index and preview catalog. Published
web entrances and their original modules/assets are served through the private
Mac Vite host (5176), outbound restricted SSH tunnel (relay18772), and
world_gateway.py on https://dots.kosmos.institute:8444. dots-worlds.service runs
as caddy solely so it can use that existing host's TLS certificate. Caddy continues
to manage renewal; dots-worlds-certificate.path triggers SIGHUP certificate reload.
The existing Caddy routes and TLS router remain unchanged.

The dedicated world SSH key is restricted to remote loopback18772 forwarding,
with no shell. Authorized-key options are restrict,port-forwarding,
permitlisten="127.0.0.1:18772",command="/usr/bin/false". No public Mac listener
or inbound Mac port is required. world_host.py installs the two Mac launch agents.

The gateway accepts owner device authorization, gives WebKit an opaque Secure,
HttpOnly session cookie, revalidates against the existing device registry every
30 seconds, and strips authorization/cookies before contacting the world server.
There is no agent input or model context in this path. Assets stream in bounded
chunks and retain range/content-type headers. iPhone previews and world rendering
are actual source-owned content; image contents are never supplied to a model.
