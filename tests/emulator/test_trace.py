"""T015 trace recorder tests.

Co-authored-by: GPT-5, Aug 2026
"""

from smotoremu.machine_shim import ADC, Pin
from smotoremu.session import Session
from smotoremu.trace import TraceRecorder


def test_session_records_button_and_adc_events_in_timestamp_order():
    session = Session(seed=123)

    session.buttons.press("up")
    ADC(Pin(3)).read()

    events = session.trace.events
    kinds = [event["kind"] for event in events]

    assert "header" in kinds
    assert "button" in kinds
    assert "pin" in kinds
    assert "adc" in kinds
    assert [event["t_us"] for event in events] == sorted(event["t_us"] for event in events)


def test_trace_ring_buffer_drops_oldest_events():
    trace = TraceRecorder(max_events=3, seed=1)

    for n in range(5):
        trace.record(n, "pin", {"pin": n})

    assert [event["detail"]["pin"] for event in trace.events] == [2, 3, 4]


def test_trace_jsonl_round_trips():
    trace = TraceRecorder(max_events=10, seed=7, config={"mode": "test"})
    trace.record(10, "button", {"name": "select", "action": "press"})
    trace.record(20, "adc", {"pin": 3, "value": 2048})

    restored = TraceRecorder.from_jsonl(trace.to_jsonl())

    assert restored.max_events == 10
    assert restored.events == trace.events


def test_trace_header_records_seed_and_config():
    session = Session(seed=42, board_config={"accelerometer": False})

    header = session.trace.events[0]

    assert header["kind"] == "header"
    assert header["detail"]["seed"] == 42
    assert header["detail"]["config"]["board_config"] == {"accelerometer": False}


def test_session_captures_device_print_output_as_log_event(tmp_path, monkeypatch):
    (tmp_path / "print_program.py").write_text("def main():\n    print('hello', 'trace')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    session = Session()

    session.boot("print_program")
    session.run_until_idle()

    logs = [event for event in session.trace.events if event["kind"] == "log"]
    assert logs[-1]["detail"]["message"] == "hello trace"
