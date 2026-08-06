// Gravity/down vector view for the SmartMotor accelerometer.
// Co-authored-by: GPT-5.6-Sol-high, Aug 2026

export function initTilt({ send, canvasId, readoutId }) {
  const canvas = document.querySelector(canvasId || "#tilt-canvas");
  const readout = document.querySelector(readoutId || "#tilt-readout");
  if (!canvas) return;

  let accel = [0, 0, -256];
  render();

  function updateState(state) {
    if (Array.isArray(state.accel) && state.accel.length === 3) {
      accel = state.accel.map(Number);
    } else if (typeof state.roll === "number" && typeof state.pitch === "number") {
      // Compatibility with older bridge messages: reconstruct only a unit
      // gravity direction, never a claimed translational movement.
      const roll = state.roll * Math.PI / 180;
      const pitch = state.pitch * Math.PI / 180;
      accel = [Math.sin(-pitch), Math.sin(roll) * Math.cos(pitch), Math.cos(roll) * Math.cos(pitch)];
    }
    render();
  }

  function render() {
    const ctx = canvas.getContext("2d");
    const w = canvas.width, h = canvas.height;
    const cx = w / 2, cy = h / 2;
    ctx.fillStyle = "#0c1119";
    ctx.fillRect(0, 0, w, h);

    const magnitude = Math.hypot(...accel);
    const scale = magnitude ? 70 / Math.max(256, magnitude) : 0;
    const dx = accel[0] * scale;
    const dy = -accel[1] * scale;
    ctx.strokeStyle = "#38bdf8";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + dx, cy + dy);
    ctx.stroke();
    ctx.fillStyle = "#38bdf8";
    ctx.beginPath();
    ctx.arc(cx + dx, cy + dy, 5, 0, 2 * Math.PI);
    ctx.fill();
    ctx.fillStyle = "#94a3b8";
    ctx.font = "14px sans-serif";
    ctx.fillText("down", cx + dx + 8, cy + dy + 5);
    ctx.fillText("Z (gravity axis)", 10, 20);
    if (readout) {
      readout.textContent = `Down vector: (${accel.map((v) => v.toFixed(1)).join(", ")}) | magnitude ${magnitude.toFixed(1)}`;
    }
  }

  return { updateState };
}
