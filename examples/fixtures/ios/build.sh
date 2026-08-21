#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
app="$repo_root/.maestro-vision/fixtures/ios/MaestroVisionFixture.app"
module_cache="$repo_root/.maestro-vision/cache/swift-modules"
sdk=$(xcrun --sdk iphonesimulator --show-sdk-path)

mkdir -p "$app" "$module_cache"
cp "$repo_root/examples/fixtures/ios/Info.plist" "$app/Info.plist"
xcrun swiftc \
  -sdk "$sdk" \
  -module-cache-path "$module_cache" \
  -target arm64-apple-ios16.0-simulator \
  -framework UIKit \
  "$repo_root/examples/fixtures/ios/Sources/main.swift" \
  -o "$app/MaestroVisionFixture"
codesign --force --sign - "$app"
printf '%s\n' "$app"
