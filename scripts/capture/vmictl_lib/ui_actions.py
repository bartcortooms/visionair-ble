"""General interaction mixin for VMI UI."""

from __future__ import annotations

from .ui_core import Node


class VMIUIActionsMixin:
    def tap_vmci(self) -> None:
        self.tap_by_selector("connect_vmci", max_scrolls=0)

    def tap_pair(self) -> None:
        try:
            self.tap_by_selector("connect_pair", max_scrolls=1)
            return
        except RuntimeError:
            # Fallback for UI dumps where the PAIR label is not exposed.
            width, height = self.display_size()
            self.tap(int(width * 0.82), int(height * 0.165), delay=1.0)

    def _find_dialog_card(self, xml: str | None = None) -> tuple[tuple[int, int, int, int], str] | None:
        """Find the firmware update dialog card bounds and return (bounds, xml)."""
        if xml is None:
            xml = self.ui_dump()
        for node in self.nodes(xml):
            desc = node.desc.lower()
            if "embedded software" in desc or "update" in desc or "firmware" in desc:
                return node.bounds, xml
        return None

    def _dialog_button_tap(self, side: str, xml: str | None = None) -> bool:
        result = self._find_dialog_card(xml)
        if result is None:
            return False
        card, xml = result

        # Try standard Button widgets first.
        buttons: list[Node] = []
        for node in self.nodes(xml):
            if not node.clickable or node.cls != "android.widget.Button":
                continue
            if self._within(card, node.bounds):
                buttons.append(node)

        # Fall back to any clickable node within the dialog card.
        if not buttons:
            for node in self.nodes(xml):
                if not node.clickable:
                    continue
                if self._within(card, node.bounds):
                    buttons.append(node)

        if not buttons:
            return False
        buttons.sort(key=lambda n: n.bounds[0])
        target = buttons[0] if side == "left" else buttons[-1]
        x, y = target.center
        self.tap(x, y, delay=1.0)
        return True

    def _dialog_close_coordinate_fallback(self) -> None:
        """Tap the firmware dialog Close/X button by coordinate.

        The X button is typically near the top-center of the dialog.
        Known bounds on 1080x2340: [356,1159][503,1306], center (430,1233).
        Scale relative to detected display resolution.
        """
        width, height = self.display_size()
        x = int(width * 0.398)
        y = int(height * 0.527)
        self.tap(x, y, delay=1.0)

    def dismiss_dialog(self) -> None:
        if not self.has_selector("dialog_firmware_prompt"):
            return
        try:
            self.tap_by_selector("dialog_firmware_close", max_scrolls=0)
            return
        except RuntimeError:
            pass
        if self._dialog_button_tap("left"):
            return
        self._dialog_close_coordinate_fallback()

    def accept_firmware_update(self) -> None:
        if not self.has_selector("dialog_firmware_prompt"):
            return
        try:
            self.tap_by_selector("dialog_firmware_validate", max_scrolls=0)
        except RuntimeError:
            self._dialog_button_tap("right")

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

    def schedule_tab(self, tab: str) -> None:
        self.nav("time-slots")
        selector = {
            "edition": "schedule_tab_edition",
            "planning": "schedule_tab_planning",
        }.get(tab)
        if not selector:
            raise RuntimeError(f"invalid schedule tab: {tab}")
        self.tap_by_selector(selector, max_scrolls=0)

    def schedule_hour(self, hour: int, *, max_scrolls: int = 4) -> None:
        if hour < 0 or hour > 23:
            raise RuntimeError("schedule hour must be between 0 and 23")

        self.nav("time-slots")
        label = f"{hour}h"
        for _ in range(max_scrolls + 1):
            xml = self.ui_dump()
            node = self._find_by_labels([label], xml, require_clickable=True)
            if not node:
                node = self._find_by_labels([label], xml, require_clickable=False)
            if node:
                x, y = node.center
                self.tap(x, y)
                return
            self.swipe(540, 1900, 540, 780)
        raise RuntimeError(f"schedule hour row not found: {label}")
