# Viewer-controlled SmartMotor modes

This document defines the viewer as the owner of the current physical/emulated
mode. The browser requests a mode; the local server performs device work and
reports progress. The browser never silently changes the SmartMotor.

## Modes

- **Emulator**: no serial-port discovery or connection attempt. Run the selected
  entry script against a virtual device filesystem. The source may be the
  checked-in emulator files or an explicitly selected backup directory.
- **Mirror**: snapshot the device filesystem into a timestamped backup, install
  the minimal `mirror.py` deployment, reset, and stream OLED/state telemetry.
- **Health**: snapshot the device, install the health-check entry script, ask
  the user to disconnect/reconnect as required by the check, and save the
  resulting event stream as a replay under `./replays/`.
- **Replay**: do not touch hardware. Enumerate `./replays/`, let the user pick
  one, and stream its saved events through the same viewer widgets.

## Server state machine

The server owns one state machine:

```text
emulator ─┬─> mirror ──> live-mirror
          ├─> health ──> waiting-reconnect ──> replay
          └─> replay ──> replay
```

Every transition emits `mode_progress` messages (`requested`, `backing_up`,
`installing`, `waiting_reconnect`, `running`, `failed`) and a final `state`.
Only one transition may run at once; a second request is rejected with a clear
busy error. A failed deployment leaves the backup path visible and does not
claim that the requested mode is active.

## Protocol additions

Client requests:

- `mode_select {mode, source?}`
- `replay_select {path}`
- `deploy {manifest?}` (equivalent to `./deploy.sh`, with an explicit server
  allow-list rather than arbitrary shell text)

Server messages:

- `mode_progress {mode, stage, message, backup?}`
- `replays {items}`

Existing `frame`, `state`, `trace`, and `log` messages remain unchanged, so the
same OLED, arm, sensor, and gravity-vector widgets work in every mode.

## Backups and replays

- Device snapshots go under a timestamped ignored directory (for example
  `device_backup_YYYY-MM-DD_HHMMSS/`) before any physical install.
- Replays are JSONL event streams under `./replays/`; they are intentionally
  untracked and must be listed in `.gitignore`.
- A replay records source mode, backup path, timestamps, state, frames, logs,
  and reconnect prompts. It must never contain credentials or student PII.

## Safety rules

- Emulator mode must never open a serial port.
- Browser input is data, not a shell command. Deploy uses a fixed executable
  and validated manifest paths.
- Mirror/health transitions require a visible progress state and preserve the
  last backup path on failure.
- Physical tests remain explicit acceptance checks; no mode transition should
  imply that a device is connected or that telemetry is live.
