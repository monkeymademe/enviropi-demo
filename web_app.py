"""
Flask web application for displaying Enviro+ sensor data.
Maker Faire mode: air-quality light, today's trophies, day replay, live proximity.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, time as dt_time
from pathlib import Path

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

# Always use files next to this app, regardless of process cwd
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = str(BASE_DIR / "sensor_data.db")
LIVE_STATE_PATH = BASE_DIR / "live_state.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class HTTPMethodFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        if '"GET /' in message:
            return False
        return True


werkzeug_logger = logging.getLogger("werkzeug")
werkzeug_logger.addFilter(HTTPMethodFilter())

SENSOR_COLUMNS = (
    "temperature",
    "humidity",
    "pressure",
    "light",
    "oxidising",
    "reducing",
    "nh3",
    "pm1",
    "pm25",
    "pm10",
)

# PM2.5 bands (µg/m³) — walk-up friendly, roughly EPA-inspired
AQ_GOOD_MAX = 12.0
AQ_OK_MAX = 35.0


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_latest_reading():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM sensor_readings
        ORDER BY timestamp DESC
        LIMIT 1
        """
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_historical_data(hours=24):
    conn = get_db_connection()
    cursor = conn.cursor()
    cutoff_time = datetime.now().timestamp() - (hours * 3600)
    cursor.execute(
        f"""
        SELECT timestamp, {", ".join(SENSOR_COLUMNS)}
        FROM sensor_readings
        WHERE timestamp >= ?
        ORDER BY timestamp ASC
        """,
        (cutoff_time,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def today_start_timestamp() -> float:
    now = datetime.now()
    start = datetime.combine(now.date(), dt_time.min)
    return start.timestamp()


def get_today_data():
    conn = get_db_connection()
    cursor = conn.cursor()
    start = today_start_timestamp()
    cursor.execute(
        f"""
        SELECT timestamp, {", ".join(SENSOR_COLUMNS)}
        FROM sensor_readings
        WHERE timestamp >= ?
        ORDER BY timestamp ASC
        """,
        (start,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def _ensure_column(cursor, column_name, column_type="REAL"):
    try:
        cursor.execute(f"ALTER TABLE sensor_readings ADD COLUMN {column_name} {column_type}")
    except sqlite3.OperationalError:
        pass


def init_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS sensor_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            temperature REAL,
            humidity REAL,
            pressure REAL,
            light REAL,
            oxidising REAL,
            reducing REAL,
            nh3 REAL,
            pm1 REAL,
            pm25 REAL,
            pm10 REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    for column in SENSOR_COLUMNS:
        _ensure_column(cursor, column)
    for legacy in ("gas", "aqi", "color_temperature"):
        _ensure_column(cursor, legacy)
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_timestamp
        ON sensor_readings(timestamp)
        """
    )
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully")


def store_sensor_data(data):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            f"""
            INSERT INTO sensor_readings
            (timestamp, {", ".join(SENSOR_COLUMNS)})
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.get("timestamp"),
                data.get("temperature"),
                data.get("humidity"),
                data.get("pressure"),
                data.get("light"),
                data.get("oxidising"),
                data.get("reducing"),
                data.get("nh3"),
                data.get("pm1"),
                data.get("pm25"),
                data.get("pm10"),
            ),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Error storing sensor data: %s", exc)
        return False


def is_system_sleeping():
    latest = get_latest_reading()
    if not latest:
        return True
    return (datetime.now().timestamp() - latest["timestamp"]) > 300


def air_quality_from_pm25(pm25):
    if pm25 is None:
        return {
            "level": "unknown",
            "label": "Waiting",
            "color": "#6b6a6a",
            "message": "Warming up the particle sensor…",
        }
    if pm25 <= AQ_GOOD_MAX:
        return {
            "level": "good",
            "label": "Good",
            "color": "#2ecc71",
            "message": "Air looks clean — breathe easy!",
        }
    if pm25 <= AQ_OK_MAX:
        return {
            "level": "ok",
            "label": "OK",
            "color": "#f1c40f",
            "message": "A bit dusty — still fine for the booth.",
        }
    return {
        "level": "poor",
        "label": "Poor",
        "color": "#e74c3c",
        "message": "Particles are high — wave a fan or step back!",
    }


def _reading_payload(reading):
    return {
        "timestamp": reading["timestamp"],
        "temperature": reading.get("temperature"),
        "humidity": reading.get("humidity"),
        "pressure": reading.get("pressure"),
        "light": reading.get("light"),
        "oxidising": reading.get("oxidising"),
        "reducing": reading.get("reducing"),
        "nh3": reading.get("nh3"),
        "pm1": reading.get("pm1"),
        "pm25": reading.get("pm25"),
        "pm10": reading.get("pm10"),
    }


def read_live_state():
    if not LIVE_STATE_PATH.exists():
        return {}
    try:
        return json.loads(LIVE_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_live_state(state: dict) -> None:
    payload = dict(state)
    payload["updated_at"] = datetime.now().timestamp()
    LIVE_STATE_PATH.write_text(json.dumps(payload), encoding="utf-8")


def _normalize_incoming_reading(reading):
    reading = dict(reading)
    if "timestamp" not in reading:
        reading["timestamp"] = datetime.now().timestamp()
    elif isinstance(reading["timestamp"], str):
        try:
            dt = datetime.fromisoformat(reading["timestamp"].replace("Z", "+00:00"))
            reading["timestamp"] = dt.timestamp()
        except ValueError:
            reading["timestamp"] = datetime.now().timestamp()

    return {
        "timestamp": reading.get("timestamp", datetime.now().timestamp()),
        "temperature": reading.get("temperature") or reading.get("temp"),
        "humidity": reading.get("humidity") or reading.get("hum"),
        "pressure": reading.get("pressure") or reading.get("press"),
        "light": reading.get("light") or reading.get("lux") or reading.get("luminance"),
        "oxidising": reading.get("oxidising") or reading.get("oxidised") or reading.get("gas"),
        "reducing": reading.get("reducing") or reading.get("reduced"),
        "nh3": reading.get("nh3"),
        "pm1": reading.get("pm1") or reading.get("pm1_0"),
        "pm25": reading.get("pm25") or reading.get("pm2_5") or reading.get("pm2.5"),
        "pm10": reading.get("pm10") or reading.get("pm10_0"),
    }


def _fmt_time(ts):
    if ts is None:
        return None
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def build_today_trophies(rows):
    if not rows:
        return {
            "trophies": [],
            "stories": ["No readings yet today — leave the Pi running and come back soon!"],
            "counts": {"readings": 0},
        }

    def best(key, reverse=False):
        valid = [r for r in rows if r.get(key) is not None]
        if not valid:
            return None
        return sorted(valid, key=lambda r: r[key], reverse=reverse)[0]

    hottest = best("temperature", reverse=True)
    coolest = best("temperature", reverse=False)
    peak_pm = best("pm25", reverse=True)
    cleanest = best("pm25", reverse=False)
    brightest = best("light", reverse=True)
    darkest = best("light", reverse=False)

    trophies = []
    if peak_pm:
        trophies.append(
            {
                "id": "peak_pm",
                "title": "Dustiest moment",
                "value": f"{peak_pm['pm25']:.1f}",
                "unit": "µg/m³ PM2.5",
                "when": _fmt_time(peak_pm["timestamp"]),
                "emoji_label": "Peak particles",
            }
        )
    if cleanest:
        trophies.append(
            {
                "id": "cleanest",
                "title": "Cleanest air",
                "value": f"{cleanest['pm25']:.1f}",
                "unit": "µg/m³ PM2.5",
                "when": _fmt_time(cleanest["timestamp"]),
                "emoji_label": "Freshest",
            }
        )
    if hottest:
        trophies.append(
            {
                "id": "hottest",
                "title": "Hottest",
                "value": f"{hottest['temperature']:.1f}",
                "unit": "°C",
                "when": _fmt_time(hottest["timestamp"]),
                "emoji_label": "Warmest",
            }
        )
    if coolest:
        trophies.append(
            {
                "id": "coolest",
                "title": "Coolest",
                "value": f"{coolest['temperature']:.1f}",
                "unit": "°C",
                "when": _fmt_time(coolest["timestamp"]),
                "emoji_label": "Chillest",
            }
        )
    if brightest:
        trophies.append(
            {
                "id": "brightest",
                "title": "Brightest",
                "value": f"{brightest['light']:.0f}",
                "unit": "lux",
                "when": _fmt_time(brightest["timestamp"]),
                "emoji_label": "Most light",
            }
        )
    if darkest:
        trophies.append(
            {
                "id": "darkest",
                "title": "Darkest",
                "value": f"{darkest['light']:.0f}",
                "unit": "lux",
                "when": _fmt_time(darkest["timestamp"]),
                "emoji_label": "Dimmest",
            }
        )

    stories = []
    if peak_pm and cleanest and peak_pm["pm25"] != cleanest["pm25"]:
        stories.append(
            f"Particles peaked at {_fmt_time(peak_pm['timestamp'])} "
            f"({peak_pm['pm25']:.1f} µg/m³) and were cleanest at "
            f"{_fmt_time(cleanest['timestamp'])}."
        )
    if hottest:
        stories.append(
            f"Warmest reading today: {hottest['temperature']:.1f}°C at {_fmt_time(hottest['timestamp'])}."
        )
    if len(rows) >= 2:
        span_h = (rows[-1]["timestamp"] - rows[0]["timestamp"]) / 3600
        stories.append(f"Tracking {len(rows)} samples across {span_h:.1f} hours of Maker Faire air.")
    if not stories:
        stories.append("Collecting today's story… hang out by the booth!")

    return {
        "trophies": trophies,
        "stories": stories,
        "counts": {"readings": len(rows)},
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data", methods=["POST"])
def api_receive_data():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "Invalid JSON"}), 400

        readings = []
        if isinstance(data, list):
            readings = data
        elif isinstance(data, dict) and "readings" in data:
            readings_data = data["readings"]
            readings = [readings_data] if isinstance(readings_data, dict) else readings_data
        elif isinstance(data, dict):
            readings = [data]
        else:
            return jsonify({"success": False, "error": "Unexpected data format"}), 400

        stored_count = 0
        for reading in readings:
            if not isinstance(reading, dict):
                continue
            if store_sensor_data(_normalize_incoming_reading(reading)):
                stored_count += 1

        return jsonify({"success": True, "stored": stored_count, "total": len(readings)}), 200
    except Exception as exc:  # noqa: BLE001
        logger.error("Error processing incoming data: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/api/current")
def api_current():
    reading = get_latest_reading()
    live = read_live_state()
    is_sleeping = is_system_sleeping()

    if reading:
        payload = _reading_payload(reading)
        aq = air_quality_from_pm25(payload.get("pm25"))
        return jsonify(
            {
                "success": True,
                "data": payload,
                "air_quality": aq,
                "proximity": live.get("proximity"),
                "waving": bool(live.get("waving")),
                "wave_count": live.get("wave_count", 0),
                "sleeping": is_sleeping,
            }
        )

    return jsonify(
        {
            "success": False,
            "data": None,
            "air_quality": air_quality_from_pm25(None),
            "proximity": live.get("proximity"),
            "waving": bool(live.get("waving")),
            "wave_count": live.get("wave_count", 0),
            "sleeping": True,
        }
    )


@app.route("/api/live")
def api_live():
    """Fast booth endpoint: latest sensors + proximity hand-wave state."""
    reading = get_latest_reading()
    live = read_live_state()
    data = _reading_payload(reading) if reading else None
    # Prefer fresher values from live_state when present
    if live:
        if data is None:
            data = {}
        for key in SENSOR_COLUMNS:
            if live.get(key) is not None:
                data[key] = live[key]
        if live.get("timestamp"):
            data["timestamp"] = live["timestamp"]

    pm25 = data.get("pm25") if data else None
    return jsonify(
        {
            "success": data is not None,
            "data": data,
            "air_quality": air_quality_from_pm25(pm25),
            "proximity": live.get("proximity", 0),
            "waving": bool(live.get("waving")),
            "wave_count": int(live.get("wave_count", 0)),
            "updated_at": live.get("updated_at"),
            "sleeping": is_system_sleeping(),
        }
    )


@app.route("/api/today")
def api_today():
    """Today's readings + trophies + stories for Maker Faire replay."""
    rows = get_today_data()
    pack = build_today_trophies(rows)
    return jsonify(
        {
            "success": True,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "data": rows,
            "trophies": pack["trophies"],
            "stories": pack["stories"],
            "counts": pack["counts"],
            "replay_seconds": 10,
        }
    )


@app.route("/api/historical")
def api_historical():
    hours = int(request.args.get("hours", 24))
    data = get_historical_data(hours)
    return jsonify({"success": True, "data": data, "hours": hours})


@app.route("/api/stats")
def api_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    hours = int(request.args.get("hours", 24))
    cutoff_time = datetime.now().timestamp() - (hours * 3600)
    cursor.execute(
        """
        SELECT
            MIN(temperature) as min_temp,
            MAX(temperature) as max_temp,
            AVG(temperature) as avg_temp,
            MIN(humidity) as min_humidity,
            MAX(humidity) as max_humidity,
            AVG(humidity) as avg_humidity,
            MIN(pressure) as min_pressure,
            MAX(pressure) as max_pressure,
            AVG(pressure) as avg_pressure,
            MIN(light) as min_light,
            MAX(light) as max_light,
            AVG(light) as avg_light,
            MIN(oxidising) as min_oxidising,
            MAX(oxidising) as max_oxidising,
            AVG(oxidising) as avg_oxidising,
            MIN(reducing) as min_reducing,
            MAX(reducing) as max_reducing,
            AVG(reducing) as avg_reducing,
            MIN(nh3) as min_nh3,
            MAX(nh3) as max_nh3,
            AVG(nh3) as avg_nh3,
            MIN(pm1) as min_pm1,
            MAX(pm1) as max_pm1,
            AVG(pm1) as avg_pm1,
            MIN(pm25) as min_pm25,
            MAX(pm25) as max_pm25,
            AVG(pm25) as avg_pm25,
            MIN(pm10) as min_pm10,
            MAX(pm10) as max_pm10,
            AVG(pm10) as avg_pm10
        FROM sensor_readings
        WHERE timestamp >= ?
        """,
        (cutoff_time,),
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        return jsonify({"success": True, "stats": dict(row), "hours": hours})
    return jsonify({"success": False, "stats": None, "hours": hours})


if __name__ == "__main__":
    Path("templates").mkdir(exist_ok=True)
    init_database()
    logger.info("Starting Enviro+ Maker Faire dashboard...")
    logger.info("Database: %s", DB_PATH)
    logger.info("Dashboard: http://<pi-ip>:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
