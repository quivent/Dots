"""Build and optionally install the native menu-bar Bluetooth companion."""
from pathlib import Path
import argparse
import plistlib
import re
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    app = root / 'build' / 'Dots Mac.app'
    executable = app / 'Contents/MacOS/DotsMac'
    executable.parent.mkdir(parents=True, exist_ok=True)
    with (app / 'Contents/Info.plist').open('wb') as file:
        plistlib.dump({'CFBundleExecutable': 'DotsMac', 'CFBundleIdentifier': 'com.quivent.dots.mac',
                      'CFBundleName': 'Dots Mac', 'CFBundlePackageType': 'APPL', 'CFBundleVersion': '2',
                      'CFBundleShortVersionString': '0.2.0', 'LSUIElement': True,
                      'NSBluetoothAlwaysUsageDescription': 'Dots connects your iPhone to your Mac over Bluetooth so your ChatGPT login can stay on this Mac.',
                      'NSLocalNetworkUsageDescription': 'Dots advertises this Mac so your iPhone can find it for pairing.',
                      'NSBonjourServices': ['_dots._tcp'],
                      'NSAppTransportSecurity': {'NSAllowsLocalNetworking': True},
                      'CFBundleIconFile': 'AppIcon.png'}, file)
    resources = app / 'Contents/Resources'
    resources.mkdir(exist_ok=True)
    shutil.copy2(root / 'ios/Dots/Assets.xcassets/AppIcon.appiconset/AppIcon.png', resources / 'AppIcon.png')
    subprocess.run(['swiftc', '-swift-version', '5', '-O', '-framework', 'AppKit', '-framework', 'CoreBluetooth',
                    str(root / 'shared/BluetoothWire.swift'),
                    str(root / 'macos/DotsMac/DesktopAPI.swift'), str(root / 'macos/DotsMac/DesktopWindow.swift'),
                    str(root / 'macos/DotsMac/main.swift'), '-o', str(executable)], check=True)
    identities = subprocess.check_output(['security', 'find-identity', '-v', '-p', 'codesigning'], text=True)
    identity = re.search(r'\b([A-F0-9]{40})\s+"Apple Development:', identities)
    subprocess.run(['codesign', '--force', '--sign', identity.group(1) if identity else '-', str(app)], check=True)
    if args.install:
        destination = Path.home() / 'Applications/Dots Mac.app'
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists(): shutil.rmtree(destination)
        shutil.copytree(app, destination)
        agent = Path.home() / 'Library/LaunchAgents/com.quivent.dots.mac.plist'
        agent.parent.mkdir(parents=True, exist_ok=True)
        with agent.open('wb') as file:
            plistlib.dump({'Label': 'com.quivent.dots.mac', 'ProgramArguments': ['/usr/bin/open', '-g', '-a', str(destination), '--args', '--background'],
                          'RunAtLoad': True, 'ThrottleInterval': 10,
                          'StandardErrorPath': str(Path.home() / 'Library/Logs/Dots/mac-error.log')}, file)
        print('Installed ' + str(destination))
    else:
        print(app)


if __name__ == '__main__': main()
