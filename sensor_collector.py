#!/usr/bin/env python3
"""
Collect readings from Enviro+ (BME280, LTR-559, MICS6814) and PMS5003.

Full samples go to SQLite on SAMPLE_INTERVAL.
Proximity is polled faster and published to live_state.json for Maker Faire hand-waves.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

from web_app import DB_PATH, init_database, store_sensor_data, write_live_state

# Full sensor sample cadence
SAMPLE_INTERVAL = 30
# Proximity / live UI refresh
PROXIMITY_POLL = 0.25
WAVE_THRESHOLD = 1500

TEMP_COMPENSATION_FACTOR = 2.25

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("sensor_collector")


def get_cpu_temperature() -> float:
    with open("/sys/class/thermal/thermal_zone0/temp", "r", encoding="utf-8") as handle:
        return int(handle.read().strip()) / 1000.0


def compensate_temperature(raw_temp: float, cpu_temps: list[float]) -> float:
    cpu_temp = get_cpu_temperature()
    cpu_temps.append(cpu_temp)
    del cpu_temps[0]
    avg_cpu_temp = sum(cpu_temps) / len(cpu_temps)
    return raw_temp - ((avg_cpu_temp - raw_temp) / TEMP_COMPENSATION_FACTOR)


def init_sensors():
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
    for _ in range(3):
        bme280.get_temperature()
        time.sleep(0.2)

    pms5003 = PMS5003()
    logger.info("Enviro+ and PMS5003 initialised")
    return bme280, ltr559, gas, pms5003


def read_full_sample(bme280, ltr559, gas, pms5003, cpu_temps: list[float]) -> dict:
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
    except Exception as exc:  # noqa: BLE001
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
        "proximity": proximity,
    }


def main() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    init_database()

    logger.info(
        "Starting Enviro+ collector (sample=%ss, proximity=%.2fs)",
        SAMPLE_INTERVAL,
        PROXIMITY_POLL,
    )
    bme280, ltr559, gas, pms5003 = init_sensors()
    cpu_temps = [get_cpu_temperature()] * 5

    latest = {
        "timestamp": datetime.now().timestamp(),
        "temperature": None,
        "humidity": None,
        "pressure": None,
        "light": None,
        "oxidising": None,
        "reducing": None,
        "nh3": None,
        "pm1": None,
        "pm25": None,
        "pm10": None,
    }
    wave_count = 0
    was_waving = False
    next_sample = time.monotonic()

    while True:
        loop_start = time.monotonic()
        try:
            proximity = float(ltr559.get_proximity())
            waving = proximity >= WAVE_THRESHOLD
            if waving and not was_waving:
                wave_count += 1
                logger.info("Hand wave detected! (count=%s, proximity=%.0f)", wave_count, proximity)
            was_waving = waving

            if loop_start >= next_sample:
                reading = read_full_sample(bme280, ltr559, gas, pms5003, cpu_temps)
                proximity = float(reading.pop("proximity", proximity))
                waving = proximity >= WAVE_THRESHOLD
                latest = {k: reading.get(k) for k in latest}
                if store_sensor_data(reading):
                    logger.info(
                        "Stored reading: T=%.1f°C RH=%.1f%% PM2.5=%s",
                        reading["temperature"],
                        reading["humidity"],
                        reading["pm25"],
                    )
                next_sample = loop_start + SAMPLE_INTERVAL

            write_live_state(
                {
                    **latest,
                    "proximity": proximity,
                    "waving": waving,
                    "wave_count": wave_count,
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Sensor collection error: %s", exc)

        elapsed = time.monotonic() - loop_start
        time.sleep(max(0.05, PROXIMITY_POLL - elapsed))


if __name__ == "__main__":
    main()
