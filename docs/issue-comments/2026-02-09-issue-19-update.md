### Capture-backed validation update (2026-02-09)

Post-#26, ADB target `192.168.1.160:38087` is reachable and stable (`adb connect` + shell commands succeed).

I attempted to run a new #19 capture session (`issue19_humidity_validation`) but hit an execution blocker:
- `vmictl` navigation commands (e.g. `measurements-full`) stall waiting for expected VMI selectors.
- Preflight checks show the top resumed activity is launcher (`com.android.launcher3/...`) instead of VMI+.
- `vmictl launch` returns success but the UI remains on launcher in subsequent dumps.

To make this reproducible and unblock future runs, I added:
- `scripts/capture/preflight_capture.py` (read-only checks: ADB connectivity, keyguard state, top resumed activity)
- explicit #19 runbook with checkpoint and extraction commands in `docs/reverse-engineering/playbook.md`

Once VMI+ reliably stays foregrounded on the capture phone, we can re-run the exact #19 sequence and attach fresh packet/UI correlation evidence.
