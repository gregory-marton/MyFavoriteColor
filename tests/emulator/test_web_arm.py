"""Playwright and unit tests for Web UI arm and angle widget (T029).

Co-authored-by: Gemini 3.6 Flash, Aug 2026
"""

import asyncio
import http.server
import os
import threading

import pytest

from smotoremu import protocol
from smotoremu.server import ServerSession
from smotoremu.world import World

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "web")


def test_server_session_state_message_includes_commanded_angle_and_world():
    session = ServerSession()
    try:
        msg = session.state_message()
        assert "commanded_angle" in msg
        assert "world" in msg
        assert msg["commanded_angle"] == session.sm.arm.angle
        assert isinstance(msg["world"], dict)
        assert "patches" in msg["world"]
    finally:
        session.close()


@pytest.fixture(scope="module")
def arm_server():
    world = World(
        patches=[
            {"from": 0, "to": 60, "color": "#ff0000", "name": "red"},
            {"from": 60, "to": 120, "color": "#00ff00", "name": "green"},
            {"from": 120, "to": 180, "color": "#0000ff", "name": "blue"},
        ]
    )
    messages = [
        protocol.state_message(
            angle=45.0,
            commanded_angle=90.0,
            pot=2000,
            battery=4000,
            attached="VEML6040",
            clock_ms=100,
            world=world.to_dict(),
        )
    ]
    ws_server = _WebSocketFixture(messages)
    ws_server.start()
    handler = lambda *args, **kwargs: http.server.SimpleHTTPRequestHandler(*args, directory=WEB_DIR, **kwargs)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    http_port = httpd.server_address[1]
    http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    http_thread.start()
    yield f"http://127.0.0.1:{http_port}/?ws=ws://127.0.0.1:{ws_server.port}", ws_server
    httpd.shutdown()
    ws_server.stop()


@pytest.fixture(scope="module")
def browser_page(arm_server):
    url, _ = arm_server
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url)
        page.wait_for_function("document.querySelector('#connection-status').textContent === 'connected'")
        yield page
        browser.close()


def test_arm_widget_renders_angle_readout_and_canvas(browser_page):
    page = browser_page
    page.wait_for_selector("#arm-panel")
    page.wait_for_function("document.querySelector('#arm-angle').textContent.includes('45')")

    angle_text = page.text_content("#arm-angle")
    assert "45" in angle_text

    has_drawn = page.evaluate(
        """() => {
            const canvas = document.querySelector('#arm-canvas');
            if (!canvas) return false;
            const ctx = canvas.getContext('2d');
            const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
            for (let i = 0; i < data.length; i += 4) {
                if (data[i] > 0 || data[i+1] > 0 || data[i+2] > 0) return true;
            }
            return false;
        }"""
    )
    assert has_drawn


class _WebSocketFixture:
    def __init__(self, messages):
        self.messages = messages
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.server = None
        self.port = None
        self.clients = set()

    def start(self):
        self.thread.start()
        assert self.ready.wait(5)

    def stop(self):
        self.close_clients()
        if self.server is not None:
            async def _shutdown():
                self.server.close()
                await self.server.wait_closed()

            asyncio.run_coroutine_threadsafe(_shutdown(), self.loop).result(timeout=5)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)

    def close_clients(self):
        async def close_all():
            for client in list(self.clients):
                await client.close()

        if self.loop.is_running():
            asyncio.run_coroutine_threadsafe(close_all(), self.loop).result(timeout=5)

    def _run(self):
        import websockets

        asyncio.set_event_loop(self.loop)

        async def handler(websocket):
            self.clients.add(websocket)
            try:
                for message in self.messages:
                    await websocket.send(protocol.dumps(message))
                    await asyncio.sleep(0.05)
                async for _ in websocket:
                    pass
            finally:
                self.clients.discard(websocket)

        async def start_server():
            self.server = await websockets.serve(handler, "127.0.0.1", 0)
            self.port = self.server.sockets[0].getsockname()[1]
            self.ready.set()

        self.loop.run_until_complete(start_server())
        self.loop.run_forever()
