"""Playwright tests for the live WebSocket SmartMotor UI.

Co-authored-by: GPT-5, Aug 2026
"""

import asyncio
import base64
import http.server
import os
import threading

import pytest

from smotoremu import protocol

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "web")


@pytest.fixture(scope="module")
def live_servers():
    messages = [
        protocol.frame_message(1, _png_pixel(on=True), ["Starting in 2s...", "Press UP to REPL"]),
        protocol.frame_message(2, _png_pixel(on=False), ["Point at WHITE", "SELECT=ok"]),
        protocol.frame_message(3, _png_pixel(on=True), ["Set FAV color", "SELECT=ok"]),
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
def browser_page(live_servers):
    url, _ = live_servers
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(permissions=["clipboard-read", "clipboard-write"])
        page = context.new_page()
        page.goto(url)
        page.wait_for_function("document.querySelector('#connection-status').textContent === 'connected'")
        page.wait_for_function("document.querySelector('#screen-text').textContent.includes('Starting in 2s')")
        yield page
        browser.close()


def test_live_ui_connects_and_renders_oled_text(browser_page):
    page = browser_page

    assert page.text_content("#connection-status") == "connected"
    assert "Starting in 2s" in page.text_content("#screen-text")
    assert "Press UP to REPL" in page.text_content("#screen-text")


def test_oled_canvas_receives_nonblank_frame(browser_page):
    page = browser_page
    has_pixels = page.evaluate(
        """() => {
            const c = document.querySelector('#oled');
            const data = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
            for (let i = 0; i < data.length; i += 4) {
                if (data[i] > 0 || data[i + 1] > 40 || data[i + 2] > 0) return true;
            }
            return false;
        }"""
    )
    assert has_pixels


def test_text_view_is_selectable_and_copy_button_uses_clipboard(browser_page):
    page = browser_page
    page.select_option("#view-mode", "text")
    page.fill("#frame-scrub", "0")
    page.dispatch_event("#frame-scrub", "input")
    expected_text = page.text_content("#screen-text").strip()
    page.click("#copy-text")

    assert page.locator("#screen-text").evaluate("el => getComputedStyle(el).userSelect") != "none"
    assert expected_text in page.evaluate("navigator.clipboard.readText()")


def test_view_modes_toggle_pixels_text_both_and_raw(browser_page):
    page = browser_page

    page.select_option("#view-mode", "pixels")
    assert page.locator("#oled-panel").is_visible()
    assert not page.locator("#text-panel").is_visible()

    page.select_option("#view-mode", "text")
    assert not page.locator("#oled-panel").is_visible()
    assert page.locator("#text-panel").is_visible()

    page.select_option("#view-mode", "both")
    assert page.locator("#oled-panel").is_visible()
    assert page.locator("#text-panel").is_visible()

    page.select_option("#view-mode", "raw")
    assert page.locator("#raw-panel").is_visible()
    assert '"type":"frame"' in page.text_content("#raw-frame")


def test_frame_history_scrubber_and_keyboard_step_through_frames(browser_page):
    page = browser_page

    page.wait_for_function("document.querySelector('#frame-scrub').max === '2'")
    page.fill("#frame-scrub", "0")
    page.dispatch_event("#frame-scrub", "input")
    assert "Starting in 2s" in page.text_content("#screen-text")

    page.keyboard.press("]")
    assert "Point at WHITE" in page.text_content("#screen-text")

    page.keyboard.press("[")
    assert "Starting in 2s" in page.text_content("#screen-text")


def test_connection_state_reports_disconnected_after_socket_close(browser_page, live_servers):
    page = browser_page
    _, ws_server = live_servers

    ws_server.close_clients()

    page.wait_for_function("document.querySelector('#connection-status').textContent.includes('disconnected')")


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


def _png_pixel(on):
    if not on:
        return base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAACklEQVR4nGMAAQAABQABDQottAAAAABJRU5ErkJggg=="
        )
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAACklEQVR4nGP4DwABAQEAG7buVgAAAABJRU5ErkJggg=="
    )
