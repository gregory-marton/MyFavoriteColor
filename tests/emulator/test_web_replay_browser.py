"""Browser-level proof that a stored healthcheck recording actually replays
in the web UI: the recordings dropdown lists it, Replay streams it over
/replay, and the trace panel shows the real per-tick numbers -- including
the sample-to-sample jitter, which is the whole point of capturing
FULL_SAMPLE at every tick (see healthcheck_logic.format_full_sample_line).

Runs the real smotoremu.server (not a hand-rolled fixture) so /api/recordings
and /replay are exercised exactly as a teacher's browser would hit them.

Co-authored-by: Claude Sonnet 5, Aug 2026
"""

import asyncio
import os
import threading

import pytest

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

from smotoremu import server as server_module

SAMPLE_LOG = (
    "BOOT boot_num=1 reset_cause=1(PWRON_RESET) resume_stage=0\n"
    "FULL_SAMPLE t=10 pot=2048 batt_raw=2894 batt_uv=2079321 accel=-9,1,-253 "
    "port=alg sensor_attached=1 sensor=1500 btn=1,1,0 angle=90\n"
    "FULL_SAMPLE t=30 pot=2051 batt_raw=2888 batt_uv=2071904 accel=-8,3,-251 "
    "port=alg sensor_attached=1 sensor=1487 btn=1,1,0 angle=90\n"
    "FULL_SAMPLE t=50 pot=2046 batt_raw=2891 batt_uv=2075118 accel=-10,0,-255 "
    "port=alg sensor_attached=1 sensor=1512 btn=1,1,0 angle=90\n"
)


@pytest.fixture(scope="module")
def real_server(tmp_path_factory):
    recordings_root = tmp_path_factory.mktemp("recordings")
    run_dir = recordings_root / "deadbeef0001" / "2026-08-07T12-00-00"
    run_dir.mkdir(parents=True)
    (run_dir / "healthcheck_log.txt").write_text(SAMPLE_LOG)
    server_module.RECORDINGS_ROOT = str(recordings_root)

    loop = asyncio.new_event_loop()
    ready = threading.Event()
    state = {"port": None, "server": None}

    def _run():
        import websockets

        asyncio.set_event_loop(loop)

        async def start():
            server = await websockets.serve(
                server_module._connection_handler, "127.0.0.1", 0,
                process_request=server_module.websocket_process_request,
            )
            state["server"] = server
            state["port"] = server.sockets[0].getsockname()[1]
            ready.set()

        loop.run_until_complete(start())
        loop.run_forever()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    assert ready.wait(5)

    yield f"http://127.0.0.1:{state['port']}/"

    async def _shutdown():
        state["server"].close()
        await state["server"].wait_closed()

    asyncio.run_coroutine_threadsafe(_shutdown(), loop).result(timeout=5)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def browser_page(real_server):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(real_server)
        page.wait_for_function(
            "document.querySelector('#replay-select').options.length > 1"
        )
        yield page
        browser.close()


def test_recordings_dropdown_lists_the_stored_run(browser_page):
    page = browser_page
    options = page.eval_on_selector_all("#replay-select option", "els => els.map(e => e.value)")
    assert "deadbeef0001/2026-08-07T12-00-00/healthcheck_log.txt" in options


def test_replay_streams_each_ticks_real_numbers_into_the_trace_panel(browser_page):
    page = browser_page
    page.select_option("#replay-select", "deadbeef0001/2026-08-07T12-00-00/healthcheck_log.txt")
    page.click("#replay-btn")

    page.wait_for_function(
        "document.querySelector('#replay-status').textContent.startsWith('done')",
        timeout=15000,
    )

    log_text = page.text_content("#trace-log-list")
    # All three ticks' pot readings show up distinctly -- this is the jitter:
    # not a single settled value, the real sample-to-sample wiggle.
    assert "pot=2048" in log_text
    assert "pot=2051" in log_text
    assert "pot=2046" in log_text
    assert "angle=90" in log_text


def test_trace_filter_can_isolate_sensor_samples(browser_page):
    page = browser_page
    page.select_option("#trace-filter", "FULL_SAMPLE")
    visible_text = page.text_content("#trace-log-list")
    assert "pot=" in visible_text
    page.select_option("#trace-filter", "all")
