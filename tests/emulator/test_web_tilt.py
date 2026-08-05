"""Playwright and unit tests for Web UI accelerometer tilt widget (T031).

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
def tilt_server():
    server_fixture = _TiltServerFixture()
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
def browser_page(tilt_server):
    url, _ = tilt_server
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url)
        page.wait_for_function("document.querySelector('#connection-status').textContent === 'connected'")
        yield page
        browser.close()


def test_tilt_widget_renders_and_emits_set_tilt(browser_page, tilt_server):
    page = browser_page
    _, server = tilt_server

    page.wait_for_selector("#tilt-panel")

    # Double click to reset
    page.dblclick("#tilt-canvas")
    page.wait_for_function("window.__last_sent && window.__last_sent.type === 'set_tilt'")

    assert any(m.get("type") == "set_tilt" and m.get("roll") == 0 and m.get("pitch") == 0 for m in server.received)


def test_physical_orientation_updates_tilt_widget(browser_page):
    browser_page.reload()
    browser_page.wait_for_function(
        "document.querySelector('#tilt-readout').textContent.includes('Roll: 25.0°')"
    )
    assert "Pitch: -15.0°" in browser_page.text_content("#tilt-readout")


class _TiltServerFixture:
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
                angle=0.0, pot=2048, battery=4000, attached=None, clock_ms=0,
                roll=25.0, pitch=-15.0,
            )))
            async for raw in websocket:
                msg = protocol.loads(raw)
                self.received.append(msg)

        async def start_server():
            self.server = await websockets.serve(handler, "127.0.0.1", 0)
            self.port = self.server.sockets[0].getsockname()[1]
            self.ready.set()

        self.loop.run_until_complete(start_server())
        self.loop.run_forever()
