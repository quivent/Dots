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

Garden remains private at loopback18740. The existing Mac
`~/.config/crew/ssh_config` connection **garden** resolves its changing address.
Two scoped launch agents hold the authenticated loopback-only bridge:
`org.fmvision.garden-voice-tunnel` forwards Mac28740 to Garden18740;
`org.fmvision.garden-voice-backend` forwards backend18740 to Mac28740.
No GPU IP, model credentials, R2 account keys or model weights belong in iOS.

Private archived audio, when used independently, is signed using AWS SignatureV4
with region `auto`; server-only R2 configuration is
`/etc/dots-hub/voice-r2.json` (root/dots-ops, 0640). Never log signed URLs or keys.
The initial default-signature401 is preserved in operational evidence.

Validation: `python3 -m unittest test_quick_tasks test_crew_voice test_crew_voice_stream -v`
uses isolated fixtures, including malformed sequences, incomplete END, input
preservation, authorization and cancellation with no continued model requests.
Production probes and device playback receipts remain separate from these tests.
