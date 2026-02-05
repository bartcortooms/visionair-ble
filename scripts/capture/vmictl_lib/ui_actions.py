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

    def _dialog_button_tap(self, side: str, xml: str | None = None) -> bool:
        if xml is None:
            xml = self.ui_dump()
        card = None
        for node in self.nodes(xml):
            if "embedded software" in node.desc.lower() and "update" in node.desc.lower():
                card = node.bounds
                break
        if card is None:
            return False

        buttons: list[Node] = []
        for node in self.nodes(xml):
            if not node.clickable or node.cls != "android.widget.Button":
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

    def dismiss_dialog(self) -> None:
        if not self.has_selector("dialog_firmware_prompt"):
            return
        try:
            self.tap_by_selector("dialog_firmware_close", max_scrolls=0)
        except RuntimeError:
            self._dialog_button_tap("left")

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
