#!/usr/bin/env python3
"""
Collect readings from Enviro+ (BME280, LTR-559, MICS6814) and PMS5003,
then store them in the shared SQLite database used by the web dashboard.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

from web_app import DB_PATH, init_database, store_sensor_data

# How often to sample sensors (seconds)
SAMPLE_INTERVAL = 60

# BME280 sits above the Pi SoC; compensate like Pimoroni examples
TEMP_COMPENSATION_FACTOR = 2.25

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("sensor_collector")


def get_cpu_temperature() -> float:
    """Read Pi CPU temperature in °C."""
    with open("/sys/class/thermal/thermal_zone0/temp", "r", encoding="utf-8") as handle:
        return int(handle.read().strip()) / 1000.0


def compensate_temperature(raw_temp: float, cpu_temps: list[float]) -> float:
    """Reduce CPU heat bias on the BME280 reading."""
    cpu_temp = get_cpu_temperature()
    cpu_temps.append(cpu_temp)
    del cpu_temps[0]
    avg_cpu_temp = sum(cpu_temps) / len(cpu_temps)
    return raw_temp - ((avg_cpu_temp - raw_temp) / TEMP_COMPENSATION_FACTOR)


def init_sensors():
    """Initialise Enviro+ and PMS5003 hardware interfaces."""
    from bme280 import BME280
    from enviroplus import gas
    from pms5003 import PMS5003

    try:
        from ltr559 import LTR559

        ltr559 = LTR559()
    except ImportError:
        import ltr559 as ltr559_module

        ltr559 = ltr559_module

    bme280 = BME280()
    # Discard first few BME280 readings while the sensor settles
    for _ in range(3):
        bme280.get_temperature()
        time.sleep(0.2)

    pms5003 = PMS5003()
    logger.info("Enviro+ and PMS5003 initialised")
    return bme280, ltr559, gas, pms5003


def read_sensors(bme280, ltr559, gas, pms5003, cpu_temps: list[float]) -> dict:
    """Take one full sensor snapshot."""
    from pms5003 import ReadTimeoutError as PmsReadTimeoutError

    temperature = compensate_temperature(bme280.get_temperature(), cpu_temps)
    humidity = bme280.get_humidity()
    pressure = bme280.get_pressure()

    proximity = ltr559.get_proximity()
    light = ltr559.get_lux() if proximity < 10 else 1.0

    gas_data = gas.read_all()
    oxidising = float(gas_data.oxidising)
    reducing = float(gas_data.reducing)
    nh3 = float(gas_data.nh3)

    pm1 = pm25 = pm10 = None
    try:
        particles = pms5003.read()
        pm1 = float(particles.pm_ug_per_m3(1.0))
        pm25 = float(particles.pm_ug_per_m3(2.5))
        pm10 = float(particles.pm_ug_per_m3(10))
    except PmsReadTimeoutError:
        logger.warning("PMS5003 read timed out; storing reading without PM values")
    except Exception as exc:  # noqa: BLE001 - keep collecting other sensors
        logger.warning("PMS5003 read failed (%s); storing reading without PM values", exc)

    return {
        "timestamp": datetime.now().timestamp(),
        "temperature": round(temperature, 2),
        "humidity": round(humidity, 2),
        "pressure": round(pressure, 2),
        "light": round(light, 1),
        "oxidising": round(oxidising, 1),
        "reducing": round(reducing, 1),
        "nh3": round(nh3, 1),
        "pm1": pm1,
        "pm25": pm25,
        "pm10": pm10,
    }


def main() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    init_database()

    logger.info("Starting Enviro+ sensor collector (interval=%ss)", SAMPLE_INTERVAL)
    bme280, ltr559, gas, pms5003 = init_sensors()
    cpu_temps = [get_cpu_temperature()] * 5

    while True:
        started = time.monotonic()
        try:
            reading = read_sensors(bme280, ltr559, gas, pms5003, cpu_temps)
            if store_sensor_data(reading):
                logger.info(
                    "Stored reading: T=%.1f°C RH=%.1f%% P=%.1fhPa lux=%.0f "
                    "ox=%.0f red=%.0f nh3=%.0f PM2.5=%s",
                    reading["temperature"],
                    reading["humidity"],
                    reading["pressure"],
                    reading["light"],
                    reading["oxidising"],
                    reading["reducing"],
                    reading["nh3"],
                    reading["pm25"],
                )
            else:
                logger.error("Failed to store sensor reading")
        except Exception as exc:  # noqa: BLE001 - never exit the loop on a bad sample
            logger.exception("Sensor collection error: %s", exc)

        elapsed = time.monotonic() - started
        time.sleep(max(1.0, SAMPLE_INTERVAL - elapsed))


if __name__ == "__main__":
    main()
