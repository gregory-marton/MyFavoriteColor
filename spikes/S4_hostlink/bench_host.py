#!/Users/gregorymarton/Documents/GitHub/MyFavoriteColor/.venv/bin/python3
"""
S4 host-link benchmark -- HOST side.

Run against a SmartMotor running bench_device.py. Prints the numbers that
decide whether real-time host<->device work is feasible, and at what rate.

    ./spikes/S4_hostlink/bench_host.py
    ./spikes/S4_hostlink/bench_host.py --port /dev/cu.usbmodem2101

Requires pyserial (already present via esptool).

This is a THROWAWAY EXPERIMENT. Its only product is a number in FINDINGS.md.
"""

import argparse
import json
import statistics
import sys
import time

try:
    import serial
    import serial.tools.list_ports as list_ports
except ImportError:
    sys.exit("pyserial not found. Run via the repo venv's shebang: " + __file__)

ESPRESSIF_VID = 0x303A  # ESP32-C3 native USB Serial/JTAG


def find_port():
    candidates = [p for p in list_ports.comports() if p.vid == ESPRESSIF_VID]
    if not candidates:
        # fall back to the name pattern deploy.sh uses
        candidates = [p for p in list_ports.comports() if "usbmodem" in p.device]
    if not candidates:
        sys.exit(
            "No SmartMotor found. Plugged in? Ports seen:\n  "
            + "\n  ".join(p.device for p in list_ports.comports())
        )
    if len(candidates) > 1:
        print(f"note: {len(candidates)} candidate ports; using the first")
    return candidates[0].device


class Link:
    def __init__(self, port, verbose=False):
        # dsrdtr/rts off: the C3's native USB-serial does not use the classic
        # DTR/RTS auto-reset circuit, but be explicit rather than lucky.
        self.ser = serial.Serial(port, 115200, timeout=2.0, dsrdtr=False, rtscts=False)
        self.ser.dtr = False
        self.ser.rts = False
        self.verbose = verbose
        time.sleep(0.2)
        self.ser.reset_input_buffer()

    def send(self, line):
        self.ser.write((line + "\n").encode())
        self.ser.flush()

    def readline(self, skip_comments=True):
        while True:
            raw = self.ser.readline()
            if not raw:
                return None
            text = raw.decode("utf-8", "replace").strip()
            if skip_comments and text.startswith("#"):
                if self.verbose:
                    print("   ", text)
                continue
            return text

    def roundtrip(self, line):
        t0 = time.perf_counter()
        self.send(line)
        reply = self.readline()
        return (time.perf_counter() - t0) * 1000.0, reply

    def close(self):
        try:
            self.send("Q")
            self.readline()
        except Exception:
            pass
        self.ser.close()


def pct(values, p):
    if not values:
        return float("nan")
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(p / 100.0 * (len(ordered) - 1))))
    return ordered[idx]


def bench_rtt(link, results, n=150):
    print("\n== Round-trip latency ==")
    for mode in ("readline", "bytewise"):
        link.send(f"M {mode}")
        if link.readline() is None:
            print(f"  {mode}: no response, skipping")
            continue
        for size in (8, 64, 256):
            payload = "x" * size
            samples = []
            for _ in range(n):
                ms, reply = link.roundtrip(f"E {payload}")
                if reply is None:
                    break
                samples.append(ms)
            if not samples:
                print(f"  {mode:9s} {size:4d}B  no data")
                continue
            key = f"rtt_{mode}_{size}B_ms"
            results[key] = {
                "median": round(statistics.median(samples), 3),
                "p95": round(pct(samples, 95), 3),
                "max": round(max(samples), 3),
                "n": len(samples),
            }
            print(
                f"  {mode:9s} {size:4d}B  median {statistics.median(samples):6.2f} ms"
                f"   p95 {pct(samples, 95):6.2f} ms   max {max(samples):6.2f} ms"
            )
    link.send("M readline")
    link.readline()


def bench_stream(link, results, count=2000, period_us=1000):
    hz = 1_000_000 / period_us
    print(f"\n== Streaming at {hz:.0f} Hz ({count} records) ==")
    link.send(f"S {count} {period_us}")

    device_ts, host_gaps = [], []
    last_host = None
    received = 0
    summary = None
    deadline = time.time() + 60

    while time.time() < deadline:
        line = link.readline()
        if line is None:
            break
        if line.startswith("SDONE"):
            summary = line.split()
            break
        if not line.startswith("S "):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        received += 1
        device_ts.append(int(parts[2]))
        now = time.perf_counter()
        if last_host is not None:
            host_gaps.append((now - last_host) * 1000.0)
        last_host = now

    dropped = count - received
    device_gaps = [
        (b - a) / 1000.0 for a, b in zip(device_ts, device_ts[1:]) if b > a
    ]
    entry = {
        "requested_hz": round(hz, 1),
        "received": received,
        "dropped": dropped,
    }
    if device_gaps:
        entry["device_gap_ms"] = {
            "median": round(statistics.median(device_gaps), 3),
            "p95": round(pct(device_gaps, 95), 3),
        }
    if host_gaps:
        entry["host_gap_ms"] = {
            "median": round(statistics.median(host_gaps), 3),
            "p95": round(pct(host_gaps, 95), 3),
            "max": round(max(host_gaps), 3),
        }
    if summary and len(summary) >= 4:
        entry["device_elapsed_ms"] = round(int(summary[2]) / 1000.0, 1)
        entry["max_late_us"] = int(summary[3])
    results[f"stream_{hz:.0f}hz"] = entry

    print(f"  received {received}/{count}  (dropped {dropped})")
    if device_gaps:
        print(
            f"  device-side gap  median {statistics.median(device_gaps):6.3f} ms"
            f"   p95 {pct(device_gaps, 95):6.3f} ms"
        )
    if host_gaps:
        print(
            f"  host-side   gap  median {statistics.median(host_gaps):6.3f} ms"
            f"   p95 {pct(host_gaps, 95):6.3f} ms   max {max(host_gaps):6.3f} ms"
        )
    if summary and len(summary) >= 4:
        late_us = int(summary[3])
        print(f"  device max lateness {late_us} us"
              + ("   <-- device could NOT keep up" if late_us > period_us else ""))
    return dropped == 0 and (not summary or int(summary[3]) <= period_us)


def bench_throughput(link, results, count=5000):
    print(f"\n== Raw throughput ({count} lines, as fast as possible) ==")
    link.send(f"T {count}")
    t0 = time.perf_counter()
    received = 0
    total_bytes = 0
    while True:
        line = link.readline()
        if line is None or line.startswith("TDONE"):
            break
        if line.startswith("T "):
            received += 1
            total_bytes += len(line) + 1
    elapsed = time.perf_counter() - t0
    if elapsed <= 0:
        return
    results["throughput"] = {
        "lines": received,
        "seconds": round(elapsed, 3),
        "lines_per_s": round(received / elapsed),
        "kbytes_per_s": round(total_bytes / elapsed / 1024, 1),
    }
    print(f"  {received} lines in {elapsed:.2f} s"
          f"  =  {received/elapsed:.0f} lines/s, {total_bytes/elapsed/1024:.1f} kB/s")


def bench_adc(link, results):
    print("\n== ADC sampling cost (the hidden latency) ==")
    for n in (1, 100, 200, 1000):
        link.send(f"A {n}")
        line = link.readline()
        if not line or not line.startswith("ADONE"):
            continue
        _, count, read_us, full_us, _mean = line.split()
        count, read_us, full_us = int(count), int(read_us), int(full_us)
        results[f"adc_{count}"] = {
            "read_ms": round(read_us / 1000.0, 3),
            "read_and_sort_ms": round(full_us / 1000.0, 3),
            "us_per_sample": round(read_us / count, 2),
        }
        note = ""
        if count == 1000:
            note = "   <-- webconnect.readSensor() does this PER MESSAGE"
        elif count == 200:
            note = "   <-- sensors.readpoint() does this"
        print(f"  {count:5d} reads: {read_us/1000:7.2f} ms"
              f"   (+sort: {full_us/1000:7.2f} ms)"
              f"   {read_us/count:5.1f} us/sample{note}")


def main():
    ap = argparse.ArgumentParser(description="SmartMotor host-link benchmark")
    ap.add_argument("--port", default=None)
    ap.add_argument("--json", default=None, help="write raw results here")
    ap.add_argument("-v", "--verbose", action="store_true", help="show device '#' lines")
    args = ap.parse_args()

    port = args.port or find_port()
    print(f"Connecting to {port} ...")
    link = Link(port, verbose=args.verbose)

    results = {"port": port}
    try:
        link.send("R")
        line = link.readline()
        if line is None:
            sys.exit(
                "No response from the device.\n"
                "Is bench_device.py running? See the HOW TO RUN header in it.\n"
                "Note that mpremote and this script cannot hold the port at once."
            )
        if line.startswith("RDONE"):
            overhead_us = int(line.split()[1])
            results["ticks_us_overhead_ns"] = round(overhead_us * 1000 / 1000)
            print(f"  device ticks_us() overhead: {overhead_us/1000:.2f} us per call")

        bench_adc(link, results)
        bench_rtt(link, results)
        bench_throughput(link, results)
        for hz in (50, 100, 200, 500):
            if not bench_stream(link, results, count=int(hz * 2), period_us=int(1e6 / hz)):
                print(f"  -> {hz} Hz is above the sustainable rate; stopping the sweep")
                break
    finally:
        link.close()

    if args.json:
        with open(args.json, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nRaw results written to {args.json}")

    print("\nRecord these numbers in spikes/S4_hostlink/FINDINGS.md.")


if __name__ == "__main__":
    main()
