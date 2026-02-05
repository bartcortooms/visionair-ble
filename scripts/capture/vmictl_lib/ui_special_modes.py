"""Special modes (Holiday) interaction mixin."""

from __future__ import annotations

import time

class VMIUISpecialModesMixin:
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
        state: str | None = None
        try:
            state = self.holiday_state(xml)
        except RuntimeError:
            # If state cannot be read reliably, continue with field lookup below.
            state = None
        if state == "OFF":
            raise RuntimeError(
                "holiday days field is only available when Holiday mode is ON "
                "(run holiday-toggle first)"
            )
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
