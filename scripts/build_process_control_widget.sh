#!/bin/zsh
set -euo pipefail

ROOT_DIR="/Users/plo/Documents/remoteBot"
SOURCE="$ROOT_DIR/scripts/process_control_widget.swift"
BUILD_DIR="$ROOT_DIR/build/widget"
APP_NAME="RemoteControlWidget"
APP_DIR="$BUILD_DIR/$APP_NAME.app"
CONTENTS_DIR="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
PLIST_PATH="$CONTENTS_DIR/Info.plist"
BINARY_PATH="$MACOS_DIR/$APP_NAME"

mkdir -p "$MACOS_DIR"

cat > "$PLIST_PATH" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>ko</string>
  <key>CFBundleExecutable</key>
  <string>RemoteControlWidget</string>
  <key>CFBundleIdentifier</key>
  <string>com.plo.remotebot.widget</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>Remote Widget</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
  <key>LSUIElement</key>
  <true/>
</dict>
</plist>
PLIST

if [[ ! -f "$BINARY_PATH" || "$SOURCE" -nt "$BINARY_PATH" || "$PLIST_PATH" -nt "$BINARY_PATH" ]]; then
  /usr/bin/swiftc \
    -O \
    "$SOURCE" \
    -framework AppKit \
    -framework WebKit \
    -o "$BINARY_PATH"
fi

echo "$APP_DIR"
