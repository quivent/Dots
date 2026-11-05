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

## Interactive crew speech: direct streaming

Use **POST `/v1/vmfactory/voice/responses/stream`** for interactive app speech.
`crew_voice_stream.py` is the thin owner-authenticated gateway to Garden's
`POST /v1/audio/speech/stream`, reached through the existing private connection.
The app makes one request, consumes NDJSON audio events and schedules PCM buffers
on AVAudioPlayerNode as they arrive. There are no job-status requests, sleep-based
status checks, MP3 encoding, R2 uploads or archive verification on this path.

Requests identify either a recorded notice (`eventId`) or an actual completed
assistant response (`responseId`), with `agentId`, `nativeSessionId` and
`textSHA256`. `crew_voice.context` resolves the full published reply, never a
notification title or truncated preview. Exact active roster/session, response
identity, source hash and assigned voice are checked throughout delivery. An END
is successful only after all bounded upstream streams finish and global sequence,
sample count, byte count and incremental PCM SHA match. Disconnect closes the
upstream and prevents further text-part requests. Full text is partitioned without
losing characters; HTTP chunk boundaries are not JSON-line boundaries.

Native build 2026110417 implements the incremental PCM player and bounded local
cache/diagnostics. Its per-response numeric receipt records text-ready,
request-start, first-audio-received and the first nonzero Core Audio render callback.
A Mac HTTPS test received first PCM in 2.662 seconds; that is network evidence,
not physical iPad playback evidence. Keep actual device receipts separate.

`POST /v1/vmfactory/voice/responses` remains a compatibility endpoint for the
previous completed-file client. It must not be reused for live app narration.
Existing Garden archive jobs are independent of interactive playback.

## Changing voices requires no app rebuild

The app has no hardcoded speaker profile. The gateway selects each member's
profile/version from `/etc/dots-hub/crew-voices.json` (root/dots-ops, 0640), after
checking actual service activation. Current native stream and codec interfaces
stay the same when a voice changes. Profile selection is pinned for an in-flight
reply; new replies pick up the new server assignment. Audio identity/cache keys
include the voice version, source response and exact session/text binding.

Garden owns `/workspace/gemstone/crew-voice/voices.json` and the actual reference
recordings/transcripts/hashes. Its private POST `/v1/crew/voices/reload` accepts
`expected_sha256`; tested hot reload retains the existing model/PID and deduplicates
conditioning by reference identity. Do not restart the model or rebuild iOS merely
to choose a voice. Soren currently selects `soren-grounded-v2`, version2. All53
canonical members have real starter assignments, using a small shared palette;
this is not a claim of53 distinct or individually listened-to voices.

## Private transport and storage

Gardener remains private at loopback18740. Backstage's user service
`fmvision-gardener-voice-tunnel.service` now forwards backend18740 **directly** to
Gardener18740. Its runtime-only `~/.config/crew/voice_ssh_config` alias
`gardener-voice` pins the current address, port, host key and dedicated private
key. The remote public key is restricted to forwarding to the model's loopback
port with shell commands disabled. The deploy template contains no host address
or credential. Keep this connection reference separate from unrelated crew hosts.

The previous Mac launch agents `org.fmvision.garden-voice-tunnel` and
`org.fmvision.garden-voice-backend` are disabled; their definitions and recovery
receipts are retained. They must not autostart and race for backend18740. Speech
no longer needs the Mac's Wi-Fi, uptime or memory capacity. Native app/backend
auth, exact source hashes and voice-profile selection remain unchanged.
No GPU IP, model credentials, R2 account keys or model weights belong in iOS.

Private archived audio, when used independently, is signed using AWS SignatureV4
with region `auto`; server-only R2 configuration is
`/etc/dots-hub/voice-r2.json` (root/dots-ops, 0640). Never log signed URLs or keys.
The initial default-signature401 is preserved in operational evidence.

Validation: `python3 -m unittest test_quick_tasks test_crew_voice test_crew_voice_stream -v`
uses isolated fixtures, including malformed sequences, incomplete END, input
preservation, authorization and cancellation with no continued model requests.
Production probes and device playback receipts remain separate from these tests.

## Submitted prompt playback and prompted replies

The stream endpoint also accepts `promptId` instead of `responseId`. It resolves
an already-observed **user** history item by native message/request ID, verifies
the exact account-authorized crew/session and original text SHA, and selects the
private `operatorVoice` assignment. Raw draft text, client-selected voices/models,
and assistant rows passed as prompts are rejected. The installed male preset is
`kokoro-adam`; it is not a clone of the operator. Only the stream path forwards
the selected model, so prompt playback does not use archive/job polling.

The native candidate arms speech only after explicit app message submission.
It voices the exact observed prompt first, then queues the completed reply in
that crew member's voice. Account/session changes invalidate authorization;
unsolicited snapshots and notification milestones cannot authorize narration.
One shared playback queue leaves a one-second gap between different speakers,
including operator-to-crew transitions. Native installation and real playback
acceptance must be recorded separately from source/model checks.

For a controlled model restart, `voice-rollout-hold.json` can delay **new** stream
requests for at most 90 seconds with one cancellable timer. Accepted inference
continues to drain. It is not a status poll and must not be inserted into the
per-frame source validation path. Preserve failed or slow measurements: a fast
first codec frame does not establish sustainable, gap-free generation.
