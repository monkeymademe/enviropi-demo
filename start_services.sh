#!/bin/bash
# Convenience script to start the dashboard + collector in the background
cd "$(dirname "$0")"

VENV_PYTHON="./.venv/bin/python"
if [ ! -x "$VENV_PYTHON" ]; then
    VENV_PYTHON="python3"
fi

start_if_needed() {
    local script="$1"
    local label="$2"
    if pgrep -f "$script" > /dev/null; then
        echo "$label is already running"
    else
        echo "Starting $label..."
        "$VENV_PYTHON" "$script" &
        echo "$label started (PID: $!)"
    fi
}

start_if_needed "web_app.py" "Web dashboard"
start_if_needed "sensor_collector.py" "Sensor collector"

echo ""
echo "Dashboard: http://localhost:5000"
echo "Network:   http://$(hostname -I | awk '{print $1}'):5000"
echo ""
echo "Stop with: pkill -f web_app.py; pkill -f sensor_collector.py"
