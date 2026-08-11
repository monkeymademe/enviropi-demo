#!/bin/bash
# Raspberry Pi Kiosk Mode Setup Script for Enviro Indoor Dashboard
# This script sets up automatic kiosk mode to display the dashboard in fullscreen

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "Enviro+ Dashboard - Kiosk Mode Setup"
echo "=========================================="
echo ""

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Get the current user
CURRENT_USER=${SUDO_USER:-$USER}
if [ "$CURRENT_USER" = "root" ]; then
    CURRENT_USER="pi"
fi

# Check if running on Raspberry Pi
if [ ! -f /proc/device-tree/model ] || ! grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
    echo -e "${YELLOW}Warning: This doesn't appear to be a Raspberry Pi. Continue anyway? (y/n)${NC}"
    read -r response
    if [ "$response" != "y" ]; then
        exit 1
    fi
fi

# Check if web server service exists and is running
echo -e "${GREEN}Step 1: Checking web server...${NC}"
if systemctl is-active --quiet enviro-dashboard.service 2>/dev/null; then
    echo -e "${GREEN}✓ Web server is running${NC}"
    DASHBOARD_URL="http://localhost:5000"
elif systemctl list-unit-files | grep -q "enviro-dashboard.service"; then
    echo -e "${YELLOW}Web server service exists but is not running. Starting it...${NC}"
    sudo systemctl start enviro-dashboard.service
    sleep 3
    if systemctl is-active --quiet enviro-dashboard.service; then
        echo -e "${GREEN}✓ Web server started${NC}"
        DASHBOARD_URL="http://localhost:5000"
    else
        echo -e "${RED}✗ Failed to start web server. Please check: sudo systemctl status enviro-dashboard.service${NC}"
        exit 1
    fi
else
    echo -e "${YELLOW}Web server service not found.${NC}"
    echo "Do you want to set up the web server service first? (y/n)"
    read -r setup_server
    if [ "$setup_server" = "y" ]; then
        if [ -f "$SCRIPT_DIR/setup_service.sh" ]; then
            echo "Running setup_service.sh..."
            sudo "$SCRIPT_DIR/setup_service.sh"
            DASHBOARD_URL="http://localhost:5000"
        else
            echo -e "${RED}Error: setup_service.sh not found. Please set up the web server manually.${NC}"
            exit 1
        fi
    else
        echo -e "${YELLOW}Using http://localhost:5000 (assuming server will be running)${NC}"
        DASHBOARD_URL="http://localhost:5000"
    fi
fi
echo ""

# Install Chromium if not already installed
echo -e "${GREEN}Step 2: Installing Chromium...${NC}"
if ! command -v chromium &> /dev/null && ! command -v chromium-browser &> /dev/null; then
    sudo apt-get update
    sudo apt-get install -y chromium chromium-sandbox
else
    echo "Chromium is already installed."
fi

# Determine Chromium command name
if command -v chromium &> /dev/null; then
    CHROMIUM_CMD="chromium"
elif command -v chromium-browser &> /dev/null; then
    CHROMIUM_CMD="chromium-browser"
else
    echo -e "${RED}Error: Could not find Chromium installation${NC}"
    exit 1
fi

echo "Using Chromium command: $CHROMIUM_CMD"
echo "Dashboard URL: $DASHBOARD_URL"
echo ""

# Create systemd service file
echo -e "${GREEN}Step 3: Creating kiosk systemd service...${NC}"
SERVICE_FILE="/etc/systemd/system/enviro-kiosk.service"

sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Enviro Indoor Dashboard Kiosk Mode
After=graphical.target network.target enviro-dashboard.service
Wants=enviro-dashboard.service

[Service]
Type=simple
User=$CURRENT_USER
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/$CURRENT_USER/.Xauthority
ExecStartPre=/bin/sleep 5
ExecStart=$CHROMIUM_CMD --noerrdialogs --disable-infobars --kiosk --app=$DASHBOARD_URL
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical.target
EOF

echo "Service file created at $SERVICE_FILE"
echo ""

# Enable autologin (optional - uncomment if needed)
echo -e "${GREEN}Step 4: Setting up autologin...${NC}"
echo "Do you want to enable autologin for user '$CURRENT_USER'? (y/n)"
read -r autologin_response
if [ "$autologin_response" = "y" ]; then
    # For Debian Trixie with GDM3
    if [ -f /etc/gdm3/daemon.conf ]; then
        echo "Configuring GDM3 autologin..."
        sudo sed -i "s/#  AutomaticLoginEnable = true/  AutomaticLoginEnable = true/" /etc/gdm3/daemon.conf 2>/dev/null || true
        sudo sed -i "s/#  AutomaticLogin = user1/  AutomaticLogin = $CURRENT_USER/" /etc/gdm3/daemon.conf 2>/dev/null || true
        # Add if not present
        if ! grep -q "AutomaticLoginEnable = true" /etc/gdm3/daemon.conf; then
            echo "  AutomaticLoginEnable = true" | sudo tee -a /etc/gdm3/daemon.conf > /dev/null
            echo "  AutomaticLogin = $CURRENT_USER" | sudo tee -a /etc/gdm3/daemon.conf > /dev/null
        fi
    fi
    
    # For LightDM (alternative display manager)
    if [ -f /etc/lightdm/lightdm.conf ]; then
        echo "Configuring LightDM autologin..."
        sudo sed -i "s/#autologin-user=/autologin-user=$CURRENT_USER/" /etc/lightdm/lightdm.conf 2>/dev/null || true
        sudo sed -i "s/#autologin-user-timeout=0/autologin-user-timeout=0/" /etc/lightdm/lightdm.conf 2>/dev/null || true
    fi
    
    echo -e "${GREEN}Autologin configured.${NC}"
else
    echo "Skipping autologin setup. You'll need to log in manually."
fi
echo ""

# Disable screen blanking
echo -e "${GREEN}Step 5: Disabling screen blanking...${NC}"
if [ -f /etc/X11/xorg.conf ]; then
    echo -e "${YELLOW}xorg.conf already exists. Checking for blank time settings...${NC}"
    if ! grep -q "blank time" /etc/X11/xorg.conf; then
        echo "Adding screen blanking settings..."
        sudo tee -a /etc/X11/xorg.conf > /dev/null <<EOF

Section "ServerFlags"
    Option "blank time" "0"
    Option "standby time" "0"
    Option "suspend time" "0"
    Option "off time" "0"
EndSection
EOF
        echo -e "${GREEN}Screen blanking disabled.${NC}"
    else
        echo "Screen blanking settings already present."
    fi
else
    sudo tee /etc/X11/xorg.conf > /dev/null <<EOF
Section "ServerLayout"
    Identifier "ServerLayout0"
EndSection

Section "ServerFlags"
    Option "blank time" "0"
    Option "standby time" "0"
    Option "suspend time" "0"
    Option "off time" "0"
EndSection
EOF
    echo -e "${GREEN}Screen blanking disabled.${NC}"
fi
echo ""

# Disable screen saver for user
echo -e "${GREEN}Step 6: Disabling screensaver...${NC}"
sudo -u $CURRENT_USER mkdir -p /home/$CURRENT_USER/.config/systemd/user
sudo -u $CURRENT_USER tee /home/$CURRENT_USER/.config/systemd/user/xscreensaver-disable.service > /dev/null <<EOF
[Unit]
Description=Disable XScreenSaver
After=graphical-session.target

[Service]
Type=oneshot
ExecStart=/usr/bin/xset s off
ExecStart=/usr/bin/xset -dpms
ExecStart=/usr/bin/xset s noblank

[Install]
WantedBy=default.target
EOF

sudo -u $CURRENT_USER systemctl --user enable xscreensaver-disable.service 2>/dev/null || true
echo -e "${GREEN}Screensaver disabled.${NC}"
echo ""

# Enable and start the service
echo -e "${GREEN}Step 7: Enabling kiosk service...${NC}"
sudo systemctl daemon-reload
sudo systemctl enable enviro-kiosk.service
echo -e "${GREEN}Service enabled. It will start automatically on boot.${NC}"
echo ""

# Ask if user wants to start it now
echo "Do you want to start kiosk mode now? (y/n)"
read -r start_now
if [ "$start_now" = "y" ]; then
    echo "Starting kiosk service..."
    sudo systemctl start enviro-kiosk.service
    sleep 2
    
    if systemctl is-active --quiet enviro-kiosk.service; then
        echo -e "${GREEN}✓ Kiosk mode started!${NC}"
    else
        echo -e "${YELLOW}Service may need a graphical session. It will start automatically on next boot.${NC}"
    fi
    echo ""
    echo "To stop it, run: sudo systemctl stop enviro-kiosk.service"
    echo "To disable it, run: sudo systemctl disable enviro-kiosk.service"
else
    echo "Kiosk mode will start automatically on next boot."
fi

echo ""
echo "=========================================="
echo -e "${GREEN}Setup Complete!${NC}"
echo "=========================================="
echo ""
echo "Useful commands:"
echo "  Start kiosk:   sudo systemctl start enviro-kiosk.service"
echo "  Stop kiosk:    sudo systemctl stop enviro-kiosk.service"
echo "  Status:        sudo systemctl status enviro-kiosk.service"
echo "  View logs:     sudo journalctl -u enviro-kiosk.service -f"
echo "  Disable:       sudo systemctl disable enviro-kiosk.service"
echo ""
echo "To exit kiosk mode, press Alt+F4 or Ctrl+Alt+F1 to switch to terminal"
echo ""
