#!/usr/bin/env python3
"""Preflight checks + issue-specific capture checklist generator.

Safe helper: read-only ADB checks only (no device writes).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from textwrap import dedent


def run(cmd: list[str]) -> tuple[int, str, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def adb_cmd(target: str, *args: str) -> list[str]:
    return ["adb", "-s", target, *args]


def detect_keyguard(target: str) -> str:
    rc, out, _ = run(adb_cmd(target, "shell", "dumpsys", "window", "policy"))
    if rc != 0:
        return "unknown"
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("isStatusBarKeyguard"):
            if "true" in line:
                return "locked"
            if "false" in line:
                return "unlocked"
        if line.startswith("showing="):
            # KeyguardServiceDelegate block
            if line.endswith("true"):
                return "locked"
            if line.endswith("false"):
                return "unlocked"
    return "unknown"


def detect_top_package(target: str) -> str:
    rc, out, _ = run(adb_cmd(target, "shell", "dumpsys", "activity", "activities"))
    if rc != 0:
        return "unknown"
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("topResumedActivity=") or line.startswith("ResumedActivity:"):
            # Example: topResumedActivity=ActivityRecord{... com.android.launcher3/... t68}
            for token in line.split():
                if "/" in token and "." in token:
                    return token
    return "unknown"


def checklist(issue: str) -> str:
    if issue == "19":
        return dedent(
            """
            # Issue #19 capture checklist (humidity validation)
            1) Start clean session:
               ./scripts/capture/vmictl.py session-start issue19_humidity_validation
            2) Open measurements + checkpoints while switching Remote/Probe1/Probe2:
               ./scripts/capture/vmictl.py measurements-full
               ./scripts/capture/vmictl.py session-checkpoint <session_dir> "measurements-full"
               ./scripts/capture/vmictl.py sensors
               ./scripts/capture/vmictl.py sensor-remote
               ./scripts/capture/vmictl.py session-checkpoint <session_dir> "sensor=remote"
               ./scripts/capture/vmictl.py sensor-probe1
               ./scripts/capture/vmictl.py session-checkpoint <session_dir> "sensor=probe1"
               ./scripts/capture/vmictl.py sensor-probe2
               ./scripts/capture/vmictl.py session-checkpoint <session_dir> "sensor=probe2"
            3) End + extract:
               ./scripts/capture/vmictl.py session-end <session_dir>
               python scripts/capture/extract_packets.py <session_dir>/btsnoop.log --checkpoint-dir <session_dir>
            """
        ).strip()

    if issue == "6":
        return dedent(
            """
            # Issue #6 capture checklist (night ventilation decoding)
            1) Navigate once to Special Modes page and checkpoint baseline.
            2) Toggle only Night Ventilation ON, checkpoint immediately.
            3) Wait ~15s, checkpoint again (catch delayed writes/acks).
            4) Toggle OFF, checkpoint.
            5) Repeat 3 runs to filter noise from unrelated packets.
            6) Extract and diff around checkpoints:
               python scripts/capture/extract_packets.py <session>/btsnoop.log --checkpoint-dir <session>
               python scripts/analyze_settings_packets.py <session>/btsnoop.log
            """
        ).strip()

    return dedent(
        """
        # Issue #5 capture checklist (bypass status)
        Goal: correlate bypass icon state with packet bytes during weather-driven transitions.

        1) Capture whenever icon visibly changes (open/closed).
        2) For each event, checkpoint with note including:
           - outside temp/wind snapshot
           - bypass icon state
           - airflow mode
        3) Keep device settings unchanged; only observe.
        4) Build table across days: checkpoint -> candidate status bytes.
        5) Prefer morning/evening swings where bypass is most likely to toggle.
        """
    ).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="Preflight checks for VMI capture sessions")
    ap.add_argument("--target", default=os.environ.get("ADB_TARGET", ""), help="ADB target host:port")
    ap.add_argument("--issue", choices=["19", "6", "5"], help="Print issue-specific checklist")
    ns = ap.parse_args()

    if not ns.target:
        print("ERROR: missing ADB target (use --target or ADB_TARGET)", file=sys.stderr)
        return 2

    rc, out, err = run(["adb", "connect", ns.target])
    print(f"adb_connect_rc={rc}")
    if out:
        print(out)
    if err:
        print(err)

    rc, out, err = run(adb_cmd(ns.target, "get-state"))
    print(f"adb_state_rc={rc} state={out or err}")

    kg = detect_keyguard(ns.target)
    top = detect_top_package(ns.target)
    print(f"keyguard={kg}")
    print(f"top_window={top}")

    if kg == "locked":
        print("WARNING: phone appears locked; vmictl UI navigation will likely fail/hang.")
        print("Action: unlock phone manually, then re-run preflight.")

    if "com.ventilairsec.ventilairsecinstallateur" not in top:
        print("NOTE: VMI+ app is not foregrounded.")
        print("Action: run './scripts/capture/vmictl.py launch' or './scripts/capture/vmictl.py connect' first.")

    if ns.issue:
        print("\n" + checklist(ns.issue))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
