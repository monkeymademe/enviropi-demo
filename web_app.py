"""
Flask web application for displaying Enviro+ sensor data.
Provides API endpoints and serves the web UI.
"""

from flask import Flask, render_template, jsonify, request
import sqlite3
from datetime import datetime
from pathlib import Path
import logging

app = Flask(__name__)
DB_PATH = "sensor_data.db"

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


def get_db_connection():
    """Get database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_latest_reading():
    """Get the most recent sensor reading."""
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
    """Get historical sensor data for the specified number of hours."""
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


def _ensure_column(cursor, column_name, column_type="REAL"):
    try:
        cursor.execute(f"ALTER TABLE sensor_readings ADD COLUMN {column_name} {column_type}")
    except sqlite3.OperationalError:
        pass


def init_database():
    """Initialize the SQLite database with sensor data table."""
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

    # Legacy columns from the Enviro Indoor version (kept if already present)
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
    """Store sensor data in the database."""
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
        logger.debug("Stored sensor data: %s", data)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Error storing sensor data: %s", exc)
        return False


def is_system_sleeping():
    """Treat missing recent samples as inactive (collector down)."""
    latest = get_latest_reading()
    if not latest:
        return True
    time_diff = datetime.now().timestamp() - latest["timestamp"]
    return time_diff > 300  # 5 minutes


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


def _normalize_incoming_reading(reading):
    """Map common aliases into the Enviro+ schema."""
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


@app.route("/")
def index():
    """Serve the main web interface."""
    return render_template("index.html")


@app.route("/api/data", methods=["POST"])
def api_receive_data():
    """Optional ingest endpoint (collector writes DB directly; useful for tests)."""
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
    """API endpoint for current sensor readings."""
    reading = get_latest_reading()
    is_sleeping = is_system_sleeping()

    if reading:
        return jsonify(
            {
                "success": True,
                "data": _reading_payload(reading),
                "sleeping": is_sleeping,
            }
        )

    return jsonify({"success": False, "data": None, "sleeping": True})


@app.route("/api/historical")
def api_historical():
    """API endpoint for historical sensor data."""
    hours = int(request.args.get("hours", 24))
    data = get_historical_data(hours)
    return jsonify({"success": True, "data": data, "hours": hours})


@app.route("/api/stats")
def api_stats():
    """API endpoint for sensor statistics."""
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
    logger.info("Starting Enviro+ web dashboard...")
    logger.info("Dashboard: http://<pi-ip>:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
