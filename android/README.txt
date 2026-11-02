Dots for Android

Native Kotlin/Jetpack Compose companion sharing the iPhone's server and Mac
protocol. Android 8.0+; package com.quivent.dots.

Build: ./android/build.sh
Output: android/app/build/outputs/apk/debug/app-debug.apk
Runs the debug build, local tests and Android lint. The script finds Homebrew
JDK/SDK on this Mac; elsewhere set JAVA_HOME (JDK 17) and ANDROID_HOME. The Gradle
wrapper pins 8.11.1 with its official checksum. SDK platform 35/build-tools 34
are required. No Python environment is needed.

Install:
  adb -s DEVICE_SERIAL install -r android/app/build/outputs/apk/debug/app-debug.apk
  adb -s DEVICE_SERIAL shell am start -n com.quivent.dots/.MainActivity

Authentication:
  Existing server: on the owner's iPhone, Account > Invite a phone > Create
  invitation. On Android, Enter invitation code and enter its eight-digit
  code. The code lasts ten minutes, works once, and gives this phone hosted Dots,
  shared chats and Bank access, including approval of Codex turns using the
  server's allowance. Guests cannot manage invitations or access Mac account Dots.
  Owners can revoke an invited phone from the same iPhone screen.
  Nearby invitation: iPhone Account > Invite a phone > Invite nearby; Android
  Join nearby > select invitation > Join. Allow Bluetooth pairing if prompted,
  then approve the invitation on iPhone. Keep both apps open during the handoff.
  Bluetooth carries only the temporary server code over an encrypted read;
  subsequent chats use HTTPS, so the phones do not need to stay nearby.
  The Android welcome screen shows Join nearby and Enter invitation code;
  Mac/direct/manual sign-in and the debug preview are under Other ways to connect.
  Invitations are never included in Bluetooth advertisements. Sharing stops on
  leaving the iPhone screen, backgrounding the app, expiry or successful handoff.
  Download this development build: https://dots.kosmos.institute/downloads/dots-android.apk
  Each phone receives an independent credential. No credentials are in the APK.
  Bluetooth: Connect through your Mac, allow Nearby devices, select the Mac,
  and enter its six-digit code. Dots Mac's Pair iPhone menu works for Android too.
  Account > Connect to Dots server switches a paired Mac credential to HTTPS
  after verification. Provider credentials are never sent to the hub.
  Direct: Connect ChatGPT directly matches the existing iPhone WebView sign-in
  and account-session capture flow. Providers may block embedded sign-in; Mac
  pairing and manual account-session entry remain available. A Platform API key
  does not grant access to account Dots. JWT claims only select account routing;
  a catalog read verifies authorization before saving credentials.

Security and delivery:
  Android Keystore AES-GCM protects credentials, drafts and pending sends.
  Backup and device transfer are disabled. Redirects never receive credentials.
  Direct provider credentials can only target https://chatgpt.com.
  BLE uses the UUIDs/framing in shared/BluetoothWire.swift, encrypted GATT
  characteristics, write acknowledgments, bounded responses and serialized
  exchanges. Unknown writes are never automatically replayed. Android 12+
  requests Nearby devices; older Android requires location permission to scan
  BLE devices. No location is collected. BLE needs an awake Mac and Dots Mac.

First parity pass:
  Catalog/search, Dot details, separate Dot/chat setup, hosted shared chats.
  Persistent drafts and pending request IDs, explicit retries and reconciliation.
  Approval before hosted sends and detected work; native operation approvals.
  Opposite message sides/colors, sender names, Markdown and clickable links.
  Reported context or labeled estimate, min(1M, provider window), 10% reserve,
  send/retry guards, context details and paginated conversation export.
  Task awareness and confirmed user-controlled Pause/Resume.
  Shared-chat members listen to each user message and may remain quiet if their
  response would not add useful context. Every selected listener still uses an
  approved Codex turn even when quiet; the approval screen explains this cost.
  Agents do not trigger one another automatically.
  Bank search, paging, synthesis/sources/uncertainty, revisions and text sharing.
  Provider creation errors and persistent uncertainty markers; no bypass of
  ChatGPT account permissions. Hosted agents remain separate Codex sessions.

Remaining differences:
  No Bonjour discovery or plain-HTTP local Wi-Fi connector. Public HTTPS and
  native BLE cover remote and nearby Mac access. The initial theme is dark.
  Tablet/foldable tuning, notifications, release/store distribution and provider
  token renewal remain future work. No verified context reset or universal
  provider autonomy gate exists on either app. Hosted Codex responses require
  approval because they can consume allowance. Bank is on the hosted connection.

Tests:
  ANDROID_SERIAL=emulator-5554 ./android/build.sh :app:connectedDebugAndroidTest
UI tests use explicit preview fixtures and a separate test vault; no model
turns are started. Preview is debug-only. Local tests cover context reserve,
message visibility/identity, approval classification, endpoint/credential
routing, JWT account hints, pending IDs, BLE framing and bounded invitation
parsing restricted to the intended HTTPS server.

Code: DotsApi.kt (transports), DotsModel.kt (state/outbox), Vault.kt (encryption),
BluetoothTransport.kt (Mac GATT), AuthScreens.kt (authentication), MainActivity.kt
and BankScreens.kt (interface). Both phones share the server's agent sessions,
room membership/history, approval state and research bank.

People and one-to-one chats:
  Chats > New chat > select a person. Dots are optional and start unselected.
  Your display name is editable in the picker. Leave the chat name empty to
  derive it from the selected participants, or enter a name yourself.
  With one other person and no Dots, messages create no agent jobs, require no
  AI approval, have no context meter, and do not wait for an agent response.
  Sender identity is supplied by the server for each viewer, so the other
  person's messages appear on the incoming side with their display name.
  New rooms are visible only to their participants; older shared rooms retain
  their previous workspace-wide visibility. Dots added to a room still reuse
  their global saved sessions across rooms. An invited phone currently represents
  one person; multiple owner connections represent the same server owner.

Live discovery:
  The hosted chat list refreshes every two seconds while the app is active and
  when returning from the background, independently of the slower provider/Mac
  catalog. New rooms created on another phone appear without manual refresh.
  This is foreground polling; background push notifications are not implemented.
