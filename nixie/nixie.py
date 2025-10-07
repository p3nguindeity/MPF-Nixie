from __future__ import annotations

import asyncio
import logging
from typing import Optional, Tuple, TYPE_CHECKING, Sequence, Any

from mpf.core.platform import SegmentDisplayPlatform
from mpf.platforms.interfaces.segment_display_platform_interface import (
    SegmentDisplayPlatformInterface,
    FlashingType,
)
from mpf.devices.segment_display.segment_display_text import ColoredSegmentDisplayText

try:
    # This lets us parse MPF color names/hex strings robustly
    from mpf.core.rgb_color import RGBColor  # type: ignore
except Exception:  # pragma: no cover
    RGBColor = None  # type: ignore

if TYPE_CHECKING:  # pragma: no cover
    from mpf.core.machine import MachineController

LOG = logging.getLogger("mpf.nixie")

def _log_info(msg: str, *args): 
    try: LOG.info(msg, *args)
    except Exception: pass

def _log_debug(msg: str, *args):
    try: LOG.debug(msg, *args)
    except Exception: pass

def _log_warn(msg: str, *args):
    try: LOG.warning(msg, *args)
    except Exception: pass


def _clampi(v: Any) -> int:
    try:
        i = int(v)
    except Exception:
        i = 0
    return 0 if i < 0 else 255 if i > 255 else i

def _resolve_color(x: Any) -> Tuple[int, int, int]:
    """Resolve a color from (r,g,b) or MPF color-name/hex string to 0-255 ints."""
    # Already a 3-tuple/list?
    if isinstance(x, (list, tuple)) and len(x) == 3:
        return (_clampi(x[0]), _clampi(x[1]), _clampi(x[2]))
    # String (named/hex)
    if isinstance(x, str):
        if RGBColor:
            try:
                c = RGBColor(x)  # supports 'red', '#ff00aa', 'orange', etc.
                r, g, b = c.rgb
                return (_clampi(r), _clampi(g), _clampi(b))
            except Exception:
                pass
        # naive hex fallback (e.g. '#RRGGBB' or 'RRGGBB')
        s = x.strip().lstrip("#")
        if len(s) == 6:
            try:
                r = int(s[0:2], 16)
                g = int(s[2:4], 16)
                b = int(s[4:6], 16)
                return (_clampi(r), _clampi(g), _clampi(b))
            except Exception:
                pass
    # Unknown → default red
    return (255, 0, 0)


# --------------------------
#  Single-tube display impl
# --------------------------
class NixieSegmentDisplay(SegmentDisplayPlatformInterface):
    """One-character segment display backed by the Nixie platform."""

    def __init__(self, number: int, platform: "NixiePlatform"):
        super().__init__(platform)
        self.number = int(number)
        self.platform: NixiePlatform = platform

    def set_text(
        self,
        text: ColoredSegmentDisplayText,
        flashing: FlashingType,
        flash_mask: str,
    ) -> None:
        del flashing, flash_mask

        # character
        s = text.convert_to_str().strip() if text else ""
        if not s:
            digit = 10  # blank/off
        else:
            try:
                digit = int(s[0])
            except (ValueError, TypeError):
                digit = 10

        # pick color for this (single) char
        rgb: Tuple[int, int, int] = self.platform.default_color
        if text:
            cols = text.get_colors()  # type: ignore[attr-defined]
            if cols:
                rgb = _resolve_color(cols[0])

        dim = self.platform.default_dim
        idx = self.number
        r, g, b = rgb
        self.platform.send_cmd(f"N,{idx},{digit},{r},{g},{b},{dim}\n")


# --------------------------
#  Multi-digit display impl
# --------------------------
class NixieMultiSegmentDisplay(SegmentDisplayPlatformInterface):
    """
    Multi-character display that maps onto consecutive tube indices.
    Sends per-character RGB if provided by MPF's ColoredSegmentDisplayText.
    """

    def __init__(self, base_number: int, size: int, platform: "NixiePlatform"):
        super().__init__(platform)
        self.base = int(base_number)
        self.size = int(size)
        self.platform: NixiePlatform = platform

    def set_text(self, text: ColoredSegmentDisplayText, flashing: FlashingType, flash_mask: str):
        del flashing, flash_mask
        s = text.convert_to_str() if text else ""
        s = (s or "").ljust(self.size)[:self.size]

        # colors list can be per character; fall back to default/first
        default_rgb: Tuple[int, int, int] = self.platform.default_color
        colors: Optional[Sequence[Any]] = None
        if text:
            try:
                colors = text.get_colors()  # type: ignore[attr-defined]
            except Exception:
                colors = None

        dim = self.platform.default_dim

        # Send rightmost->leftmost so rightmost index transmits first (works well with your chain)
        for i in range(self.size - 1, -1, -1):
            ch = s[i]
            try:
                digit = int(ch)
            except (ValueError, TypeError):
                digit = 10  # blank on non-digit

            # choose color for this position
            rgb = default_rgb
            if colors:
                # if there's a color for this char index, use it; else first color; else default
                rgb = _resolve_color(colors[i] if i < len(colors) else colors[0])

            r, g, b = rgb
            idx = self.base + i
            self.platform.send_cmd(f"N,{idx},{digit},{r},{g},{b},{dim}\n")


# --------------------------
#  Platform
# --------------------------
class NixiePlatform(SegmentDisplayPlatform):
    """Serial platform talking to the Arduino Nixie controller."""

    def __init__(self, machine: "MachineController"):
        super().__init__(machine)
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._cfg: dict = {}
        self.default_dim: int = 0
        self.default_color: Tuple[int, int, int] = (255, 0, 0)
        self._auto_mode: str = ""
        self._ignore_in_attract: bool = False
        self._in_attract: bool = False

    async def initialize(self) -> None:
        self._cfg = dict(self.machine.config.get("nixie", {}))
        port = self._cfg.get("port")
        baud = int(self._cfg.get("baud", 9600))
        if not port:
            raise AssertionError("nixie.port must be set to your Arduino's serial port")

        self.default_dim = int(self._cfg.get("default_dim", 0)) & 0xFF
        dc = self._cfg.get("default_color")
        if isinstance(dc, (list, tuple)) and len(dc) == 3:
            self.default_color = (_clampi(dc[0]), _clampi(dc[1]), _clampi(dc[2]))

        self._auto_mode = str(self._cfg.get("auto_attract", "")).strip().lower()
        self._ignore_in_attract = bool(self._cfg.get("ignore_updates_in_attract", False))

        _log_info("NixiePlatform: opening %s @ %d baud", port, baud)
        connector = self.machine.clock.open_serial_connection(url=port, baudrate=baud)
        self._reader, self._writer = await connector
        await asyncio.sleep(2.0)
        _log_info("NixiePlatform: serial ready (%s)", self.get_info_string())

        if self._auto_mode:
            self.machine.events.add_handler("mode_attract_started", self._on_attract_started)
            self.machine.events.add_handler("game_ended", self._on_attract_started)
            self.machine.events.add_handler("game_started", self._on_game_started)
            self.machine.events.add_handler("ball_started", self._on_game_started)
            _log_info("NixiePlatform: auto_attract=%s, ignore_updates_in_attract=%s",
                      self._auto_mode, self._ignore_in_attract)

    async def stop(self) -> None:
        if self._writer:
            try:
                self._writer.close()
                if hasattr(self._writer, "wait_closed"):
                    await self._writer.wait_closed()  # type: ignore[attr-defined]
            except Exception:
                pass
        self._reader = None
        self._writer = None

    def get_info_string(self) -> str:  # pragma: no cover
        port = self._cfg.get("port", "?")
        baud = self._cfg.get("baud", "?")
        return f"Serial {port} @ {baud} baud; default_dim={self.default_dim}; default_color={self.default_color}"

    async def configure_segment_display(self, number: str, display_size: int, platform_settings) -> SegmentDisplayPlatformInterface:
        del platform_settings
        if int(display_size) <= 1:
            return NixieSegmentDisplay(int(number), self)
        else:
            return NixieMultiSegmentDisplay(int(number), int(display_size), self)

    def send_cmd(self, cmd: str) -> None:
        if self._ignore_in_attract and self._in_attract and cmd.startswith("N,"):
            if self._cfg.get("debug", False):
                _log_debug("NIXIE DROP (in attract): %s", cmd.strip())
            return

        if self._cfg.get("debug", False):
            _log_debug("NIXIE TX: %s", cmd.strip())
        if not self._writer:
            _log_warn("NixiePlatform: write skipped (serial not ready)")
            return
        try:
            self._writer.write(cmd.encode("ascii", errors="ignore"))
        except Exception as e:
            _log_warn("NixiePlatform write failed: %s", e)

    # ---- Mode event handlers ----
    def _on_attract_started(self, **kwargs) -> None:
        self._in_attract = True
        if self._auto_mode == "a":
            self.send_cmd("A\n")

    def _on_game_started(self, **kwargs) -> None:
        self._in_attract = False
