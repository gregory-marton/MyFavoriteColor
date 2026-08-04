// Live SmartMotor emulator UI.
// Co-authored-by: GPT-5, Aug 2026

import { drawFrame } from "./oled.js";
import { renderArm } from "./arm.js";
import { initInputs } from "./input.js";
import { initTilt } from "./tilt.js";

const MAX_FRAMES = 200;

const els = {
  status: document.querySelector("#connection-status"),
  canvas: document.querySelector("#oled"),
  armCanvas: document.querySelector("#arm-canvas"),
  armAngle: document.querySelector("#arm-angle"),
  text: document.querySelector("#screen-text"),
  raw: document.querySelector("#raw-frame"),
  viewMode: document.querySelector("#view-mode"),
  viewer: document.querySelector("#viewer"),
  copy: document.querySelector("#copy-text"),
  scrub: document.querySelector("#frame-scrub"),
  prev: document.querySelector("#prev-frame"),
  next: document.querySelector("#next-frame"),
  count: document.querySelector("#frame-count"),
  boot: document.querySelector("#boot"),
};

let socket = null;
let reconnectTimer = null;
let reconnectDelayMs = 250;
let frames = [];
let frameIndex = -1;
let latestState = null;

connect();
initInputs({
  send,
  getPot: () => (latestState ? latestState.pot : 2048),
});
initTilt({ send });

els.viewMode.addEventListener("change", () => setViewMode(els.viewMode.value));
els.copy.addEventListener("click", copyText);
els.scrub.addEventListener("input", () => showFrame(parseInt(els.scrub.value, 10)));
els.prev.addEventListener("click", () => stepFrame(-1));
els.next.addEventListener("click", () => stepFrame(1));
els.boot.addEventListener("click", () => send({ type: "boot" }));
document.addEventListener("keydown", (event) => {
  if (event.key === "[") stepFrame(-1);
  if (event.key === "]") stepFrame(1);
});
setViewMode(els.viewMode.value);

function connect() {
  clearTimeout(reconnectTimer);
  setStatus("connecting");
  socket = new WebSocket(webSocketUrl());
  socket.addEventListener("open", () => {
    reconnectDelayMs = 250;
    setStatus("connected");
  });
  socket.addEventListener("message", (event) => handleMessage(JSON.parse(event.data)));
  socket.addEventListener("close", () => scheduleReconnect());
  socket.addEventListener("error", () => {
    setStatus("disconnected");
    socket.close();
  });
}

function scheduleReconnect() {
  setStatus(`disconnected; reconnecting in ${reconnectDelayMs} ms`);
  reconnectTimer = setTimeout(connect, reconnectDelayMs);
  reconnectDelayMs = Math.min(5000, reconnectDelayMs * 2);
}

function webSocketUrl() {
  const params = new URLSearchParams(window.location.search);
  if (params.has("ws")) return params.get("ws");
  if (window.SMOTOR_WS_URL) return window.SMOTOR_WS_URL;
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${window.location.host}/ws`;
}

function handleMessage(message) {
  if (message.type === "frame") {
    pushFrame(message);
  } else if (message.type === "state") {
    updateState(message);
  } else if (message.type === "error") {
    setStatus(`error: ${message.message}`);
  } else if (message.type === "exited" && message.error) {
    setStatus(`exited: ${message.error}`);
  }
}

function updateState(state) {
  latestState = state;
  if (els.armAngle) {
    els.armAngle.textContent = `${(state.angle || 0).toFixed(1)}°`;
  }
  if (els.armCanvas) {
    renderArm(els.armCanvas, state);
  }
}

function pushFrame(frame) {
  const wasAtLatest = frameIndex === -1 || frameIndex === frames.length - 1;
  frames.push(frame);
  if (frames.length > MAX_FRAMES) frames.shift();
  updateScrubber();
  if (wasAtLatest) {
    showFrame(frames.length - 1);
  }
}

function showFrame(index) {
  if (frames.length === 0) return;
  frameIndex = Math.max(0, Math.min(index, frames.length - 1));
  const frame = frames[frameIndex];
  drawFrame(els.canvas, frame.png);
  els.text.textContent = frame.lines.join("\n");
  els.raw.textContent = compactJson(frame);
  els.scrub.value = String(frameIndex);
}

function stepFrame(delta) {
  showFrame(frameIndex + delta);
}

function updateScrubber() {
  els.scrub.max = String(Math.max(0, frames.length - 1));
  els.count.textContent = `${frames.length} frame${frames.length === 1 ? "" : "s"}`;
}

function setViewMode(mode) {
  els.viewer.className = mode;
}

async function copyText() {
  await navigator.clipboard.writeText(els.text.textContent);
}

function send(message) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ v: 1, ...message }));
  }
}

function setStatus(text) {
  els.status.textContent = text;
  els.status.className = `status ${text.startsWith("connected") ? "connected" : "disconnected"}`;
}

function compactJson(value) {
  return JSON.stringify(value);
}
