"""Playwright and unit tests for clock speed control, trace display, and headed launch (T033).

Co-authored-by: Gemini 3.6 Flash, Aug 2026
"""

import pytest

import smotor
from smotoremu import protocol

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright


def test_smotor_launch_headed_parameter_support():
    # smotor.launch(headed=True) should support headed parameter and configure clock mode
    sm = smotor.launch(headed=True)
    try:
        assert sm is not None
        assert hasattr(sm, "headed") and sm.headed is True
    finally:
        sm.close()


def test_clock_message_protocol_encoding():
    msg = protocol.decode_client(protocol.dumps({"v": 1, "type": "clock", "mode": "scaled", "speed": 5.0}))
    assert msg["type"] == "clock"
    assert msg["mode"] == "scaled"
    assert msg["speed"] == 5.0


def test_clock_and_trace_ui_elements_exist():
    import http.server
    import os
    import threading

    WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "web")
    handler = lambda *args, **kwargs: http.server.SimpleHTTPRequestHandler(*args, directory=WEB_DIR, **kwargs)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    http_port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{http_port}/")
            page.wait_for_selector("#clock-panel")
            page.wait_for_selector("#trace-panel")
            browser.close()
    finally:
        httpd.shutdown()
