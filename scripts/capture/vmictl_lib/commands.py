from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .controller import VMICtl


@dataclass(frozen=True)
class CommandSpec:
    name: str
    help: str
    handler: Callable[[VMICtl, list[str]], int]


def _require_args(args: list[str], count: int, msg: str) -> None:
    if len(args) < count:
        raise RuntimeError(msg)


def _cmd_launch(ctl: VMICtl, args: list[str]) -> int:
    ctl.launch()
    return 0


def _cmd_stop(ctl: VMICtl, args: list[str]) -> int:
    ctl.stop()
    return 0


def _cmd_connect(ctl: VMICtl, args: list[str]) -> int:
    ctl.connect()
    return 0


def _cmd_vmci(ctl: VMICtl, args: list[str]) -> int:
    ctl.ui.tap_vmci()
    return 0


def _cmd_pair(ctl: VMICtl, args: list[str]) -> int:
    ctl.ui.tap_pair()
    return 0


def _cmd_dismiss(ctl: VMICtl, args: list[str]) -> int:
    ctl.ui.dismiss_dialog()
    return 0


def _cmd_firmware_update(ctl: VMICtl, args: list[str]) -> int:
    ctl.ui.accept_firmware_update()
    return 0


def _cmd_nav(name: str) -> Callable[[VMICtl, list[str]], int]:
    def handler(ctl: VMICtl, args: list[str]) -> int:
        ctl.nav(name)
        shot = ctl.capture_data_dir / f"vmi_{name.replace('-', '_')}.png"
        ctl.screenshot(str(shot))
        return 0

    return handler


def _cmd_sensor(which: str) -> Callable[[VMICtl, list[str]], int]:
    def handler(ctl: VMICtl, args: list[str]) -> int:
        ctl.ui.tap_sensor(which)
        return 0

    return handler


def _cmd_fan(index: int) -> Callable[[VMICtl, list[str]], int]:
    def handler(ctl: VMICtl, args: list[str]) -> int:
        ctl.ui.tap_home_tile(index)
        return 0

    return handler


def _cmd_airflow(ctl: VMICtl, args: list[str]) -> int:
    _require_args(args, 2, "airflow requires <from_pct> <to_pct>")
    ctl.ui.airflow_drag(int(args[0]), int(args[1]))
    return 0


def _cmd_airflow_min(ctl: VMICtl, args: list[str]) -> int:
    ctl.ui.airflow_tap("min")
    return 0


def _cmd_airflow_max(ctl: VMICtl, args: list[str]) -> int:
    ctl.ui.airflow_tap("max")
    return 0


def _cmd_holiday_toggle(ctl: VMICtl, args: list[str]) -> int:
    ctl.ui.holiday_toggle()
    return 0


def _cmd_holiday_days(ctl: VMICtl, args: list[str]) -> int:
    _require_args(args, 1, "holiday-days requires a numeric value")
    ctl.ui.holiday_days(args[0])
    return 0


def _cmd_holiday_state(ctl: VMICtl, args: list[str]) -> int:
    print(ctl.ui.holiday_state())
    return 0


def _cmd_schedule_tab(which: str) -> Callable[[VMICtl, list[str]], int]:
    def handler(ctl: VMICtl, args: list[str]) -> int:
        ctl.ui.schedule_tab(which)
        return 0

    return handler


def _cmd_schedule_hour(ctl: VMICtl, args: list[str]) -> int:
    _require_args(args, 1, "schedule-hour requires <0-23>")
    ctl.ui.schedule_hour(int(args[0]))
    return 0


def _cmd_screenshot(ctl: VMICtl, args: list[str]) -> int:
    ctl.screenshot(args[0] if args else None)
    return 0


def _cmd_back(ctl: VMICtl, args: list[str]) -> int:
    ctl.ui.back()
    return 0


def _cmd_scroll(ctl: VMICtl, args: list[str]) -> int:
    ctl.ui.swipe(540, 1850, 540, 760)
    return 0


def _cmd_ui(ctl: VMICtl, args: list[str]) -> int:
    ctl.ui_dump()
    return 0


def _cmd_resolution(ctl: VMICtl, args: list[str]) -> int:
    print("Detected resolution:", "x".join(map(str, ctl.ui.display_size())))
    return 0


def _cmd_bt_on(ctl: VMICtl, args: list[str]) -> int:
    ctl.bt_on()
    return 0


def _cmd_bt_off(ctl: VMICtl, args: list[str]) -> int:
    ctl.bt_off()
    return 0


def _cmd_btstart(ctl: VMICtl, args: list[str]) -> int:
    ctl.start_btsnoop_basic()
    return 0


def _cmd_btsnoop_enable(ctl: VMICtl, args: list[str]) -> int:
    ctl.btsnoop_enable_full()
    return 0


def _cmd_btpull(ctl: VMICtl, args: list[str]) -> int:
    ctl.pull_btsnoop()
    return 0


def _cmd_session_start(ctl: VMICtl, args: list[str]) -> int:
    name = args[0] if args else "session"
    ctl.session_start(name)
    return 0


def _cmd_session_checkpoint(ctl: VMICtl, args: list[str]) -> int:
    _require_args(args, 1, "session-checkpoint requires <session_dir>")
    ctl.session_checkpoint(Path(args[0]))
    return 0


def _cmd_session_end(ctl: VMICtl, args: list[str]) -> int:
    _require_args(args, 1, "session-end requires <session_dir>")
    ctl.session_end(Path(args[0]))
    return 0


def _cmd_collect_sensors(ctl: VMICtl, args: list[str]) -> int:
    force = bool(args and args[0] == "--force")
    ctl.collect_sensors(force=force)
    return 0


def _cmd_should_collect(ctl: VMICtl, args: list[str]) -> int:
    print("Yes, should collect" if ctl.should_collect_sensors() else "No, too recent")
    return 0


def get_command_specs() -> dict[str, CommandSpec]:
    navs = [
        "menu",
        "config",
        "simplified",
        "maintenance",
        "sensors",
        "available-info",
        "equipment-life",
        "measurements",
        "measurements-full",
        "diagnostic",
        "special-modes",
        "special-modes-full",
        "time-slots",
    ]

    specs: list[CommandSpec] = [
        CommandSpec("launch", "Launch VMI+ app", _cmd_launch),
        CommandSpec("stop", "Force-stop VMI+ app", _cmd_stop),
        CommandSpec("connect", "Full connect sequence", _cmd_connect),
        CommandSpec("vmci", "Tap VMCI device type", _cmd_vmci),
        CommandSpec("pair", "Tap PAIR", _cmd_pair),
        CommandSpec("dismiss", "Dismiss firmware dialog if visible", _cmd_dismiss),
        CommandSpec("firmware-update", "Accept firmware update if dialog visible", _cmd_firmware_update),
        CommandSpec("sensor-probe1", "Select Probe 1", _cmd_sensor("probe1")),
        CommandSpec("sensor-probe2", "Select Probe 2", _cmd_sensor("probe2")),
        CommandSpec("sensor-remote", "Select Remote sensor", _cmd_sensor("remote")),
        CommandSpec("fan-min", "Tap fan low tile", _cmd_fan(0)),
        CommandSpec("fan-mid", "Tap fan medium tile", _cmd_fan(1)),
        CommandSpec("fan-max", "Tap fan high tile", _cmd_fan(2)),
        CommandSpec("boost", "Tap boost tile", _cmd_fan(3)),
        CommandSpec("airflow-min", "Set simplified airflow to minimum", _cmd_airflow_min),
        CommandSpec("airflow-max", "Set simplified airflow to maximum", _cmd_airflow_max),
        CommandSpec("airflow", "Drag simplified airflow slider", _cmd_airflow),
        CommandSpec("holiday-toggle", "Toggle holiday mode", _cmd_holiday_toggle),
        CommandSpec("holiday-days", "Set holiday days", _cmd_holiday_days),
        CommandSpec("holiday-state", "Read holiday state", _cmd_holiday_state),
        CommandSpec("schedule-edition", "Time slots: switch to EDITION tab", _cmd_schedule_tab("edition")),
        CommandSpec("schedule-planning", "Time slots: switch to PLANNING tab", _cmd_schedule_tab("planning")),
        CommandSpec("schedule-hour", "Time slots: tap hour row (0-23)", _cmd_schedule_hour),
        CommandSpec("screenshot", "Capture screenshot", _cmd_screenshot),
        CommandSpec("back", "Press Android back", _cmd_back),
        CommandSpec("scroll", "Scroll down", _cmd_scroll),
        CommandSpec("ui", "Dump UI XML", _cmd_ui),
        CommandSpec("resolution", "Show display resolution", _cmd_resolution),
        CommandSpec("bt-on", "Enable Bluetooth", _cmd_bt_on),
        CommandSpec("bt-off", "Disable Bluetooth", _cmd_bt_off),
        CommandSpec("btstart", "Enable basic BT snoop", _cmd_btstart),
        CommandSpec("btsnoop-enable", "Enable full BT snoop via Developer Options", _cmd_btsnoop_enable),
        CommandSpec("btpull", "Pull btsnoop log via bugreport", _cmd_btpull),
        CommandSpec("session-start", "Start capture session", _cmd_session_start),
        CommandSpec("session-checkpoint", "Take checkpoint screenshot", _cmd_session_checkpoint),
        CommandSpec("session-end", "End session and pull btsnoop", _cmd_session_end),
        CommandSpec("collect-sensors", "Collect timestamped sensor evidence session", _cmd_collect_sensors),
        CommandSpec("should-collect", "Check collection interval", _cmd_should_collect),
    ]

    for nav in navs:
        specs.append(CommandSpec(nav, f"Navigate to {nav}", _cmd_nav(nav)))

    return {s.name: s for s in specs}
