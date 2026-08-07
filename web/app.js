// Live SmartMotor emulator UI.
// Co-authored-by: GPT-5, Aug 2026
// Co-authored-by: GPT-5.6-Sol-high, Aug 2026

import { drawFrame } from "./oled.js";
import { renderArm } from "./arm.js";
import { initInputs } from "./input.js";
import { initTilt } from "./tilt.js";
import { initWorldEditor } from "./world.js";
import { initClockAndTrace } from "./clock_trace.js";

const MAX_FRAMES = 200;

const els = {
  status: document.querySelector("#connection-status"),
  connect: document.querySelector("#connect-btn"),
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
  record: document.querySelector("#record-btn"),
  sensorAttached: document.querySelector("#sensor-attached"),
  sensorReading: document.querySelector("#sensor-reading"),
  replaySelect: document.querySelector("#replay-select"),
  replayBtn: document.querySelector("#replay-btn"),
  replayRefreshBtn: document.querySelector("#replay-refresh-btn"),
  replayStatus: document.querySelector("#replay-status"),
};

let socket = null;
let replaySocket = null;
let frames = [];
let frameIndex = -1;
let latestState = null;
let isRecording = false;

const inputs = initInputs({
  send,
  getPot: () => (latestState ? latestState.pot : 2048),
});
const tilt = initTilt({ send });
initWorldEditor({ send });
initClockAndTrace({ send });

els.viewMode.addEventListener("change", () => setViewMode(els.viewMode.value));
els.connect.addEventListener("click", () => {
  if (socket && socket.readyState === WebSocket.OPEN) return;
  connect();
});
els.copy.addEventListener("click", copyText);
els.scrub.addEventListener("input", () => showFrame(parseInt(els.scrub.value, 10)));
els.prev.addEventListener("click", () => stepFrame(-1));
els.next.addEventListener("click", () => stepFrame(1));
els.boot.addEventListener("click", () => send({ type: "boot" }));
if (els.record) {
  els.record.addEventListener("click", () => {
    isRecording = !isRecording;
    send({ type: "record", recording: isRecording });
  });
}
document.addEventListener("keydown", (event) => {
  if (event.key === "[") stepFrame(-1);
  if (event.key === "]") stepFrame(1);
});
setViewMode(els.viewMode.value);

if (els.replaySelect) {
  loadRecordingsList();
  if (els.replayRefreshBtn) els.replayRefreshBtn.addEventListener("click", loadRecordingsList);
  if (els.replayBtn) els.replayBtn.addEventListener("click", startReplay);
}

function loadRecordingsList() {
  fetch("/api/recordings")
    .then((response) => response.json())
    .then((paths) => {
      const previous = els.replaySelect.value;
      els.replaySelect.innerHTML = '<option value="">-- choose a recording --</option>';
      paths.forEach((path) => {
        const option = document.createElement("option");
        option.value = path;
        option.textContent = path;
        els.replaySelect.appendChild(option);
      });
      els.replaySelect.value = previous;
    })
    .catch(() => {
      if (els.replayStatus) els.replayStatus.textContent = "could not list recordings";
    });
}

function startReplay() {
  const path = els.replaySelect.value;
  if (!path) return;
  if (replaySocket) replaySocket.close();

  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
  replaySocket = new WebSocket(`${scheme}//${window.location.host}/replay?path=${encodeURIComponent(path)}`);
  if (els.replayStatus) els.replayStatus.textContent = `replaying ${path}...`;
  if (window.__pushTraceLog) {
    window.__pushTraceLog({ kind: "log", t: 0, text: `-- replaying ${path} --` });
  }
  replaySocket.addEventListener("message", (event) => handleMessage(JSON.parse(event.data)));
  replaySocket.addEventListener("close", () => {
    if (els.replayStatus) els.replayStatus.textContent = `done: ${path}`;
  });
  replaySocket.addEventListener("error", () => {
    if (els.replayStatus) els.replayStatus.textContent = `replay error: ${path}`;
  });
}

function connect() {
  setStatus("connecting");
  socket = new WebSocket(webSocketUrl());
  socket.addEventListener("open", () => {
    setStatus("connected");
    els.connect.textContent = "Connected";
    els.connect.disabled = true;
  });
  socket.addEventListener("message", (event) => handleMessage(JSON.parse(event.data)));
  socket.addEventListener("close", () => {
    setStatus("disconnected");
    els.connect.textContent = "Connect";
    els.connect.disabled = false;
  });
  socket.addEventListener("error", () => {
    setStatus("disconnected");
    els.connect.textContent = "Connect";
    els.connect.disabled = false;
  });
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
  } else if (message.type === "log") {
    if (window.__pushTraceLog) window.__pushTraceLog({ kind: "log", t: message.t, text: message.text });
  } else if (message.type === "trace") {
    if (Array.isArray(message.events)) {
      message.events.forEach((ev) => {
        if (window.__pushTraceLog) {
          window.__pushTraceLog({ ...ev, kind: ev.type, text: formatTraceEvent(ev) });
        }
      });
    }
  } else if (message.type === "error") {
    setStatus(`error: ${message.message}`);
    if (els.replayStatus && message.code === "not_found") els.replayStatus.textContent = message.message;
  } else if (message.type === "exited" && message.error) {
    setStatus(`exited: ${message.error}`);
  }
}

// Readable one-liners for the trace panel -- this is what makes a
// recording's sample-to-sample jitter visible while replaying: every
// FULL_SAMPLE/SUSTAIN_SAMPLE tick scrolls by as a line of real numbers, not
// a JSON blob you'd have to parse by eye.
function formatTraceEvent(ev) {
  const t = ev.t != null ? `t=${ev.t}ms ` : "";
  if (ev.type === "FULL_SAMPLE" || ev.type === "SUSTAIN_SAMPLE" || ev.type === "START_SAMPLE") {
    const accel = ev.accel ? ev.accel.join(",") : "--";
    const battery = ev.battery_v != null ? `${ev.battery_v.toFixed(3)}V` : `${ev.batt_raw}`;
    const parts = [`${t}pot=${ev.pot}`, `batt=${battery}`, `accel=${accel}`];
    if (ev.type === "FULL_SAMPLE") {
      parts.push(`angle=${ev.angle}`, `sensor=${ev.sensor_value}`, `port=${ev.port_mode}`);
    }
    return parts.join(" ");
  }
  if (ev.type === "SCREEN") return `${t}SCREEN ${(ev.lines || []).join(" | ")}`;
  if (ev.type === "SERVO") return `${t}SERVO angle=${ev.angle}`;
  if (ev.type === "BOOT") return `${t}BOOT #${ev.boot_num} (${ev.reset_cause_name})`;
  if (ev.type === "REP" || ev.type === "STAGE_DONE" || ev.type === "TIMEOUT") {
    return `${t}${ev.type} stage=${ev.stage}`;
  }
  return `${t}${ev.type || "event"} ${JSON.stringify(ev)}`;
}

function updateState(state) {
  latestState = state;
  if (inputs) inputs.updateState(state);
  if (tilt) tilt.updateState(state);
  if (state.is_recording != null) {
    isRecording = Boolean(state.is_recording);
    if (els.record) {
      els.record.textContent = isRecording ? "⏹ Stop Recording" : "⏺ Record";
      els.record.className = `btn-record ${isRecording ? "recording" : ""}`;
    }
  }
  if (els.armAngle) {
    els.armAngle.textContent = `${(state.angle || 0).toFixed(1)}°`;
  }
  if (els.sensorAttached) {
    const mode = state.mode || state.attached || "unknown";
    const usb = state.usb == null ? "?" : (state.usb ? "ON" : "OFF");
    const sensor = state.sensor_attached == null ? "?" : (state.sensor_attached ? "YES" : "NO");
    els.sensorAttached.textContent = `Mode: ${mode} | Sensor: ${sensor} | USB: ${usb}`;
  }
  if (els.sensorReading) {
    const sensorValue = state.sensor_rgbw ? state.sensor_rgbw.join(",") : (state.sensor_value == null ? "--" : state.sensor_value);
    const pot = state.pot == null ? "--" : state.pot;
    const angle = state.angle == null ? "--" : Number(state.angle).toFixed(1);
    els.sensorReading.textContent = `Sensor: ${sensorValue} | Pot: ${pot} | Angle: ${angle}°`;
  }
  if (els.armCanvas) {
    renderArm(els.armCanvas, state);
  }
  if (state.clock_ms != null && window.__updateClockReadout) {
    window.__updateClockReadout(state.clock_ms);
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
