// 2D side view arm & angle rendering for SmartMotor emulator.
// Co-authored-by: Gemini 3.6 Flash, Aug 2026

export function renderArm(canvas, state) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;

  ctx.fillStyle = "#0c1119";
  ctx.fillRect(0, 0, w, h);

  const cx = w / 2;
  const cy = h * 0.55;
  const armLength = Math.min(w, h) * 0.38;

  // Draw World Arc (0° to 180°, mapped horizontally beneath arm)
  const arcRadius = armLength + 14;
  ctx.lineWidth = 12;

  // Default world surface
  ctx.strokeStyle = (state.world && state.world.default_color) || "#334155";
  ctx.beginPath();
  ctx.arc(cx, cy, arcRadius, Math.PI, 0);
  ctx.stroke();

  // Patch segments
  if (state.world && Array.isArray(state.world.patches)) {
    for (const patch of state.world.patches) {
      const startRad = Math.PI - (patch.from * Math.PI) / 180;
      const endRad = Math.PI - (patch.to * Math.PI) / 180;
      ctx.strokeStyle = patch.color || "#38bdf8";
      ctx.beginPath();
      ctx.arc(cx, cy, arcRadius, startRad, endRad, true);
      ctx.stroke();
    }
  }

  const actualAngle = typeof state.angle === "number" ? state.angle : 0.0;
  const commandedAngle = typeof state.commanded_angle === "number" ? state.commanded_angle : actualAngle;

  // Ghost beam if commanded differs from actual (slew / 2° quantization)
  if (Math.abs(commandedAngle - actualAngle) >= 0.5) {
    drawBeam(ctx, cx, cy, commandedAngle, armLength, "rgba(148, 163, 184, 0.4)", true);
  }

  // Actual LEGO beam
  drawBeam(ctx, cx, cy, actualAngle, armLength, "#38bdf8", false);

  // Hub circle
  ctx.fillStyle = "#1e293b";
  ctx.strokeStyle = "#475569";
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.arc(cx, cy, 16, 0, 2 * Math.PI);
  ctx.fill();
  ctx.stroke();

  // Angle Marker on World Arc
  const markerRad = Math.PI - (actualAngle * Math.PI) / 180;
  const mx = cx + arcRadius * Math.cos(markerRad);
  const my = cy - arcRadius * Math.sin(markerRad);
  ctx.fillStyle = "#ef4444";
  ctx.beginPath();
  ctx.arc(mx, my, 5, 0, 2 * Math.PI);
  ctx.fill();

  // Big Numeric Readout
  ctx.fillStyle = "#e2e8f0";
  ctx.font = "bold 22px ui-monospace, monospace";
  ctx.textAlign = "center";
  ctx.fillText(`${actualAngle.toFixed(1)}°`, cx, h - 14);
}

function drawBeam(ctx, cx, cy, angleDeg, length, color, isGhost) {
  const rad = Math.PI - (angleDeg * Math.PI) / 180;
  const ex = cx + length * Math.cos(rad);
  const ey = cy - length * Math.sin(rad);

  ctx.save();
  ctx.lineWidth = isGhost ? 6 : 10;
  ctx.strokeStyle = color;
  if (isGhost) ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(ex, ey);
  ctx.stroke();
  ctx.restore();
}
