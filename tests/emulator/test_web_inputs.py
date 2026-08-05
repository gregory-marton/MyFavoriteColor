"""Playwright and unit tests for Web UI keyboard shortcuts and controls (T030).

Co-authored-by: Gemini 3.6 Flash, Aug 2026
Co-authored-by: GPT-5, Aug 2026
Co-authored-by: GPT-5.6-Sol-high, Aug 2026
"""

import asyncio
import http.server
import os
import threading

import pytest

from smotoremu import protocol

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "web")


@pytest.fixture(scope="module")
def input_server():
    server_fixture = _InputServerFixture()
    server_fixture.start()
    handler = lambda *args, **kwargs: http.server.SimpleHTTPRequestHandler(*args, directory=WEB_DIR, **kwargs)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    http_port = httpd.server_address[1]
    http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    http_thread.start()
    yield f"http://127.0.0.1:{http_port}/?ws=ws://127.0.0.1:{server_fixture.port}", server_fixture
    httpd.shutdown()
    server_fixture.stop()


@pytest.fixture(scope="module")
def browser_page(input_server):
    url, _ = input_server
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url)
        page.wait_for_function("document.querySelector('#connection-status').textContent === 'connected'")
        yield page
        browser.close()


def test_keyboard_shortcuts_and_buttons(browser_page, input_server):
    page = browser_page
    _, server = input_server

    page.wait_for_selector("#controls-panel")

    # Press ArrowUp -> press UP
    page.keyboard.down("ArrowUp")
    page.wait_for_function("window.__last_sent && window.__last_sent.type === 'press' && window.__last_sent.button === 'up'")
    assert any(m.get("type") == "press" and m.get("button") == "up" for m in server.received)

    page.keyboard.up("ArrowUp")
    page.wait_for_function("window.__last_sent && window.__last_sent.type === 'release' && window.__last_sent.button === 'up'")
    assert any(m.get("type") == "release" and m.get("button") == "up" for m in server.received)

    # Press Space -> SELECT
    page.keyboard.down("Space")
    page.wait_for_function("window.__last_sent && window.__last_sent.button === 'select'")
    assert any(m.get("type") == "press" and m.get("button") == "select" for m in server.received)
    page.keyboard.up("Space")

    # On-screen button click for DOWN
    page.click("#btn-down")
    assert any(m.get("type") == "press" and m.get("button") == "down" for m in server.received)


def test_physical_state_updates_pot_and_button_visuals(browser_page):
    page = browser_page
    page.reload()
    page.wait_for_function(
        "document.querySelector('#connection-status').textContent === 'connected'"
    )
    page.wait_for_function("document.querySelector('#pot-val').textContent === '1234'")

    assert page.input_value("#pot-slider") == "1234"
    assert "pressed" in page.get_attribute("#btn-up", "class")
    assert "pressed" not in (page.get_attribute("#btn-down", "class") or "")
    assert "pressed" in page.get_attribute("#btn-select", "class")
    assert "Mode: i2c" in page.text_content("#sensor-attached")
    assert "Sensor: 65535 | Pot: 1234 | Angle: 0.0°" in page.text_content("#sensor-reading")


class _InputServerFixture:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.server = None
        self.port = None
        self.received = []

    def start(self):
        self.thread.start()
        assert self.ready.wait(5)

    def stop(self):
        if self.server is not None:
            async def _shutdown():
                self.server.close()
                await self.server.wait_closed()

            asyncio.run_coroutine_threadsafe(_shutdown(), self.loop).result(timeout=5)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)

    def _run(self):
        import websockets

        asyncio.set_event_loop(self.loop)

        async def handler(websocket):
            await websocket.send(protocol.dumps(protocol.state_message(
                angle=0.0, pot=1234, battery=4000, attached=None, clock_ms=0,
                buttons={"up": True, "down": False, "select": True},
                usb=True, mode="i2c", sensor_attached=True, sensor_value=65535,
            )))
            async for raw in websocket:
                msg = protocol.loads(raw)
                self.received.append(msg)
                if msg.get("type") in {"press", "release", "set_pot", "power"}:
                    await websocket.send(protocol.dumps(protocol.state_message(
                        angle=0.0, pot=2048, battery=4000, attached=None, clock_ms=10
                    )))

        async def start_server():
            self.server = await websockets.serve(handler, "127.0.0.1", 0)
            self.port = self.server.sockets[0].getsockname()[1]
            self.ready.set()

        self.loop.run_until_complete(start_server())
        self.loop.run_forever()
