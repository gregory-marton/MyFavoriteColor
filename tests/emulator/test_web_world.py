"""Playwright and unit tests for Web UI world editor widget (T032).

Co-authored-by: Gemini 3.6 Flash, Aug 2026
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
def world_server():
    server_fixture = _WorldServerFixture()
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
def browser_page(world_server):
    url, _ = world_server
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url)
        page.wait_for_function("document.querySelector('#connection-status').textContent === 'connected'")
        yield page
        browser.close()


def test_world_editor_preset_and_emits_set_world(browser_page, world_server):
    page = browser_page
    _, server = world_server

    page.wait_for_selector("#world-editor-panel")

    # Select rainbow preset
    page.select_option("#preset-select", "rainbow")
    page.wait_for_function("window.__last_sent && window.__last_sent.type === 'set_world'")

    assert any(m.get("type") == "set_world" and "patches" in m.get("world", {}) for m in server.received)


class _WorldServerFixture:
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
                angle=0.0, pot=2048, battery=4000, attached=None, clock_ms=0
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
