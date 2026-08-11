#!/usr/bin/env python3
"""
Drive the Enviro+ 0.96" ST7735 LCD with Maker Faire-friendly screens.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("lcd_display")

# Match web dashboard bands
AQ_GOOD_MAX = 12.0
AQ_OK_MAX = 35.0


class EnviroDisplay:
    """Small colour LCD for live booth readings."""

    def __init__(self):
        self.enabled = False
        self.disp = None
        self.draw = None
        self.img = None
        self.width = 160
        self.height = 80
        self.font_sm = None
        self.font_md = None
        self.font_lg = None
        self.font_xl = None
        self._page = 0
        self._page_started = 0.0
        self._wave_until = 0.0
        self._last_frame = 0.0

        try:
            import st7735
            from fonts.ttf import RobotoMedium as UserFont
            from PIL import Image, ImageDraw, ImageFont

            self.disp = st7735.ST7735(
                port=0,
                cs=1,
                dc="GPIO9",
                backlight="GPIO12",
                rotation=270,
                spi_speed_hz=10_000_000,
            )
            self.disp.begin()
            self.width = self.disp.width
            self.height = self.disp.height
            self.img = Image.new("RGB", (self.width, self.height), color=(0, 0, 0))
            self.draw = ImageDraw.Draw(self.img)
            self.font_sm = ImageFont.truetype(UserFont, 11)
            self.font_md = ImageFont.truetype(UserFont, 13)
            self.font_lg = ImageFont.truetype(UserFont, 18)
            self.font_xl = ImageFont.truetype(UserFont, 28)
            self.enabled = True
            logger.info("Enviro+ LCD ready (%sx%s)", self.width, self.height)
            self.show_boot()
        except Exception as exc:  # noqa: BLE001
            logger.warning("LCD unavailable (%s) — continuing without display", exc)
            self.enabled = False

    def show_boot(self) -> None:
        if not self.enabled:
            return
        self._fill((16, 32, 51))
        self._text_center("Enviro+", self.font_lg, (255, 255, 255), y=22)
        self._text_center("Maker Faire", self.font_md, (200, 59, 101), y=48)
        self._flush()

    def notify_wave(self, hold_seconds: float = 1.6) -> None:
        import time

        self._wave_until = time.monotonic() + hold_seconds

    def update(self, reading: dict, waving: bool = False, wave_count: int = 0) -> None:
        """Refresh the LCD. Safe to call often; frames are rate-limited."""
        if not self.enabled:
            return

        import time

        now = time.monotonic()
        if waving:
            self.notify_wave()

        # ~8 fps max keeps SPI load reasonable on a Pi Zero
        if now - self._last_frame < 0.12 and now < self._wave_until:
            return
        if now - self._last_frame < 0.12 and now >= self._wave_until:
            # still throttle normal pages a bit less aggressively when not waving
            if now - self._last_frame < 0.35:
                return

        self._last_frame = now

        if now < self._wave_until:
            self._draw_wave(wave_count)
            self._flush()
            return

        # Rotate pages every 4 seconds
        if now - self._page_started >= 4.0:
            self._page = (self._page + 1) % 3
            self._page_started = now

        if self._page == 0:
            self._draw_air_quality(reading)
        elif self._page == 1:
            self._draw_weather(reading)
        else:
            self._draw_waves(wave_count, reading)

        self._flush()

    def _aq(self, pm25: Optional[float]):
        if pm25 is None:
            return "WAIT", (107, 106, 106), (30, 30, 30)
        if pm25 <= AQ_GOOD_MAX:
            return "GOOD", (255, 255, 255), (31, 173, 107)
        if pm25 <= AQ_OK_MAX:
            return "OK", (20, 20, 20), (224, 168, 0)
        return "POOR", (255, 255, 255), (226, 61, 61)

    def _draw_air_quality(self, reading: dict) -> None:
        pm25 = reading.get("pm25")
        label, fg, bg = self._aq(pm25)
        self._fill(bg)

        self._text(4, 2, "PM2.5", self.font_sm, fg)
        value = "--" if pm25 is None else f"{pm25:.1f}"
        self._text(4, 16, value, self.font_xl, fg)
        self._text(4, 50, label, self.font_lg, fg)

        pm10 = reading.get("pm10")
        right = f"PM10 {pm10:.0f}" if pm10 is not None else "PM10 --"
        self._text_right(self.width - 4, 52, right, self.font_sm, fg)

        clock = datetime.now().strftime("%H:%M")
        self._text_right(self.width - 4, 2, clock, self.font_sm, fg)

    def _draw_weather(self, reading: dict) -> None:
        self._fill((15, 37, 52))
        temp = reading.get("temperature")
        hum = reading.get("humidity")
        press = reading.get("pressure")
        light = reading.get("light")

        self._text(4, 3, "WEATHER", self.font_sm, (160, 190, 210))
        self._text(4, 18, f"{temp:.1f}C" if temp is not None else "--C", self.font_xl, (255, 255, 255))
        self._text(4, 52, f"RH {hum:.0f}%" if hum is not None else "RH --", self.font_md, (220, 230, 240))
        self._text_right(
            self.width - 4,
            52,
            f"{press:.0f}hPa" if press is not None else "--hPa",
            self.font_md,
            (220, 230, 240),
        )
        self._text_right(
            self.width - 4,
            3,
            f"{light:.0f}lx" if light is not None else "--lx",
            self.font_sm,
            (160, 190, 210),
        )

    def _draw_waves(self, wave_count: int, reading: dict) -> None:
        self._fill((48, 18, 40))
        self._text(4, 3, "HAND WAVES", self.font_sm, (255, 200, 140))
        self._text(4, 18, str(int(wave_count)), self.font_xl, (255, 255, 255))
        self._text(4, 52, "Wave over sensor", self.font_sm, (240, 210, 190))
        pm25 = reading.get("pm25")
        self._text_right(
            self.width - 4,
            52,
            f"PM {pm25:.0f}" if pm25 is not None else "PM --",
            self.font_sm,
            (240, 210, 190),
        )

    def _draw_wave(self, wave_count: int) -> None:
        self._fill((255, 210, 90))
        self._text_center("WAVE!", self.font_xl, (40, 25, 0), y=14)
        self._text_center(f"#{wave_count}", self.font_md, (60, 40, 0), y=52)

    def _fill(self, color) -> None:
        self.draw.rectangle((0, 0, self.width, self.height), color)

    def _text(self, x, y, text, font, fill) -> None:
        self.draw.text((x, y), text, font=font, fill=fill)

    def _text_right(self, x, y, text, font, fill) -> None:
        bbox = self.draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        self.draw.text((x - w, y), text, font=font, fill=fill)

    def _text_center(self, text, font, fill, y) -> None:
        bbox = self.draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        self.draw.text(((self.width - w) / 2, y), text, font=font, fill=fill)

    def _flush(self) -> None:
        try:
            self.disp.display(self.img)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LCD refresh failed: %s", exc)
