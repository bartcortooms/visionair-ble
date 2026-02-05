"""Core UI primitives for VMI automation."""

from __future__ import annotations

import re
import subprocess
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


class VMIUIBase:
    def __init__(self, adb_target: str = "", config_path: Path | None = None) -> None:
        if config_path is None:
            config_path = Path(__file__).with_name("ui_selectors.toml")
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
