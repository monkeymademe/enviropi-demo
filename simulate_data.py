#!/usr/bin/env python3
"""
Simulate 24 hours of Enviro+ style sensor data with gaps for dashboard testing.
"""

import math
import random
import sqlite3
from datetime import datetime, timedelta

from web_app import DB_PATH, init_database

DB_PATH = DB_PATH


def generate_sensor_reading(timestamp, base_temp=23.0, base_humidity=45.0, base_pressure=1006.0):
    """Generate realistic Enviro+ readings with some variation."""
    hour = datetime.fromtimestamp(timestamp).hour

    temp_variation = 2 * math.sin((hour - 6) * math.pi / 12)
    temperature = base_temp + temp_variation + random.uniform(-0.5, 0.5)

    humidity = base_humidity - (temp_variation * 2) + random.uniform(-2, 2)
    humidity = max(30, min(60, humidity))

    pressure = base_pressure + random.uniform(-2, 2)

    if 6 <= hour <= 20:
        light = random.uniform(200, 800)
    else:
        light = random.uniform(0, 50)

    oxidising = random.uniform(15000, 45000)
    reducing = random.uniform(80000, 250000)
    nh3 = random.uniform(100000, 400000)

    # Higher PM during daytime traffic hours
    if 7 <= hour <= 9 or 16 <= hour <= 19:
        pm_base = random.uniform(12, 35)
    else:
        pm_base = random.uniform(3, 15)

    pm25 = pm_base + random.uniform(-2, 2)
    pm1 = max(0, pm25 * random.uniform(0.55, 0.75))
    pm10 = pm25 * random.uniform(1.2, 1.8)

    return {
        "timestamp": timestamp,
        "temperature": round(temperature, 2),
        "humidity": round(humidity, 2),
        "pressure": round(pressure, 2),
        "light": round(light, 0),
        "oxidising": round(oxidising, 1),
        "reducing": round(reducing, 1),
        "nh3": round(nh3, 1),
        "pm1": round(pm1, 1),
        "pm25": round(max(0, pm25), 1),
        "pm10": round(pm10, 1),
    }


def simulate_data():
    """Generate 24 hours of data with multiple gaps."""
    init_database()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    now = datetime.now()
    start_time = now - timedelta(hours=24)

    gap1_start = start_time + timedelta(hours=8)
    gap1_end = gap1_start + timedelta(hours=8)
    gap2_start = start_time + timedelta(hours=2)
    gap2_end = gap2_start + timedelta(hours=1)
    gap3_start = start_time + timedelta(hours=20)
    gap3_end = gap3_start + timedelta(minutes=40)

    print("Generating simulated Enviro+ sensor data...")
    print(f"Start time: {start_time}")
    print(f"Gap 1 (8 hours): {gap1_start} to {gap1_end}")
    print(f"Gap 2 (1 hour): {gap2_start} to {gap2_end}")
    print(f"Gap 3 (40 minutes): {gap3_start} to {gap3_end}")
    print(f"End time: {now}")
    print()

    print("Clearing existing data in time range...")
    cursor.execute(
        """
        DELETE FROM sensor_readings
        WHERE timestamp >= ? AND timestamp <= ?
        """,
        (start_time.timestamp(), now.timestamp()),
    )
    print(f"✓ Deleted {cursor.rowcount} existing readings in time range")
    print()

    current_time = start_time
    reading_count = 0
    skipped_count = 0

    while current_time <= now:
        if (
            (gap1_start <= current_time < gap1_end)
            or (gap2_start <= current_time < gap2_end)
            or (gap3_start <= current_time < gap3_end)
        ):
            skipped_count += 1
            current_time += timedelta(minutes=1)
            continue

        reading = generate_sensor_reading(current_time.timestamp())
        cursor.execute(
            """
            INSERT INTO sensor_readings
            (timestamp, temperature, humidity, pressure, light,
             oxidising, reducing, nh3, pm1, pm25, pm10)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reading["timestamp"],
                reading["temperature"],
                reading["humidity"],
                reading["pressure"],
                reading["light"],
                reading["oxidising"],
                reading["reducing"],
                reading["nh3"],
                reading["pm1"],
                reading["pm25"],
                reading["pm10"],
            ),
        )
        reading_count += 1
        current_time += timedelta(minutes=1)

    conn.commit()
    conn.close()

    print(f"✓ Generated {reading_count} sensor readings")
    print(f"✓ Skipped {skipped_count} readings during gap periods")
    print()
    print("Data simulation complete! Refresh your dashboard to see the results.")


if __name__ == "__main__":
    simulate_data()
