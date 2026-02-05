from __future__ import annotations

import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from .ui import VMIUI


class VMICtl:
    def __init__(self, adb_target: str, project_root: Path) -> None:
        self.adb_target = adb_target
        self.project_root = project_root
        self.script_dir = Path(__file__).resolve().parent.parent
        self.ui = VMIUI(adb_target=adb_target)
        self.capture_data_dir = project_root / "data" / "captures"
        self.capture_data_dir.mkdir(parents=True, exist_ok=True)
        self.last_sensor_checkpoint_file = self.capture_data_dir / "last_sensor_checkpoint.txt"
        self.sensor_checkpoint_interval_minutes = 15

    def _adb_base(self) -> list[str]:
        cmd = ["adb"]
        if self.adb_target:
            cmd.extend(["-s", self.adb_target])
        return cmd

    def adb_run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            [*self._adb_base(), *args],
            check=False,
            capture_output=True,
            text=True,
        )
        if check and proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "adb command failed")
        return proc

    def adb_shell(self, *args: str, check: bool = True) -> str:
        return self.adb_run("shell", *args, check=check).stdout

    def screenshot(self, path: str | None = None) -> str:
        out = path or "/tmp/vmi_screen.png"
        self.ui.screenshot(out)
        print(f"Screenshot saved to {out}")
        return out

    def ui_dump(self) -> None:
        print(self.ui.ui_dump(), end="")

    def bt_on(self) -> None:
        print("Enabling Bluetooth...")
        self.adb_shell("svc", "bluetooth", "enable")
        time.sleep(3)

    def bt_off(self) -> None:
        print("Disabling Bluetooth...")
        self.adb_shell("svc", "bluetooth", "disable")
        time.sleep(2)

    def start_btsnoop_basic(self) -> None:
        print("Enabling Bluetooth HCI snoop log (basic mode)...")
        self.adb_shell("settings", "put", "secure", "bluetooth_hci_log", "1")
        self.bt_off()
        self.bt_on()
        print("BT snoop basic mode enabled.")

    def _parse_bounds(self, raw: str) -> tuple[int, int, int, int] | None:
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", raw)
        if not m:
            return None
        return tuple(map(int, m.groups()))

    def _dump_xml(self) -> str:
        return self.ui.ui_dump()

    def _tap_node_text(self, xml: str, text: str) -> bool:
        pat = re.compile(rf'text="{re.escape(text)}"[^>]*bounds="(\[[0-9,]+\]\[[0-9,]+\])"')
        m = pat.search(xml)
        if not m:
            return False
        bounds = self._parse_bounds(m.group(1))
        if not bounds:
            return False
        x1, y1, x2, y2 = bounds
        self.ui.tap((x1 + x2) // 2, (y1 + y2) // 2, delay=0.8)
        return True

    def btsnoop_enable_full(self) -> None:
        print("Enabling FULL Bluetooth HCI snoop logging...")
        self.adb_shell("am", "start", "-a", "android.settings.APPLICATION_DEVELOPMENT_SETTINGS")
        time.sleep(2)

        found = False
        for _ in range(14):
            xml = self._dump_xml()
            if "Enable Bluetooth HCI snoop log" in xml:
                found = True
                break
            self.ui.swipe(540, 1850, 540, 760)

        if not found:
            raise RuntimeError("Could not find 'Enable Bluetooth HCI snoop log' in Developer Options")

        xml = self._dump_xml()
        if not self._tap_node_text(xml, "Enable Bluetooth HCI snoop log"):
            raise RuntimeError("Could not tap 'Enable Bluetooth HCI snoop log'")

        xml = self._dump_xml()
        if not self._tap_node_text(xml, "Enabled"):
            raise RuntimeError("Could not select 'Enabled' option")

        self.bt_off()
        self.bt_on()
        self.adb_shell("input", "keyevent", "KEYCODE_HOME")
        print("BT snoop full mode enabled.")

    def pull_btsnoop(self, output_dir: Path | None = None) -> Path:
        outdir = output_dir or self.capture_data_dir
        outdir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        bugreport = outdir / f"bugreport_{ts}.zip"
        print("Pulling Bluetooth snoop logs via bugreport...")
        self.adb_run("bugreport", str(bugreport))

        log_path = outdir / f"btsnoop_{ts}.log"
        with zipfile.ZipFile(bugreport) as zf:
            names = zf.namelist()
            candidates = [
                "btsnooz_hci.log",
                "btsnoop_hci.log",
                "FS/data/misc/bluetooth/logs/btsnooz_hci.log",
                "FS/data/misc/bluetooth/logs/btsnoop_hci.log",
            ]
            picked = None
            for cand in candidates:
                for name in names:
                    if name.endswith(cand):
                        picked = name
                        break
                if picked:
                    break
            if not picked:
                raise RuntimeError("No btsnoop/btsnooz file found in bugreport")
            log_path.write_bytes(zf.read(picked))

        print(f"Logs saved to {log_path}")
        return log_path

    def launch(self) -> None:
        print("Launching VMI+ app...")
        self.adb_shell("am", "force-stop", "com.ventilairsec.ventilairsecinstallateur", check=False)
        time.sleep(1)
        self.adb_run(
            "shell",
            "monkey",
            "-p",
            "com.ventilairsec.ventilairsecinstallateur",
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        )
        time.sleep(3)
        self.screenshot("/tmp/vmi_01_home.png")

    def connect(self) -> None:
        print("=== Full VMI Connect Sequence ===")
        self.launch()
        print("Selecting VMCI...")
        self.ui.tap_vmci()
        time.sleep(5)
        self.screenshot("/tmp/vmi_02_scanning.png")

        print("Waiting for device discovery...")
        time.sleep(8)
        self.screenshot("/tmp/vmi_scan_result.png")

        print("Tapping PAIR...")
        paired = False
        for _ in range(3):
            self.ui.tap_pair()
            time.sleep(3)
            if self.ui.has_selector("dialog_firmware_prompt") or self.ui.screen_matches("home"):
                paired = True
                break
        if not paired:
            print("PAIR did not transition to expected state; continuing with dialog/home checks.")
        self.screenshot("/tmp/vmi_03_paired.png")

        print("Dismissing firmware dialog if visible...")
        self.ui.dismiss_dialog()
        time.sleep(1)
        self.screenshot("/tmp/vmi_04_main_menu.png")
        self.screenshot("/tmp/vmi_connected.png")
        print("=== Connected to VMI ===")

    def nav(self, name: str) -> None:
        mapping = {
            "menu": "menu",
            "config": "configuration",
            "maintenance": "maintenance",
            "sensors": "sensors",
            "available-info": "available-info",
            "equipment-life": "equipment-life",
            "measurements": "measurements",
            "measurements-full": "measurements-full",
            "diagnostic": "diagnostic",
            "special-modes": "special-modes",
            "special-modes-full": "special-modes-full",
            "time-slots": "time-slots",
            "simplified": "simplified",
        }
        self.ui.nav(mapping[name])

    def session_start(self, name: str) -> Path:
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = self.capture_data_dir / f"{name}_{ts}"
        path.mkdir(parents=True, exist_ok=True)
        (path / "session_start.txt").write_text(time.strftime("%Y-%m-%dT%H:%M:%S%z"), encoding="utf-8")
        (path / "checkpoint_count.txt").write_text("0", encoding="utf-8")
        print(path)
        return path

    def session_checkpoint(self, session_dir: Path) -> Path:
        count_file = session_dir / "checkpoint_count.txt"
        count = int(count_file.read_text(encoding="utf-8").strip() or "0") + 1
        count_file.write_text(str(count), encoding="utf-8")

        ts_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        ts_file = time.strftime("%H%M%S")
        shot = session_dir / f"checkpoint_{count}_{ts_file}.png"
        self.ui.screenshot(str(shot))

        with (session_dir / "checkpoints.txt").open("a", encoding="utf-8") as fh:
            fh.write(f"\n[checkpoint_{count}]\ntimestamp={ts_iso}\nscreenshot={shot.name}\n")

        print(shot)
        return shot

    def append_checkpoint_note(self, session_dir: Path, note: str) -> None:
        with (session_dir / "checkpoints.txt").open("a", encoding="utf-8") as fh:
            fh.write(f"note={note}\n")

    def session_end(self, session_dir: Path) -> Path:
        (session_dir / "session_end.txt").write_text(time.strftime("%Y-%m-%dT%H:%M:%S%z"), encoding="utf-8")
        bugreport = session_dir / "bugreport.zip"
        self.adb_run("bugreport", str(bugreport))

        log_path = session_dir / "btsnoop.log"
        with zipfile.ZipFile(bugreport) as zf:
            picked = None
            for name in zf.namelist():
                if name.endswith("btsnooz_hci.log") or name.endswith("btsnoop_hci.log"):
                    picked = name
                    break
            if picked:
                log_path.write_bytes(zf.read(picked))

        print(log_path)
        return log_path

    def should_collect_sensors(self) -> bool:
        if not self.last_sensor_checkpoint_file.exists():
            return True
        last_ts = int(self.last_sensor_checkpoint_file.read_text(encoding="utf-8").strip())
        now_ts = int(time.time())
        return (now_ts - last_ts) >= (self.sensor_checkpoint_interval_minutes * 60)

    def collect_sensors(self, force: bool = False) -> Path | None:
        if not force and not self.should_collect_sensors():
            print("Skipping sensor collection (use --force to override)")
            return None

        session_dir = self.session_start("sensor_capture")
        print(f"Collecting sensor evidence in session: {session_dir}", file=sys.stderr)

        try:
            self.nav("measurements-full")
            shot = self.session_checkpoint(session_dir)
            self.append_checkpoint_note(session_dir, "action=measurements-full")
            self.append_checkpoint_note(session_dir, f"screenshot={shot.name}")
        except Exception as exc:  # noqa: BLE001
            self.append_checkpoint_note(session_dir, f"action=measurements-full error={exc}")

        try:
            self.nav("sensors")
            shot = self.session_checkpoint(session_dir)
            self.append_checkpoint_note(session_dir, "action=sensors-screen")
            self.append_checkpoint_note(session_dir, f"screenshot={shot.name}")
        except Exception as exc:  # noqa: BLE001
            self.append_checkpoint_note(session_dir, f"action=sensors-screen error={exc}")

        for sensor in ("remote", "probe1", "probe2"):
            try:
                self.ui.tap_sensor(sensor)
                shot = self.session_checkpoint(session_dir)
                self.append_checkpoint_note(session_dir, f"action=sensor-select sensor={sensor}")
                self.append_checkpoint_note(session_dir, f"screenshot={shot.name}")
            except Exception as exc:  # noqa: BLE001
                self.append_checkpoint_note(
                    session_dir, f"action=sensor-select sensor={sensor} error={exc}"
                )

        btsnoop = self.session_end(session_dir)
        self.last_sensor_checkpoint_file.write_text(str(int(time.time())), encoding="utf-8")

        (session_dir / "summary.txt").write_text(
            "\n".join(
                [
                    "Sensor evidence capture complete.",
                    f"session_dir={session_dir}",
                    f"btsnoop_log={btsnoop}",
                    "Correlate checkpoints.txt timestamps with packet timestamps.",
                    "Record observed UI values in checkpoints.txt next to each checkpoint.",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        print(session_dir)
        return session_dir
