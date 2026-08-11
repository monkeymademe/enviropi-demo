#!/bin/bash
# Install Enviro+ dashboard + collector on a Raspberry Pi (Zero / Zero 2 W recommended)
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${GREEN}Enviro+ Dashboard — install${NC}"
echo "================================"
echo "Install directory: $SCRIPT_DIR"
echo ""

if [ "$(id -u)" -ne 0 ]; then
    echo -e "${YELLOW}This script needs root for apt, raspi-config, and systemd.${NC}"
    echo "Re-run with: sudo ./install.sh"
    exit 1
fi

REAL_USER="${SUDO_USER:-pi}"
if [ "$REAL_USER" = "root" ]; then
    REAL_USER="pi"
fi
REAL_HOME="$(getent passwd "$REAL_USER" | cut -d: -f6)"
VENV_DIR="$SCRIPT_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"
PIP_BIN="$VENV_DIR/bin/pip"

if [ ! -f /proc/device-tree/model ] || ! grep -qi "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
    echo -e "${YELLOW}Warning: this does not look like a Raspberry Pi. Continuing anyway.${NC}"
fi

echo -e "${GREEN}[1/7] Installing system packages...${NC}"
apt-get update
apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    git \
    i2c-tools \
    libatlas-base-dev \
    libopenjp2-7 \
    libjpeg-dev \
    zlib1g-dev

# Bookworm uses libtiff6; older images use libtiff5
apt-get install -y libtiff6 2>/dev/null || apt-get install -y libtiff5 || true

echo -e "${GREEN}[2/7] Enabling I2C / SPI / UART for Enviro+ and PMS5003...${NC}"
if command -v raspi-config >/dev/null 2>&1; then
    raspi-config nonint do_i2c 0 || true
    raspi-config nonint do_spi 0 || true

    # Prefer Bookworm serial helpers; fall back to Bullseye-style
    if raspi-config nonint do_serial_hw 0 >/dev/null 2>&1; then
        raspi-config nonint do_serial_cons 1 || true
    else
        raspi-config nonint do_serial 2 || true
        # enable_uart via config if available
        if [ -f /boot/firmware/config.txt ]; then
            CONFIG_TXT=/boot/firmware/config.txt
        else
            CONFIG_TXT=/boot/config.txt
        fi
        if ! grep -q '^enable_uart=1' "$CONFIG_TXT" 2>/dev/null; then
            echo "enable_uart=1" >> "$CONFIG_TXT"
        fi
    fi
else
    echo -e "${YELLOW}raspi-config not found; enable I2C/SPI/UART manually if sensors fail.${NC}"
fi

if [ -f /boot/firmware/config.txt ]; then
    CONFIG_TXT=/boot/firmware/config.txt
elif [ -f /boot/config.txt ]; then
    CONFIG_TXT=/boot/config.txt
else
    CONFIG_TXT=""
fi

if [ -n "$CONFIG_TXT" ]; then
    # Move Bluetooth off the PL011 UART so PMS5003 can use /dev/serial0
    if ! grep -Eq '^(dtoverlay|dtoverlay\s*=\s*)(pi3-miniuart-bt|miniuart-bt)' "$CONFIG_TXT"; then
        echo "dtoverlay=pi3-miniuart-bt" >> "$CONFIG_TXT"
        echo -e "${GREEN}Added dtoverlay=pi3-miniuart-bt to $CONFIG_TXT${NC}"
        REBOOT_NEEDED=1
    fi
fi

echo -e "${GREEN}[3/7] Creating Python virtualenv...${NC}"
if [ ! -d "$VENV_DIR" ]; then
    sudo -u "$REAL_USER" python3 -m venv --system-site-packages "$VENV_DIR"
fi
sudo -u "$REAL_USER" "$PIP_BIN" install --upgrade pip
sudo -u "$REAL_USER" "$PIP_BIN" install -r "$SCRIPT_DIR/requirements.txt"

echo -e "${GREEN}[4/7] Initialising database...${NC}"
sudo -u "$REAL_USER" "$PYTHON_BIN" -c "from web_app import init_database; init_database()"

echo -e "${GREEN}[5/7] Installing systemd services...${NC}"
cat > /etc/systemd/system/enviro-dashboard.service << EOF
[Unit]
Description=Enviro+ Sensor Dashboard (Flask)
After=network.target

[Service]
Type=simple
User=$REAL_USER
WorkingDirectory=$SCRIPT_DIR
ExecStart=$PYTHON_BIN $SCRIPT_DIR/web_app.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/enviro-collector.service << EOF
[Unit]
Description=Enviro+ / PMS5003 Sensor Collector
After=network.target enviro-dashboard.service
Wants=enviro-dashboard.service

[Service]
Type=simple
User=$REAL_USER
WorkingDirectory=$SCRIPT_DIR
ExecStart=$PYTHON_BIN $SCRIPT_DIR/sensor_collector.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/enviro-dashboard-cleanup.service << EOF
[Unit]
Description=Enviro+ Dashboard Database Cleanup
After=network.target

[Service]
Type=oneshot
User=$REAL_USER
WorkingDirectory=$SCRIPT_DIR
ExecStart=$PYTHON_BIN $SCRIPT_DIR/cleanup_database.py
StandardOutput=journal
StandardError=journal
EOF

cp "$SCRIPT_DIR/enviro-dashboard-cleanup.timer" /etc/systemd/system/enviro-dashboard-cleanup.timer

systemctl daemon-reload
systemctl enable enviro-dashboard.service enviro-collector.service enviro-dashboard-cleanup.timer

echo -e "${GREEN}[6/7] Starting services...${NC}"
systemctl restart enviro-dashboard.service || systemctl start enviro-dashboard.service
# Collector may fail until UART overlay is active / hardware attached — still enable it
systemctl restart enviro-collector.service || systemctl start enviro-collector.service || true
systemctl start enviro-dashboard-cleanup.timer || true

echo -e "${GREEN}[7/7] Fixing ownership...${NC}"
chown -R "$REAL_USER:$REAL_USER" "$SCRIPT_DIR"

PI_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo ""
echo -e "${GREEN}Install complete.${NC}"
echo ""
echo "Dashboard:  http://localhost:5000"
if [ -n "$PI_IP" ]; then
    echo "On LAN:     http://$PI_IP:5000"
fi
echo ""
echo "Useful commands:"
echo "  sudo systemctl status enviro-dashboard enviro-collector"
echo "  sudo journalctl -u enviro-collector -f"
echo "  sudo journalctl -u enviro-dashboard -f"
echo ""
echo "Hardware checklist:"
echo "  - Enviro+ seated on the 40-pin header"
echo "  - PMS5003 connected with the Enviro+ cable (power off while plugging in)"
echo "  - After first install, reboot so UART/Bluetooth overlay applies"
echo ""

if [ "${REBOOT_NEEDED:-0}" = "1" ]; then
    echo -e "${YELLOW}A reboot is required for serial / Bluetooth overlay changes.${NC}"
    read -r -p "Reboot now? [y/N] " reply || true
    if [[ "${reply:-}" =~ ^[Yy]$ ]]; then
        reboot
    fi
fi
