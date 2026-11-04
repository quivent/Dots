# Paired owner quick tasks and crew speech

`quick_tasks.py` installs `POST /v1/vmfactory/work/tasks`. An authenticated Studio
owner sends `{request_id: <UUID>, title: <1–500 characters>}`. Successful replies
contain the canonical task ID and revision. Retry an uncertain save with the same
request ID **and** title. A changed title under the same ID is rejected.

The server writes through the existing FMVision TaskFactory HTTP authority at
`127.0.0.1:3750/v1/trackers/fmvisual`, using revision-checked replacement. It neither
opens the database file nor introduces a second task store. Captures enter the
unassigned Operator Inbox, in a `later` stage, for scope and assignment before
execution. It does not invent acceptance tests, code scopes or worker activity.
Only the server reads `/etc/dots-hub/task-database.token` (root/dots-ops, 0640).

`crew_voice.py` installs `POST /v1/vmfactory/voice/responses`. Owner requests carry
`eventId`, `agentId`, `nativeSessionId`, and `textSHA256`. The server resolves the
actual recorded coordinator notice, current roster/session and selected voice.
It does not accept arbitrary text, client-selected voices or public requests.
Initial voice assignment is Soren's adjustable `soren-bright-v1` reproduction
trial. Other crew continue using device speech until given their own profiles.

Garden inference remains private at loopback port 18740. The existing Mac
`~/.config/crew/ssh_config` connection **garden** resolves its changing address.
Two scoped launch agents hold the authenticated, loopback-only bridge:
`org.fmvision.garden-voice-tunnel` forwards Mac 28740 to Garden 18740;
`org.fmvision.garden-voice-backend` forwards backend 18740 back to Mac 28740.
No GPU IP is compiled into iOS. A failed experiment using direct backend SSH
was stopped and its experimental user service removed. No existing key was changed.

The gateway returns only bounded job state and, after complete identity checks,
a 120-second signed URL for the exact private MP3. Server-only R2 configuration
is `/etc/dots-hub/voice-r2.json` (root/dots-ops, 0640). Signing explicitly uses
AWS Signature V4 and region `auto`; the initial default-signature 401 is retained
in operational evidence. Never log signed URLs or copy R2 keys into clients.

The native integration is a separate reviewed AgentNotifications.swift overlay,
handed to the Mac Resident Engineer for the next normal same-bundle release.
It checks session/account/event/text/voice identity, selected audio SHA/size,
caches within 32 MiB per account and uses AVAudioPlayer. Device speech is the
fallback. Cancellation on background and conversation change prevents stale
playback. Status requests are bounded to the active synthesis job, not a crew
or task polling loop. Cached audio is not proof of spoken-text intelligibility,
physical-device playback or app installation.

Validation: `python3 -m unittest test_quick_tasks test_crew_voice -v` uses isolated
fixtures only. Production probes cover unauthenticated 401 and owner malformed
400 without creating tasks, notices or model turns. Real Soren trial generation
and a private signed R2 download passed exact size/SHA validation. Native helper
passes an iOS SDK type check; deployment/playback evidence remains separate.
