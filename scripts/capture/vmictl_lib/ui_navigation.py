"""Navigation mixin for VMI UI flows."""

from __future__ import annotations

import time

from .ui_core import Node


class VMIUINavigationMixin:
    def open_menu(self) -> None:
        self.ensure_home()
        xml = self.ui_dump()
        if self.screen_matches("menu", xml):
            return

        top_clickables: list[Node] = []
        for node in self.nodes(xml):
            if not node.clickable:
                continue
            x1, _y1, _x2, y2 = node.bounds
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
