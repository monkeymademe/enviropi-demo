# Enviro+ Sensor Dashboard (Raspberry Pi Zero)

Flask + SQLite dashboard for a **Raspberry Pi Zero / Zero 2 W** with a **Pimoroni Enviro+** board and **PMS5003** particulate sensor. Sensors are read on-device; the Pi serves the UI and stores history locally.

This replaces the earlier Enviro Indoor (Pico W → WiFi POST) setup. Same idea — web UI + database — with local I2C/UART data instead of a remote Pico.

## Features

- **Maker Faire mode**: giant PM2.5 traffic light, particle backdrop, today’s trophies, 10-second day replay, hand-wave detector (LTR-559 proximity)
- Live readings: temperature, humidity, pressure, light, oxidising / reducing / NH3, PM1 / PM2.5 / PM10
- Historical charts (1h → 7d) with gap handling
- SQLite storage with automatic 8-day retention cleanup
- systemd services for the web app and sensor collector

## Hardware

- Raspberry Pi Zero W or Zero 2 W (header recommended, e.g. Zero WH)
- [Pimoroni Enviro+](https://shop.pimoroni.com/products/enviro-plus)
- [PMS5003 particulate sensor + cable](https://shop.pimoroni.com/products/pms5003-particulate-matter-sensor-with-cable)
- MicroSD with Raspberry Pi OS (Bookworm Lite is fine)
- 5V USB power (PMS5003 draws noticeable current — use a solid supply)

**Power off the Pi before connecting or disconnecting the PMS5003.**

## Quick start (on the Pi)

```bash
# Clone from your git remote (example)
git clone <YOUR_REPO_URL> ~/envrio_demo
cd ~/envrio_demo

chmod +x install.sh
sudo ./install.sh
```

Reboot once after the first install so UART / Bluetooth overlay changes take effect:

```bash
sudo reboot
```

Then open:

- `http://<pi-ip>:5000` from another device on the LAN  
- or `http://localhost:5000` on the Pi

Find the IP with `hostname -I`.

## What the install script does

1. Installs apt packages (Python, I2C tools, image libs)
2. Enables **I2C**, **SPI**, and **UART**; disables the serial console
3. Adds `dtoverlay=pi3-miniuart-bt` so the PMS5003 can use the main UART
4. Creates a project venv at `.venv` and installs `requirements.txt`
5. Installs and enables:
   - `enviro-dashboard.service` — Flask UI on port 5000
   - `enviro-collector.service` — samples Enviro+ / PMS5003 every 60s into SQLite
   - `enviro-dashboard-cleanup.timer` — daily DB prune (keeps 8 days)

## Manual run (without systemd)

```bash
cd ~/envrio_demo
source .venv/bin/activate
python web_app.py          # terminal 1
python sensor_collector.py # terminal 2
```

UI-only testing without hardware:

```bash
source .venv/bin/activate
python simulate_data.py
python web_app.py
```

## Services

```bash
sudo systemctl status enviro-dashboard enviro-collector
sudo journalctl -u enviro-collector -f
sudo journalctl -u enviro-dashboard -f

sudo systemctl restart enviro-collector
sudo systemctl restart enviro-dashboard
```

## Project layout

```
envrio_demo/
├── install.sh                 # One-shot Pi setup
├── web_app.py                 # Flask API + UI
├── sensor_collector.py        # Enviro+ / PMS5003 → SQLite
├── cleanup_database.py        # Retention cleanup
├── simulate_data.py           # Fake data for UI testing
├── requirements.txt
├── templates/index.html       # Dashboard
├── enviro-dashboard.service   # Template (install.sh writes live unit)
├── enviro-dashboard-cleanup.* # Cleanup timer/service templates
└── README.md
```

## API

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/` | Maker Faire dashboard |
| `GET` | `/api/live` | Fast booth poll (sensors + proximity / waves) |
| `GET` | `/api/today` | Today’s series, trophies, stories, replay payload |
| `GET` | `/api/current` | Latest reading |
| `GET` | `/api/historical?hours=24` | Time series |
| `GET` | `/api/stats?hours=24` | Min / max / avg |
| `POST` | `/api/data` | Optional ingest (tests); collector writes the DB directly |

Wave your hand over the Enviro+ light/proximity sensor — the hero orb reacts and the wave counter ticks up.

Stored fields: `temperature`, `humidity`, `pressure`, `light`, `oxidising`, `reducing`, `nh3`, `pm1`, `pm25`, `pm10`.

Gas values are raw sensor resistances in ohms (UI shows kΩ). PM values are µg/m³.

## Sampling notes

- Collector interval: **60 seconds** (`SAMPLE_INTERVAL` in `sensor_collector.py`)
- Temperature uses CPU-heat compensation (same approach as Pimoroni examples)
- If the PMS5003 times out, the other sensors are still stored

## Troubleshooting

**No PM readings / collector UART errors**

- Confirm the PMS5003 cable is fully seated
- Confirm reboot after install (Bluetooth overlay)
- Check: `ls -l /dev/serial0` and `sudo journalctl -u enviro-collector -n 50`

**No temperature / I2C errors**

- `sudo i2cdetect -y 1` should show Enviro+ devices (typically `0x76` / `0x77` for BME280, etc.)
- Ensure Enviro+ is firmly on the header

**Dashboard empty**

- `sudo systemctl status enviro-collector` — must be active
- Or seed with `python simulate_data.py`

**Port 5000 in use**

```bash
sudo systemctl stop enviro-dashboard
sudo lsof -i :5000
```

## Optional kiosk mode

If you attach a display:

```bash
sudo ./kiosk-setup.sh
```

Headless Pi Zero use does not need this.

## Git workflow (dev machine → Pi)

1. Develop / commit on your Mac (Cursor)
2. Push to GitHub/GitLab
3. On the Pi: `git pull` then `sudo systemctl restart enviro-dashboard enviro-collector`

After dependency or install-script changes, re-run `sudo ./install.sh` (or update the venv with `source .venv/bin/activate && pip install -r requirements.txt`).

## References

- [Getting Started with Enviro+](https://learn.pimoroni.com/article/getting-started-with-enviro-plus)
- [enviroplus-python](https://github.com/pimoroni/enviroplus-python)
- [Outdoor AQ station (Pi Zero + Enviro+)](https://learn.pimoroni.com/article/enviro-plus-and-luftdaten-air-quality-station)

## License

Provided as-is for educational and personal use.
