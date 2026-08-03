# S4 — Host-link feasibility: FINDINGS

**Status: RUN.** Raw data in `run1.json`. See "Surprises" below — one
assumption in `HOSTLINK_DESIGN.md` §0 did not survive contact with hardware.

## How to run

```bash
.venv/bin/mpremote cp main.py :main_real_backup.py         # save the real main
.venv/bin/mpremote cp spikes/S4_hostlink/bench_device.py :main.py
.venv/bin/mpremote reset
./spikes/S4_hostlink/bench_host.py --json spikes/S4_hostlink/run1.json
# afterwards, restore the original firmware:
.venv/bin/mpremote cp main_real_backup.py :main.py
.venv/bin/mpremote reset
```

**`exec --no-follow "import bench_device"` does not reliably work** — in
practice the device kept running its existing `main.py` loop underneath, so
the benchmark script never actually took over. The swap-`main.py`-and-reset
approach above is what actually ran on 2026-08-03. `mpremote` and the host
script cannot hold the serial port at the same time. The device script
disables Ctrl-C; it has a 5-minute watchdog and a `Q` command, and the
physical reset button is the backstop. It writes nothing to flash beyond the
temporary `main.py` swap, which is reversed at the end.

## Environment

| | |
| --- | --- |
| Date | 2026-08-03 |
| Host machine / OS | macOS (Darwin 25.5.0) |
| Python | repo `.venv` (3.12) |
| MicroPython firmware | v1.25.0 (`ESP32_GENERIC_C3-20250415-v1.25.0.bin`) |
| Port | `/dev/cu.usbmodem2101` (VID 0x303A, PID 0x1001, native USB Serial/JTAG) |
| USB hub in path? | No, direct to laptop port |
| Board revision | Unidentified unit; device's on-flash code predates this repo's current `main.py` refactor — see note below |

**Note on this unit:** before running the benchmark, `mpremote fs ls` showed
this board's `main.py`/`myfavcolor.py`/`standalone.py`/`webconnect.py` did not
match the working tree OR any of the last 5 commits — it was running an older,
pre-refactor version (module-level code, not the `choose_activity()` /
`init_hardware()` structure). All 15 on-device files were backed up to
`device_backup_2026-08-03/` before touching anything, and the original
`main.py` was restored (and verified byte-identical via `diff`) after this
benchmark ran. This board's firmware is **not** disposable/re-flashable from
this git history the way it may have been assumed to be — treat it as unique
state until reconciled.

## Results

### ADC sampling cost — is USB even the bottleneck?

| Samples | Read (ms) | Read + sort (ms) | µs/sample |
| --- | --- | --- | --- |
| 1 | 0.25 | 0.28 | 253.0 |
| 100 | 2.96 | 3.31 | 29.6 |
| 200 | 5.76 | 6.43 | 28.8 | ← `sensors.readpoint()` |
| 1000 | 28.18 | 32.33 | 28.2 | ← `webconnect.readSensor()`, **per message** |

**Yes and no.** `webconnect.readSensor()`'s 1000-read-plus-sort pattern costs
~32 ms of dead time on the device *before it even touches the serial port*.
That's a real, fixed tax on every message under the current code — but it
turns out to be roughly the same order of magnitude as the link's own
per-message cost at larger payload sizes (see RTT below), not the dominant
term by an order of magnitude the way the design doc assumed.

### Round-trip latency

| Read mode | Payload | Median (ms) | p95 (ms) | Max (ms) |
| --- | --- | --- | --- | --- |
| readline | 8 B | 1.00 | 1.08 | 5.14 |
| readline | 64 B | 8.13 | 10.08 | 13.90 |
| readline | 256 B | 20.03 | 30.14 | 30.26 |
| bytewise | 8 B | 2.07 | 2.36 | 3.33 |
| bytewise | 64 B | 6.98 | 7.97 | 9.26 |
| bytewise | 256 B | 40.00 | 40.20 | 43.28 |

Cost of byte-at-a-time reading (the `webconnect.py` pattern): roughly 2x the
`readline` cost at small and large payloads (2.1 vs 1.0 ms at 8 B; 40.0 vs
20.0 ms at 256 B); it's a wash at 64 B, inside the noise. Real, but secondary
to the payload-size effect below.

### Throughput

Lines/s: 236   kB/s: 11.0

### Streaming

| Rate | Received/sent | Dropped | Device gap p95 (ms) | Host gap p95 (ms) | Device max late (µs) |
| --- | --- | --- | --- | --- | --- |
| 50 Hz | 100/100 | 0 | 20.01 | 20.21 | 14 |
| 100 Hz | 200/200 | 0 | 10.01 | 10.17 | 15 |
| 200 Hz | 400/400 | 0 | 5.01 | 6.52 | 15 |
| 500 Hz | 1000/1000 | 0 | 2.01 | 3.02 | 15 |

Highest rate sustained with zero drops: **at least 500 Hz** (the sweep's top
rate — it never found the ceiling). Each streamed record here is small
(`S <seq> <ticks_us> <adc_reading>\n`, ~15-20 B), and device-side lateness
tops out at 15 µs regardless of rate — the device is not straining at all.
This is the realistic shape of the accelerometer/game use case: small,
frequent samples, not large messages.

## Verdict against the §2 thresholds

- RTT median < 10 ms, p95 < 20 ms → closed-loop control at 50 Hz: **yes**, for
  payloads up to ~64 B (median 1.0-8.1 ms). **No** at 256 B (median 20 ms,
  right at the boundary) — keep control-loop messages small.
- 100 Hz streaming, zero drops → accelerometer games: **yes**, with headroom
  to spare — 500 Hz streamed cleanly with small payloads and near-zero device
  lateness.
- Chosen mode set (RPC / stream / batch): **stream mode for anything periodic
  and small** (games, accelerometer feed, sensor logging) — that's the proven
  sweet spot. **RPC mode for occasional small requests** (control commands),
  keeping payloads under ~64 B where practical. **Batch mode for bulk
  transfer** (e.g. handing torch a chunk of pre-recorded samples) — expect it
  to be bandwidth-bound at ~11 kB/s (see below), not latency-bound.

## Student-laptop re-run

The classroom case is the one that matters — USB stacks and CPU scheduling
differ. Repeat on at least one student machine and note any differences.

| | |
| --- | --- |
| Machine / OS | _not yet run — pending_ |
| Worst-case difference from above | _not yet run — pending_ |

## Surprises and notes

**The link is not "full-speed USB with no baud ceiling" — it behaves like a
genuine ~115200-baud serial link.** `HOSTLINK_DESIGN.md` §0 assumed the native
USB Serial/JTAG peripheral's throughput would be bounded by ~1 ms USB frames,
not by the `Serial(port, 115200, ...)` baud rate passed to pyserial (a
software-configured no-op on a real full-speed USB CDC-style link, in that
assumption). The measurements say otherwise:

- Raw throughput came out to 11.0 kB/s — almost exactly the ~11.5 kB/s a real
  115200-baud UART would deliver (115200 bps ÷ 10 bits/byte), not the tens to
  hundreds of kB/s full-speed USB would allow.
- RTT scales with payload size in a way that matches serial-transmission time,
  not USB-frame count: 256 B echoed round-trip (512 B on the wire) costs
  ~20-40 ms, which is what 512 B ÷ 11.5 kB/s predicts (~44 ms), not what a
  1 ms-per-frame USB link would predict (a few ms at most).

Practical effect: it doesn't change the verdict for the use cases the user
actually described (small, frequent samples for games/control loops sail
through at 500 Hz with room to spare), but it does mean **bulk/batch transfer
is genuinely bandwidth-limited to ~11 kB/s**, not just latency-limited as
`HOSTLINK_DESIGN.md` implied. Worth fixing that assumption in the design doc
before H001+ firmware work leans on it. Whether this ceiling is inherent to
the ESP32-C3's native USB Serial/JTAG peripheral or an artifact of the
`115200` argument passed to pyserial's `Serial()` (which may still throttle
writes even on a CDC-ACM-style link, depending on the driver) is worth a
5-minute follow-up: rerun `bench_throughput` with pyserial opened at a much
higher nominal baud (e.g. 921600) and see if the ceiling moves. If it does,
the fix is trivial (open the port faster); if it doesn't, ~11 kB/s is the real
ceiling and batch-mode transfers should be sized accordingly.
