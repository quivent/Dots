Dots Mac

The native desktop window lists your ChatGPT Dots, reads conversation history,
sends text messages, creates Dots subject to account eligibility, and provides
explicit pause/resume controls. Open ~/Applications/Dots Mac.app, or choose
Open Dots from its menu-bar icon. Closing the window keeps phone pairing alive;
Quit Dots stops the app. Reopen the app to bring the desktop window back.

The menu-bar companion also connects iPhone Dots to the Mac's existing ChatGPT login.
Install/build from ~/Dots with python3 macos/build.py --install. The installed
app is ~/Applications/Dots Mac.app and starts at login through
~/Library/LaunchAgents/com.quivent.dots.mac.plist.
Login launches use --background and do not open a chat window.

The desktop uses native AppKit controls, without an embedded browser or local
model. History loads on selection, focus, or Refresh. After a send, reply checks
run every five seconds for up to two minutes, only while the window is key.
They stop on close, minimize, or switching away. No conversations are polled
continuously in the background. The companion health check runs locally every
30 seconds with timer tolerance for power saving.

Writes are submitted once. Unconfirmed sends retain a private delivery marker
across app restarts; Refresh checks history without resending. Unconfirmed
creation disables another creation attempt until the catalog confirms the Dot.
Additional-Dot restrictions are shown directly from the account response.

Checks (from ~/Dots):
  swiftc -swift-version 5 macos/DotsMac/DesktopAPI.swift macos/tests/main.swift -o /tmp/dots-desktop-tests
  /tmp/dots-desktop-tests
  /tmp/dots-desktop-tests --live  # read-only live catalog/history check

The separate native daemon is ~/Dots/dist/dots mobile, installed with:
  dots mobile --host 0.0.0.0 --install-daemon
Its service is ~/Library/LaunchAgents/com.quivent.dots.mobile.plist.
Sign in with dots auth if the Mac has no account session. No venv is required.

Open Dots Mac, allow Bluetooth, and choose Pair iPhone from its menu-bar icon.
On iPhone select Connect through your Mac, choose this Mac, enter the code,
and tap Pair this Mac. Codes last two minutes and work once. Bluetooth uses
encrypted GATT with OS pairing. Wi-Fi discovery is also available; HTTP needs
a trusted network or Tailscale. Account credentials stay on the Mac.

Disconnect all phones revokes their connection tokens. Pair each again with a
new code. Closing the code window does not stop the daemon or Bluetooth.
The Mac must be awake. Logs: ~/Library/Logs/Dots. Safe status without secrets:
~/.local/share/dots/mac-status.json. Token files in that directory are private.

Stop the daemon: launchctl bootout gui/$(id -u)/com.quivent.dots.mobile
Restart it: launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.quivent.dots.mobile.plist
Quit Dots Mac from its menu to stop Bluetooth and Wi-Fi discovery.
