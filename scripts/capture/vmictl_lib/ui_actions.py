"""General interaction mixin for VMI UI."""

from __future__ import annotations

import tempfile
import time

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

    def preheat_temp(self, temperature: str) -> str:
        """Set the preheat temperature on the Simplified Configuration screen.

        Args:
            temperature: Target temperature as string -- an integer 12-18 or
                "mini".

        Returns:
            Path to the confirmation screenshot.
        """
        # Validate argument.
        if temperature.lower() == "mini":
            target_desc = "Mini"
        else:
            try:
                temp_int = int(temperature)
            except ValueError:
                raise RuntimeError(
                    f"preheat-temp requires an integer 12-18 or 'mini', got: {temperature}"
                )
            if temp_int < 12 or temp_int > 18:
                raise RuntimeError(
                    f"preheat-temp value must be 12-18 or 'mini', got: {temp_int}"
                )
            target_desc = f"{temp_int} °C"

        # Navigate to the Simplified Configuration screen.
        self.nav("simplified")

        # Take a screenshot and find the preheat temperature badge by scanning
        # for purple pixels in the expected region.
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        self.screenshot(tmp_path)

        try:
            from PIL import Image  # noqa: PLC0415
        except ImportError:
            raise RuntimeError(
                "Pillow is required for preheat-temp (pip install Pillow)"
            )

        img = Image.open(tmp_path)
        pixels = img.load()

        # Scan for purple pixels (R>60, R<120, G<50, B>100) in the badge area.
        purple_xs: list[int] = []
        purple_ys: list[int] = []
        for y in range(1380, min(1440, img.height)):
            for x in range(200, min(400, img.width)):
                r, g, b = pixels[x, y][:3]
                if r > 60 and r < 120 and g < 50 and b > 100:
                    purple_xs.append(x)
                    purple_ys.append(y)

        if not purple_xs:
            raise RuntimeError(
                "preheat temperature badge not found -- expected purple pixels "
                "in y=1380-1440, x=200-400 on the Simplified Configuration screen"
            )

        # Tap the center of the purple badge to open the dropdown.
        badge_x = (min(purple_xs) + max(purple_xs)) // 2
        badge_y = (min(purple_ys) + max(purple_ys)) // 2
        self.tap(badge_x, badge_y, delay=1.0)

        # Dump UI to find the target temperature button.
        xml = self.ui_dump()
        target_node: Node | None = None
        for node in self.nodes(xml):
            if node.desc.strip() == target_desc:
                target_node = node
                break

        if target_node is None:
            raise RuntimeError(
                f"dropdown option '{target_desc}' not found in UI dump"
            )

        # Tap the target temperature button.
        x, y = target_node.center
        self.tap(x, y, delay=2.0)

        # Take a confirmation screenshot.
        confirm_path = tmp_path
        self.screenshot(confirm_path)
        return confirm_path

    def summer_limit(self, temperature: int) -> str:
        """Set the summer limit temperature on the Simplified Configuration screen.

        Args:
            temperature: Target temperature (22-37).

        Returns:
            Path to the confirmation screenshot.
        """
        if temperature < 22 or temperature > 37:
            raise RuntimeError(
                f"summer-limit temperature must be 22-37, got: {temperature}"
            )

        # Navigate to the Simplified Configuration screen.
        self.nav("simplified")

        # The summer section button contains the current temperature badge.
        # Find it by its content-desc which includes "DURING THE SUMMER" text.
        xml = self.ui_dump()
        summer_node = None
        for node in self.nodes(xml):
            if "DURING THE SUMMER" in node.desc:
                summer_node = node
                break

        if summer_node is None:
            raise RuntimeError(
                "summer limit section not found on Simplified Configuration screen"
            )

        # The temperature badge/dropdown trigger is at the bottom-right of the
        # summer section button.  Tap at ~75% horizontal, ~89% vertical within
        # the button bounds.
        x1, y1, x2, y2 = summer_node.bounds
        badge_x = x1 + int((x2 - x1) * 0.75)
        badge_y = y1 + int((y2 - y1) * 0.89)
        self.tap(badge_x, badge_y, delay=1.0)

        # The Flutter dropdown renders items as canvas elements that may not
        # appear in the UI hierarchy.  Try the UI dump first, fall back to
        # coordinate calculation.
        target_desc = f"{temperature} °C"
        xml = self.ui_dump()
        target_node = None
        for node in self.nodes(xml):
            if node.desc.strip() == target_desc:
                target_node = node
                break

        if target_node is not None:
            x, y = target_node.center
        else:
            # Coordinate fallback: the dropdown spans the right side of the
            # screen with items from 22°C at the top to 37°C at the bottom.
            # Empirically calibrated on 1080×2340 display:
            #   22°C center ≈ y=200, item spacing ≈ 140px, x ≈ 900.
            width, height = self.display_size()
            x = int(width * (900 / 1080))
            y_base = int(height * (200 / 2340))
            item_h = int(height * (140 / 2340))
            y = y_base + (temperature - 22) * item_h
        self.tap(x, y, delay=2.0)

        # Confirm the result.
        with __import__("tempfile").NamedTemporaryFile(
            suffix=".png", delete=False
        ) as tmp:
            confirm_path = tmp.name
        self.screenshot(confirm_path)
        return confirm_path

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
            visible_hours: list[int] = []
            for item in self.nodes(xml):
                desc = item.desc.strip().lower()
                if desc.endswith("h") and desc[:-1].isdigit():
                    visible_hours.append(int(desc[:-1]))

            if not visible_hours:
                self.swipe(540, 1900, 540, 780)
                continue

            if hour < min(visible_hours):
                # Scroll toward earlier hours.
                self.swipe(540, 900, 540, 1900)
            elif hour > max(visible_hours):
                # Scroll toward later hours.
                self.swipe(540, 1900, 540, 900)
            else:
                # In range but not found; nudge down the list and retry.
                self.swipe(540, 1900, 540, 900)
        raise RuntimeError(f"schedule hour row not found: {label}")
