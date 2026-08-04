"""Playwright test for the web replay UI (web/index.html + app.js).

Desktop only, per the explicit scope for this pass. Serves web/ with a
plain http.server on a background thread (no new server framework needed),
builds a small fixture trace with a real rendered SCREEN buffer, a SERVO
angle, and a SUSTAIN_SAMPLE with on_usb, and drives the actual page with a
real Chromium browser.
"""

import http.server
import json
import os
import threading

import pytest

from smotoremu.trace import render_screens

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "web")


@pytest.fixture(scope="module")
def fixture_trace_written():
    events = [
        {"type": "BOOT", "t": 0, "boot_num": 1, "reset_cause": 1, "reset_cause_name": "PWRON_RESET", "resume_stage": 0},
        {"type": "SCREEN", "t": 100, "lines": ["POT x3", "sweep fully"]},
        {"type": "SERVO", "t": 150, "angle": 90},
        {"type": "SUSTAIN_SAMPLE", "t": 200, "pot": 1500, "batt_raw": 2900, "batt_uv": 2100000,
         "accel": (-9, 1, -253), "orientation": {"roll": 179.8, "pitch": 2.0}, "on_usb": True},
        {"type": "SUSTAIN_SAMPLE", "t": 400, "pot": 1500, "batt_raw": 1900, "batt_uv": 1400000,
         "accel": (-9, 1, -253), "orientation": {"roll": 179.8, "pitch": 2.0}, "on_usb": False},
        {"type": "REP", "t": 450, "stage": "UP"},
        {"type": "REP", "t": 475, "stage": "DOWN"},
        {"type": "STAGE_DONE", "t": 500, "stage": "POT"},
    ]
    events = render_screens(events)
    path = os.path.join(WEB_DIR, "trace.json")
    original = None
    if os.path.exists(path):
        with open(path) as f:
            original = f.read()
    with open(path, "w") as f:
        json.dump({"source": "fixture", "events": events}, f)
    yield path
    if original is not None:
        with open(path, "w") as f:
            f.write(original)


@pytest.fixture(scope="module")
def server_url(fixture_trace_written):
    handler = lambda *args, **kwargs: http.server.SimpleHTTPRequestHandler(*args, directory=WEB_DIR, **kwargs)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}/"
    httpd.shutdown()


@pytest.fixture(scope="module")
def browser_page(server_url):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(server_url)
        yield page
        browser.close()


def test_page_loads_and_shows_first_event_state(browser_page):
    page = browser_page
    page.wait_for_function("document.getElementById('t-v').textContent !== '0' || true")
    # after seekTo(0), the first event (BOOT) is applied -- t should be 0
    assert page.text_content("#t-v") == "0"


def test_scrubbing_to_the_screen_event_renders_and_logs_it(browser_page):
    page = browser_page
    page.fill("#scrub", "1")
    page.dispatch_event("#scrub", "input")
    page.wait_for_function("document.getElementById('t-v').textContent === '100'")
    log_text = page.text_content("#log")
    assert "POT x3" in log_text
    assert "sweep fully" in log_text


def test_scrubbing_to_usb_connected_sample_shows_connected_badge(browser_page):
    page = browser_page
    page.fill("#scrub", "3")  # the on_usb=True SUSTAIN_SAMPLE
    page.dispatch_event("#scrub", "input")
    page.wait_for_function("document.getElementById('usb-badge').textContent === 'connected'")
    assert page.text_content("#usb-badge") == "connected"
    assert "usb-on" in page.get_attribute("#usb-badge", "class")
    assert "roll" in page.text_content("#orientation-v")


def test_scrubbing_to_usb_disconnected_sample_shows_disconnected_badge(browser_page):
    page = browser_page
    page.fill("#scrub", "4")  # the on_usb=False SUSTAIN_SAMPLE
    page.dispatch_event("#scrub", "input")
    page.wait_for_function("document.getElementById('usb-badge').textContent === 'disconnected'")
    assert page.text_content("#usb-badge") == "disconnected"
    assert "usb-off" in page.get_attribute("#usb-badge", "class")


def test_oled_canvas_has_nonblank_pixels_after_screen_event(browser_page):
    page = browser_page
    page.fill("#scrub", "1")
    page.dispatch_event("#scrub", "input")
    page.wait_for_timeout(100)
    has_pixels = page.evaluate(
        """() => {
            const c = document.getElementById('oled');
            const ctx = c.getContext('2d');
            const data = ctx.getImageData(0, 0, c.width, c.height).data;
            for (let i = 0; i < data.length; i += 4) if (data[i] > 0) return true;
            return false;
        }"""
    )
    assert has_pixels


def test_down_button_indicator_exists_and_flashes_on_down_rep(browser_page):
    page = browser_page
    page.fill("#scrub", "6")
    page.dispatch_event("#scrub", "input")
    page.wait_for_function("document.getElementById('btn-down').classList.contains('pressed')")
    assert "pressed" in page.get_attribute("#btn-down", "class")


def test_play_button_advances_the_scrub_position(browser_page):
    page = browser_page
    page.fill("#scrub", "0")
    page.dispatch_event("#scrub", "input")
    page.select_option("#speed", "50")
    page.click("#play")
    page.wait_for_function("parseInt(document.getElementById('scrub').value) > 0", timeout=5000)
    page.click("#pause")


def test_play_keeps_advancing_past_the_first_frame(browser_page):
    # regression test: an earlier bug re-derived the target time from
    # events[idx].t each frame instead of accumulating a running virtual
    # clock, so idx got stuck at 0 forever once the per-frame delta wasn't
    # enough to cross the very first event gap.
    page = browser_page
    page.fill("#scrub", "0")
    page.dispatch_event("#scrub", "input")
    page.select_option("#speed", "5")
    page.click("#play")
    page.wait_for_timeout(1500)
    idx_at_1500ms = page.evaluate("idx")
    page.click("#pause")
    # the bug got idx permanently stuck at 0; this fixture trace is short
    # enough that a fixed version reaches the very last event well within
    # 1.5s at 5x speed.
    assert idx_at_1500ms > 0
    assert idx_at_1500ms == page.evaluate("events.length - 1")


def test_pot_value_extracted_from_screen_text_drives_the_bar(browser_page):
    page = browser_page
    page.fill("#scrub", "1")  # the SCREEN event with lines=["POT x3", "sweep fully"]
    page.dispatch_event("#scrub", "input")
    # this fixture's SCREEN text has no "v=NNNN" pattern, so pot stays
    # unset; confirm the bar renders 0% rather than throwing on null.
    fill_width = page.evaluate("document.getElementById('pot-bar-fill').style.width")
    assert fill_width in ("0%", "")


def test_button_rep_event_flashes_the_pressed_class(browser_page):
    page = browser_page
    page.fill("#scrub", "5")  # the REP stage=UP fixture event
    page.dispatch_event("#scrub", "input")
    page.wait_for_timeout(50)
    assert "pressed" in page.get_attribute("#btn-up", "class")
