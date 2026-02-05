#!/usr/bin/env python3
"""VMI UI controller (ADB + UiAutomator).

This module provides robust, selector-driven UI actions for the VMI app.
Adjust behavior for app updates in `vmi_ui_selectors.toml` instead of code.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


@dataclass(frozen=True)
class Node:
    text: str
    desc: str
    cls: str
    clickable: bool
    bounds: tuple[int, int, int, int]

    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return ((x1 + x2) // 2, (y1 + y2) // 2)


class ADBClient:
    def __init__(self, target: str = "") -> None:
        self.target = target

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        cmd = ["adb"]
        if self.target:
            cmd.extend(["-s", self.target])
        cmd.extend(args)
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if check and proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "adb command failed")
        return proc

    def shell(self, *args: str, check: bool = True) -> str:
        return self.run("shell", *args, check=check).stdout

    def run_bytes(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
        cmd = ["adb"]
        if self.target:
            cmd.extend(["-s", self.target])
        cmd.extend(args)
        proc = subprocess.run(cmd, capture_output=True, check=False)
        if check and proc.returncode != 0:
            stderr = proc.stderr.decode(errors="replace").strip()
            raise RuntimeError(stderr or "adb command failed")
        return proc


class SelectorConfig:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._raw = tomllib.loads(path.read_text(encoding="utf-8"))

    def screen_requirements(self, name: str) -> list[str]:
        screens = self._raw.get("screens", {})
        item = screens.get(name, {})
        return list(item.get("requires_desc", []))

    def label_selector(self, name: str) -> list[str]:
        selectors = self._raw.get("selectors", {})
        item = selectors.get(name, {})
        return list(item.get("labels", []))

    def tap_priority(self, name: str) -> list[str]:
        selectors = self._raw.get("selectors", {})
        item = selectors.get(name, {})
        return list(item.get("priority", []))


class VMIUI:
    def __init__(self, adb_target: str = "", config_path: Path | None = None) -> None:
        if config_path is None:
            config_path = Path(__file__).with_name("vmi_ui_selectors.toml")
        self.adb = ADBClient(adb_target)
        self.config = SelectorConfig(config_path)

    def wake(self) -> None:
        self.adb.shell("input", "keyevent", "KEYCODE_WAKEUP", check=False)
        time.sleep(0.2)

    def tap(self, x: int, y: int, *, delay: float = 1.0) -> None:
        self.wake()
        self.adb.shell("input", "tap", str(x), str(y))
        time.sleep(delay)

    def back(self, *, delay: float = 0.7) -> None:
        self.adb.shell("input", "keyevent", "KEYCODE_BACK")
        time.sleep(delay)

    def screenshot(self, path: str) -> None:
        self.wake()
        proc = self.adb.run_bytes("exec-out", "screencap", "-p")
        Path(path).write_bytes(proc.stdout)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 260) -> None:
        self.wake()
        self.adb.shell(
            "input",
            "swipe",
            str(x1),
            str(y1),
            str(x2),
            str(y2),
            str(duration_ms),
        )
        time.sleep(0.8)

    def ui_dump(self) -> str:
        self.adb.shell("uiautomator", "dump", check=False)
        return self.adb.shell("cat", "/sdcard/window_dump.xml")

    def display_size(self) -> tuple[int, int]:
        out = self.adb.shell("wm", "size", check=False)
        m = re.search(r"(\\d+)x(\\d+)", out)
        if not m:
            return (1080, 2340)
        return (int(m.group(1)), int(m.group(2)))

    @staticmethod
    def _parse_bounds(raw: str) -> tuple[int, int, int, int] | None:
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", raw)
        if not m:
            return None
        return tuple(map(int, m.groups()))

    @staticmethod
    def _norm(value: str) -> str:
        return " ".join(value.lower().split())

    def nodes(self, xml: str | None = None) -> list[Node]:
        if xml is None:
            xml = self.ui_dump()
        root = ET.fromstring(xml)
        out: list[Node] = []
        for item in root.iter():
            bounds = self._parse_bounds(item.attrib.get("bounds", ""))
            if not bounds:
                continue
            out.append(
                Node(
                    text=item.attrib.get("text", ""),
                    desc=item.attrib.get("content-desc", ""),
                    cls=item.attrib.get("class", ""),
                    clickable=item.attrib.get("clickable", "false") == "true",
                    bounds=bounds,
                )
            )
        return out

    def screen_matches(self, screen_name: str, xml: str | None = None) -> bool:
        req = self.config.screen_requirements(screen_name)
        if not req:
            raise RuntimeError(f"unknown screen fingerprint: {screen_name}")
        if xml is None:
            xml = self.ui_dump()
        hay = self._norm("\n".join(n.desc for n in self.nodes(xml)))
        return all(self._norm(x) in hay for x in req)

    def ensure_home(self, max_attempts: int = 8) -> None:
        for _ in range(max_attempts):
            xml = self.ui_dump()
            if self.screen_matches("home", xml):
                return
            self.back()
        raise RuntimeError("could not reach home screen")

    def _find_by_labels(
        self,
        labels: list[str],
        xml: str | None = None,
        *,
        require_clickable: bool,
    ) -> Node | None:
        if xml is None:
            xml = self.ui_dump()
        needles = [self._norm(x) for x in labels]
        for node in self.nodes(xml):
            if require_clickable and not node.clickable:
                continue
            haystacks = [self._norm(node.desc), self._norm(node.text)]
            for hay in haystacks:
                if not hay:
                    continue
                if any(needle in hay for needle in needles):
                    return node
        return None

    def tap_by_selector(self, selector_name: str, *, max_scrolls: int = 0) -> None:
        labels = self.config.label_selector(selector_name)
        if not labels:
            raise RuntimeError(f"unknown selector: {selector_name}")
        for _ in range(max_scrolls + 1):
            xml = self.ui_dump()
            node = self._find_by_labels(labels, xml, require_clickable=True)
            if not node:
                # Some Flutter views expose labels but mark leaf nodes non-clickable;
                # tapping the labeled bounds still works.
                node = self._find_by_labels(labels, xml, require_clickable=False)
            if node:
                x, y = node.center
                self.tap(x, y)
                return
            self.swipe(540, 1900, 540, 780)
        raise RuntimeError(f"selector not found: {selector_name}")

    def has_selector(self, selector_name: str) -> bool:
        labels = self.config.label_selector(selector_name)
        if not labels:
            raise RuntimeError(f"unknown selector: {selector_name}")
        xml = self.ui_dump()
        return self._find_by_labels(labels, xml, require_clickable=False) is not None

    def open_menu(self) -> None:
        self.ensure_home()
        xml = self.ui_dump()
        if self.screen_matches("menu", xml):
            return

        top_clickables: list[Node] = []
        for node in self.nodes(xml):
            if not node.clickable:
                continue
            x1, y1, x2, y2 = node.bounds
            if y2 > 260:
                continue
            if x1 < 700:
                continue
            top_clickables.append(node)

        if not top_clickables:
            raise RuntimeError("unable to locate top-right actions on home screen")

        top_clickables.sort(key=lambda n: n.bounds[0])
        menu_btn = top_clickables[0]
        x, y = menu_btn.center
        self.tap(x, y)

        xml = self.ui_dump()
        if not self.screen_matches("menu", xml):
            raise RuntimeError("failed to open main menu")

    def nav(self, destination: str) -> None:
        if destination == "menu":
            self.open_menu()
            return

        if destination == "configuration":
            self.open_menu()
            self.tap_by_selector("menu_configuration")
            self._expect("configuration")
            return

        if destination == "maintenance":
            self.open_menu()
            self.tap_by_selector("menu_maintenance")
            self._expect("maintenance")
            return

        if destination == "sensors":
            self.open_menu()
            self.tap_by_selector("menu_sensors")
            self._expect("sensor_management")
            return

        if destination == "available-info":
            self.nav("maintenance")
            self.tap_by_selector("maintenance_available_info")
            self._expect("available_info")
            return

        if destination == "equipment-life":
            self.nav("available-info")
            self.tap_by_selector("available_info_equipment_life", max_scrolls=1)
            self._expect("equipment_life")
            return

        if destination == "measurements":
            self.nav("available-info")
            self.tap_by_selector("available_info_measurements", max_scrolls=1)
            self._expect("measurements")
            return

        if destination == "diagnostic":
            self.nav("available-info")
            self.tap_by_selector("available_info_diagnostic", max_scrolls=1)
            self._expect("diagnostic")
            return

        if destination == "special-modes":
            self.nav("configuration")
            self.tap_by_selector("configuration_special_modes", max_scrolls=2)
            self._expect("special_modes")
            return

        if destination == "simplified":
            self.nav("configuration")
            self.tap_by_selector("configuration_simplified", max_scrolls=1)
            self._expect("simplified")
            return

        if destination == "time-slots":
            self.nav("configuration")
            self.tap_by_selector("configuration_time_slots", max_scrolls=2)
            self._expect("time_slots")
            return

        if destination == "measurements-full":
            self.nav("measurements")
            return

        if destination == "special-modes-full":
            self.nav("special-modes")
            return

        raise RuntimeError(f"unknown destination: {destination}")

    def _expect(self, screen_name: str, timeout_s: float = 6.0) -> None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.screen_matches(screen_name):
                return
            time.sleep(0.3)
        raise RuntimeError(f"expected screen not reached: {screen_name}")

    def tap_vmci(self) -> None:
        self.tap_by_selector("connect_vmci", max_scrolls=0)

    def tap_pair(self) -> None:
        self.tap_by_selector("connect_pair", max_scrolls=1)

    def dismiss_dialog(self) -> None:
        if not self.has_selector("dialog_firmware_prompt"):
            return
        self.tap_by_selector("dialog_firmware_close", max_scrolls=0)

    def accept_firmware_update(self) -> None:
        if not self.has_selector("dialog_firmware_prompt"):
            return
        self.tap_by_selector("dialog_firmware_validate", max_scrolls=0)

    def tap_sensor(self, which: str) -> None:
        key = {
            "probe1": "sensor_probe1",
            "probe2": "sensor_probe2",
            "remote": "sensor_remote",
        }[which]
        self.tap_by_selector(key)

    def tap_home_tile(self, index: int) -> None:
        self.ensure_home()
        xml = self.ui_dump()
        candidates: list[Node] = []
        for node in self.nodes(xml):
            if not node.clickable:
                continue
            if node.desc or node.text:
                continue
            x1, y1, x2, y2 = node.bounds
            if y1 < 230 or y2 > 1200:
                continue
            if (x2 - x1) < 200 or (y2 - y1) < 160:
                continue
            candidates.append(node)

        candidates.sort(key=lambda n: (n.bounds[1], n.bounds[0]))
        if len(candidates) <= index:
            raise RuntimeError(
                f"home tile index {index} not available; candidates={len(candidates)}"
            )
        x, y = candidates[index].center
        self.tap(x, y)

    def airflow_tap(self, side: str) -> None:
        self.nav("simplified")
        width, height = self.display_size()
        y = int(height * 0.335)
        x_left = int(width * 0.15)
        x_right = int(width * 0.85)
        if side == "min":
            self.tap(x_left, y)
            return
        if side == "max":
            self.tap(x_right, y)
            return
        raise RuntimeError(f"invalid airflow side: {side}")

    def airflow_drag(self, from_pct: int, to_pct: int) -> None:
        self.nav("simplified")
        width, height = self.display_size()
        y = int(height * 0.335)
        x_left = int(width * 0.15)
        x_right = int(width * 0.85)
        span = x_right - x_left
        from_x = x_left + int(span * (from_pct / 100.0))
        to_x = x_left + int(span * (to_pct / 100.0))
        self.swipe(from_x, y, to_x, y, duration_ms=450)

    def holiday_card_bounds(self, xml: str | None = None) -> tuple[int, int, int, int]:
        if xml is None:
            xml = self.ui_dump()
        for node in self.nodes(xml):
            if "HOLIDAY MODE" in node.desc:
                return node.bounds
        raise RuntimeError("holiday card not found")

    @staticmethod
    def _within(parent: tuple[int, int, int, int], child: tuple[int, int, int, int]) -> bool:
        px1, py1, px2, py2 = parent
        cx = (child[0] + child[2]) // 2
        cy = (child[1] + child[3]) // 2
        return px1 <= cx <= px2 and py1 <= cy <= py2

    def holiday_state(self, xml: str | None = None) -> str:
        if xml is None:
            xml = self.ui_dump()
        card = self.holiday_card_bounds(xml)
        for node in self.nodes(xml):
            if not node.clickable:
                continue
            if node.desc not in ("ON", "OFF"):
                continue
            if self._within(card, node.bounds):
                return node.desc
        raise RuntimeError("holiday toggle state not found")

    def holiday_toggle(self) -> None:
        xml = self.ui_dump()
        card = self.holiday_card_bounds(xml)
        for node in self.nodes(xml):
            if not node.clickable:
                continue
            if node.desc not in ("ON", "OFF"):
                continue
            if self._within(card, node.bounds):
                x, y = node.center
                self.tap(x, y, delay=1.5)
                return
        raise RuntimeError("holiday toggle control not found")

    def holiday_days(self, days: str) -> None:
        xml = self.ui_dump()
        card = self.holiday_card_bounds(xml)
        for node in self.nodes(xml):
            if node.cls != "android.widget.EditText":
                continue
            if not self._within(card, node.bounds):
                continue
            x, y = node.center
            self.tap(x, y, delay=0.4)
            self.adb.shell("input", "keyevent", "KEYCODE_MOVE_END")
            self.adb.shell("input", "keyevent", "--longpress", "KEYCODE_DEL")
            self.adb.shell("input", "text", str(days))
            self.adb.shell("input", "keyevent", "KEYCODE_ENTER")
            time.sleep(0.8)
            return
        raise RuntimeError("holiday days field not found")


def build_ui() -> VMIUI:
    target = os.environ.get("VMI_ADB_TARGET", "")
    return VMIUI(adb_target=target)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(
            "Usage: vmi_ui.py <command> [args]\n"
            "Commands:\n"
            "  ensure-home\n"
            "  open-menu\n"
            "  nav <destination>\n"
            "  vmci | pair | dismiss | firmware-update\n"
            "  sensor-probe1 | sensor-probe2 | sensor-remote\n"
            "  fan-min | fan-mid | fan-max | boost\n"
            "  airflow-min | airflow-max | airflow <from_pct> <to_pct>\n"
            "  holiday-toggle | holiday-days <n> | holiday-state\n"
            "\n"
            "Destinations:\n"
            "  menu configuration maintenance sensors available-info\n"
            "  equipment-life measurements measurements-full diagnostic\n"
            "  special-modes special-modes-full time-slots simplified"
        )
        return 0

    ui = build_ui()
    cmd = argv[0]

    try:
        if cmd == "ensure-home":
            ui.ensure_home()
        elif cmd == "open-menu":
            ui.open_menu()
        elif cmd == "nav":
            if len(argv) < 2:
                raise RuntimeError("nav requires a destination")
            ui.nav(argv[1])
        elif cmd == "vmci":
            ui.tap_vmci()
        elif cmd == "pair":
            ui.tap_pair()
        elif cmd == "dismiss":
            ui.dismiss_dialog()
        elif cmd == "firmware-update":
            ui.accept_firmware_update()
        elif cmd == "sensor-probe1":
            ui.tap_sensor("probe1")
        elif cmd == "sensor-probe2":
            ui.tap_sensor("probe2")
        elif cmd == "sensor-remote":
            ui.tap_sensor("remote")
        elif cmd == "fan-min":
            ui.tap_home_tile(0)
        elif cmd == "fan-mid":
            ui.tap_home_tile(1)
        elif cmd == "fan-max":
            ui.tap_home_tile(2)
        elif cmd == "boost":
            ui.tap_home_tile(3)
        elif cmd == "airflow-min":
            ui.airflow_tap("min")
        elif cmd == "airflow-max":
            ui.airflow_tap("max")
        elif cmd == "airflow":
            if len(argv) < 3:
                raise RuntimeError("airflow requires from/to percentages")
            ui.airflow_drag(int(argv[1]), int(argv[2]))
        elif cmd == "holiday-toggle":
            ui.holiday_toggle()
        elif cmd == "holiday-days":
            if len(argv) < 2:
                raise RuntimeError("holiday-days requires a numeric value")
            ui.holiday_days(argv[1])
        elif cmd == "holiday-state":
            print(ui.holiday_state())
        else:
            raise RuntimeError(f"unknown command: {cmd}")
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
