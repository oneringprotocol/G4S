#!/bin/sh
# Keep the app running on http://localhost:3000 with macOS launchd:
# it starts at login and restarts within 10 s if it ever stops.
#   scripts/service.sh install     start now and at every login
#   scripts/service.sh restart     pick up code changes
#   scripts/service.sh uninstall   stop and remove
#   scripts/service.sh status
# Log: data/cache/server.log
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
LABEL="com.g4s.route-audit"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

case "$1" in
install)
    mkdir -p "$HOME/Library/LaunchAgents" data/cache
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array><string>/bin/sh</string><string>$ROOT/run.sh</string></array>
    <key>WorkingDirectory</key><string>$ROOT</string>
    <key>EnvironmentVariables</key>
    <dict><key>PATH</key><string>/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin</string></dict>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ThrottleInterval</key><integer>10</integer>
    <key>StandardOutPath</key><string>$ROOT/data/cache/server.log</string>
    <key>StandardErrorPath</key><string>$ROOT/data/cache/server.log</string>
</dict>
</plist>
EOF
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null
    launchctl bootstrap "$DOMAIN" "$PLIST" && echo "Installed. The app runs at http://localhost:3000"
    ;;
restart)
    launchctl kickstart -k "$DOMAIN/$LABEL"
    ;;
uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null
    rm -f "$PLIST" && echo "Removed."
    ;;
status)
    launchctl print "$DOMAIN/$LABEL" 2>/dev/null | grep -E "state =|pid =|last exit" || echo "Not installed."
    ;;
*)
    echo "Usage: $0 install|restart|uninstall|status"
    exit 1
    ;;
esac
