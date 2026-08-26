#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/TradingAgentApp"

swift build -c release

APP="../TradingAgentApp.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp Info.plist "$APP/Contents/Info.plist"
cp .build/release/TradingAgentApp "$APP/Contents/MacOS/TradingAgentApp"

echo "Built $APP"
