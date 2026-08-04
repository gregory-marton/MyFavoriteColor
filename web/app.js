// SmartMotor session replay player. Loads a trace JSON (built by
// bin/build_trace from a captured guided_log.txt) and steps through it,
// rendering the real OLED pixel buffer, servo angle, battery/USB status,
// and a scrolling event log.

const OLED_W = 128, OLED_H = 64, SCALE = 4;
const canvas = document.getElementById("oled");
const ctx = canvas.getContext("2d");

let events = [];
let idx = 0;
let playing = false;
let lastFrameWallTime = null;
let virtualT = 0; // accumulates across frames -- must not be re-derived from events[idx].t

// Sticky state carried forward between events of different types, so e.g.
// the battery readout still shows the last known value while a SCREEN event
// is being drawn.
let state = {
  usb: null, batteryV: null, pot: null, accel: null, orientation: null, angle: 0,
  colorWb: null, light: {}
};

function decodeScreenBuffer(b64) {
  const raw = atob(b64);
  const buf = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) buf[i] = raw.charCodeAt(i);
  return buf;
}

function drawScreen(buf) {
  const img = ctx.createImageData(OLED_W, OLED_H);
  for (let y = 0; y < OLED_H; y++) {
    for (let x = 0; x < OLED_W; x++) {
      const idx8 = x + Math.floor(y / 8) * OLED_W;
      const bit = (buf[idx8] >> (y % 8)) & 1;
      const p = (y * OLED_W + x) * 4;
      const v = bit ? 255 : 0;
      img.data[p] = v; img.data[p + 1] = bit ? 255 : 20; img.data[p + 2] = v; img.data[p + 3] = 255;
    }
  }
  // draw at native size to an offscreen canvas, then scale up crisply
  const off = document.createElement("canvas");
  off.width = OLED_W; off.height = OLED_H;
  off.getContext("2d").putImageData(img, 0, 0);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(off, 0, 0, OLED_W, OLED_H, 0, 0, OLED_W * SCALE, OLED_H * SCALE);
}

function updatePanel() {
  document.getElementById("usb-badge").textContent = state.usb === null ? "unknown" : (state.usb ? "connected" : "disconnected");
  document.getElementById("usb-badge").className = state.usb ? "usb-on" : "usb-off";
  document.getElementById("batt-v").textContent = state.batteryV === null ? "--" : state.batteryV.toFixed(3);
  document.getElementById("pot-v").textContent = state.pot === null ? "--" : state.pot;
  document.getElementById("pot-bar-fill").style.width = state.pot === null ? "0%" : `${(state.pot / 4095) * 100}%`;
  document.getElementById("accel-v").textContent = state.accel === null ? "--" : state.accel.join(",");
  document.getElementById("orientation-v").textContent = state.orientation === null ? "--" :
    `roll ${state.orientation.roll.toFixed(1)}°, pitch ${state.orientation.pitch.toFixed(1)}°`;
  document.getElementById("color-wb-v").textContent = state.colorWb === null ? "--" : state.colorWb.join(",");
  const lightParts = [];
  if (state.light.LIGHT_DARK !== undefined) lightParts.push(`dark ${state.light.LIGHT_DARK}`);
  if (state.light.LIGHT_BRIGHT !== undefined) lightParts.push(`bright ${state.light.LIGHT_BRIGHT}`);
  document.getElementById("light-v").textContent = lightParts.length === 0 ? "--" : lightParts.join(" / ");
  document.getElementById("arm-needle").style.transform = `translate(-50%, 0) rotate(${state.angle - 90}deg)`;
}

function flashButton(elId) {
  const el = document.getElementById(elId);
  el.classList.add("pressed");
  clearTimeout(el._flashTimer);
  el._flashTimer = setTimeout(() => el.classList.remove("pressed"), 400);
}

function logLine(text, highlight) {
  const log = document.getElementById("log");
  const div = document.createElement("div");
  if (highlight) div.className = "hi";
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

function applyEvent(e) {
  document.getElementById("t-v").textContent = e.t;
  if (e.type === "SCREEN") {
    drawScreen(decodeScreenBuffer(e.screen_buffer_b64));
    logLine(`[${e.t}] SCREEN: ${e.lines.join(" / ")}`);
    // the pot stages' own display text embeds the live raw reading
    // ("POT x3  v=1234") -- reuse it rather than needing new device logging.
    for (const line of e.lines) {
      const m = line.match(/v=(\d+)/);
      if (m) state.pot = parseInt(m[1], 10);
    }
  } else if (e.type === "SERVO") {
    state.angle = e.angle;
  } else if (e.type === "SUSTAIN_SAMPLE" || e.type === "START_SAMPLE") {
    state.usb = e.on_usb;
    state.batteryV = e.battery_v === undefined ? e.batt_uv / 1e6 : e.battery_v;
    state.pot = e.pot;
    state.accel = e.accel;
    state.orientation = e.orientation;
  } else if (e.type === "BOOT") {
    logLine(`[${e.t}] BOOT #${e.boot_num} (${e.reset_cause_name})`, true);
  } else if (e.type === "ACCEL_SUMMARY") {
    logLine(`[${e.t}] ${e.stage}: ${e.status} (${e.summary})`, e.status !== "pass");
  } else if (e.type === "COLOR_WHITE_SUMMARY") {
    state.colorWb = e.white_balance_milli;
    logLine(`[${e.t}] COLOR_WHITE wb=${e.white_balance_milli.join(",")}`, true);
  } else if (e.type === "LIGHT_SUMMARY") {
    state.light[e.stage] = e.mean;
    logLine(`[${e.t}] ${e.stage}: mean=${e.mean}`, true);
  } else if (e.type === "REP") {
    logLine(`[${e.t}] REP ${e.stage}`);
    if (e.stage.startsWith("UP")) flashButton("btn-up");
    if (e.stage.startsWith("DOWN")) flashButton("btn-down");
    if (e.stage.startsWith("SELECT")) flashButton("btn-select");
  } else if (e.type === "STAGE_DONE") {
    logLine(`[${e.t}] STAGE_DONE ${e.stage}`, true);
  } else if (e.type === "TIMEOUT") {
    logLine(`[${e.t}] TIMEOUT ${e.stage}`, true);
  }
  updatePanel();
}

function seekTo(targetIdx) {
  // re-derive sticky state by replaying from the start -- simplest correct
  // way to scrub backward, and the trace sizes here don't need speed.
  state = {
    usb: null, batteryV: null, pot: null, accel: null, orientation: null, angle: 0,
    colorWb: null, light: {}
  };
  document.getElementById("log").innerHTML = "";
  for (let i = 0; i <= targetIdx && i < events.length; i++) applyEvent(events[i]);
  idx = targetIdx;
  virtualT = events[idx] ? events[idx].t : 0;
  document.getElementById("scrub").value = idx;
}

function tick(nowMs) {
  if (!playing) return;
  if (lastFrameWallTime === null) lastFrameWallTime = nowMs;
  const speed = parseFloat(document.getElementById("speed").value);
  virtualT += (nowMs - lastFrameWallTime) * speed;
  lastFrameWallTime = nowMs;

  while (idx < events.length - 1 && events[idx + 1].t <= virtualT) {
    idx++;
    applyEvent(events[idx]);
  }
  document.getElementById("scrub").value = idx;
  if (idx >= events.length - 1) { playing = false; return; }
  requestAnimationFrame(tick);
}

document.getElementById("play").addEventListener("click", () => {
  if (events.length === 0) return;
  playing = true;
  lastFrameWallTime = null;
  requestAnimationFrame(tick);
});
document.getElementById("pause").addEventListener("click", () => { playing = false; });
document.getElementById("scrub").addEventListener("input", (ev) => {
  playing = false;
  seekTo(parseInt(ev.target.value, 10));
});

fetch("trace.json")
  .then((r) => r.json())
  .then((data) => {
    events = data.events;
    document.getElementById("scrub").max = Math.max(0, events.length - 1);
    if (events.length > 0) seekTo(0);
  });
