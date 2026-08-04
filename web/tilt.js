// 2D isometric accelerometer tilt widget for SmartMotor emulator.
// Co-authored-by: Gemini 3.6 Flash, Aug 2026

export function initTilt({ send, canvasId, readoutId }) {
  const canvas = document.querySelector(canvasId || "#tilt-canvas");
  const readout = document.querySelector(readoutId || "#tilt-readout");
  if (!canvas) return;

  let roll = 0;
  let pitch = 0;
  let isDragging = false;
  let lastX = 0;
  let lastY = 0;

  render();

  canvas.addEventListener("mousedown", (e) => {
    isDragging = true;
    lastX = e.clientX;
    lastY = e.clientY;
  });

  window.addEventListener("mousemove", (e) => {
    if (!isDragging) return;
    const dx = e.clientX - lastX;
    const dy = e.clientY - lastY;
    lastX = e.clientX;
    lastY = e.clientY;

    roll = Math.max(-90, Math.min(90, roll + dx * 0.5));
    pitch = Math.max(-90, Math.min(90, pitch - dy * 0.5));
    emitTilt();
  });

  window.addEventListener("mouseup", () => {
    isDragging = false;
  });

  canvas.addEventListener("dblclick", () => {
    roll = 0;
    pitch = 0;
    emitTilt();
  });

  function emitTilt() {
    render();
    const msg = { type: "set_tilt", roll: Math.round(roll * 10) / 10, pitch: Math.round(pitch * 10) / 10 };
    window.__last_sent = msg;
    send(msg);
  }

  function render() {
    const ctx = canvas.getContext("2d");
    const w = canvas.width;
    const h = canvas.height;
    const cx = w / 2;
    const cy = h / 2;

    ctx.fillStyle = "#0c1119";
    ctx.fillRect(0, 0, w, h);

    const rollRad = (roll * Math.PI) / 180;
    const pitchRad = (pitch * Math.PI) / 180;

    // Projected 3D corners of rectangular board
    const bw = 90;
    const bh = 60;
    const corners = [
      { x: -bw, y: -bh, z: 0 },
      { x: bw, y: -bh, z: 0 },
      { x: bw, y: bh, z: 0 },
      { x: -bw, y: bh, z: 0 },
    ];

    const proj = corners.map((pt) => project(pt, rollRad, pitchRad, cx, cy));

    // Draw Board Top Face
    ctx.fillStyle = "#1e293b";
    ctx.strokeStyle = "#38bdf8";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(proj[0].x, proj[0].y);
    for (let i = 1; i < proj.length; i++) ctx.lineTo(proj[i].x, proj[i].y);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();

    // Draw Gravity Vector Arrow from board center
    const gx = Math.sin(rollRad) * 40;
    const gy = -Math.sin(pitchRad) * 40;
    ctx.strokeStyle = "#ef4444";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + gx, cy + gy);
    ctx.stroke();

    // Arrowhead
    ctx.fillStyle = "#ef4444";
    ctx.beginPath();
    ctx.arc(cx + gx, cy + gy, 4, 0, 2 * Math.PI);
    ctx.fill();

    if (readout) {
      readout.textContent = `Roll: ${roll.toFixed(1)}° | Pitch: ${pitch.toFixed(1)}°`;
    }
  }

  function project(pt, rollRad, pitchRad, cx, cy) {
    // 3D rotation matrix for Roll and Pitch
    const x1 = pt.x * Math.cos(rollRad) - pt.y * Math.sin(rollRad);
    const y1 = pt.x * Math.sin(rollRad) + pt.y * Math.cos(rollRad);

    const x2 = x1;
    const y2 = y1 * Math.cos(pitchRad);

    // Isometric projection constant scale
    const isoX = cx + (x2 - y2) * 0.7;
    const isoY = cy + (x2 + y2) * 0.35;
    return { x: isoX, y: isoY };
  }
}
