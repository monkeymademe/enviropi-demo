#!/bin/bash
# Legacy helper — prefer ./install.sh for a full Enviro+ setup.
# This script only installs the Flask dashboard unit.

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Enviro+ Dashboard - Service Setup${NC}"
echo "=========================================="
echo -e "${YELLOW}Tip: use sudo ./install.sh for full Enviro+ + collector setup.${NC}"
echo ""

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="enviro-dashboard.service"
SERVICE_FILE="$SCRIPT_DIR/$SERVICE_NAME"
SYSTEMD_PATH="/etc/systemd/system/$SERVICE_NAME"

# Check if running as root (needed for systemd operations)
if [ "$EUID" -ne 0 ]; then 
    echo -e "${YELLOW}Note: This script needs sudo privileges to install the service.${NC}"
    echo "Please run with: sudo $0"
    exit 1
fi

# Check if service file exists
if [ ! -f "$SERVICE_FILE" ]; then
    echo -e "${RED}Error: Service file not found at $SERVICE_FILE${NC}"
    exit 1
fi

# Get the current user (who invoked sudo)
REAL_USER=${SUDO_USER:-$USER}
if [ "$REAL_USER" = "root" ]; then
    echo -e "${YELLOW}Warning: Running as root. Using 'pi' as default user.${NC}"
    REAL_USER="pi"
fi

# Get the working directory (where the script is)
WORKING_DIR="$SCRIPT_DIR"

# Check if web_app.py exists
if [ ! -f "$WORKING_DIR/web_app.py" ]; then
    echo -e "${RED}Error: web_app.py not found in $WORKING_DIR${NC}"
    exit 1
fi

# Check if Python3 is available
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: python3 not found. Please install Python 3.${NC}"
    exit 1
fi

PYTHON_PATH=$(which python3)

echo "Configuration:"
echo "  Service name: $SERVICE_NAME"
echo "  Working directory: $WORKING_DIR"
echo "  User: $REAL_USER"
echo "  Python: $PYTHON_PATH"
echo ""

# Stop existing service if running
if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    echo -e "${YELLOW}Stopping existing service...${NC}"
    systemctl stop "$SERVICE_NAME" || true
fi

# Create the service file with correct paths
echo -e "${GREEN}Creating systemd service file...${NC}"
cat > "$SYSTEMD_PATH" << EOF
[Unit]
Description=Enviro+ Sensor Dashboard (Flask)
After=network.target

[Service]
Type=simple
User=$REAL_USER
WorkingDirectory=$WORKING_DIR
ExecStart=$WORKING_DIR/.venv/bin/python $WORKING_DIR/web_app.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo -e "${GREEN}Service file created at $SYSTEMD_PATH${NC}"

# Reload systemd
echo -e "${GREEN}Reloading systemd daemon...${NC}"
systemctl daemon-reload

# Enable service to start at boot
echo -e "${GREEN}Enabling service to start at boot...${NC}"
systemctl enable "$SERVICE_NAME"

# Ask if user wants to start the service now
echo ""
read -p "Do you want to start the service now? (y/n) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Check if port 5000 is in use
    if lsof -Pi :5000 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
        echo -e "${YELLOW}Warning: Port 5000 is already in use.${NC}"
        echo "Stopping any existing web_app.py processes..."
        pkill -f web_app.py || true
        sleep 2
    fi
    
    echo -e "${GREEN}Starting service...${NC}"
    systemctl start "$SERVICE_NAME"
    
    sleep 2
    
    # Check if service started successfully
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        echo -e "${GREEN}✓ Service started successfully!${NC}"
        echo ""
        echo "Service Status:"
        systemctl status "$SERVICE_NAME" --no-pager -l || true
        echo ""
        echo -e "${GREEN}Dashboard should be available at:${NC}"
        echo "  http://localhost:5000"
        echo "  http://$(hostname -I | awk '{print $1}'):5000"
    else
        echo -e "${RED}✗ Service failed to start. Check logs with:${NC}"
        echo "  sudo journalctl -u $SERVICE_NAME -n 50"
    fi
else
    echo -e "${YELLOW}Service installed but not started. Start it with:${NC}"
    echo "  sudo systemctl start $SERVICE_NAME"
fi

echo ""
echo -e "${GREEN}Setup complete!${NC}"
echo ""
echo "Useful commands:"
echo "  Check status:  sudo systemctl status $SERVICE_NAME"
echo "  View logs:     sudo journalctl -u $SERVICE_NAME -f"
echo "  Start:         sudo systemctl start $SERVICE_NAME"
echo "  Stop:          sudo systemctl stop $SERVICE_NAME"
echo "  Restart:       sudo systemctl restart $SERVICE_NAME"
echo "  Disable:       sudo systemctl disable $SERVICE_NAME"


