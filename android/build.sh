#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ -z "${JAVA_HOME:-}" ] && [ -d /opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home ]; then
    export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
fi
if [ -z "${ANDROID_HOME:-}" ] && [ -d /opt/homebrew/share/android-commandlinetools ]; then
    export ANDROID_HOME=/opt/homebrew/share/android-commandlinetools
fi
if [ "$#" -eq 0 ]; then set -- :app:assembleDebug :app:testDebugUnitTest :app:lintDebug; fi
exec ./gradlew "$@"
