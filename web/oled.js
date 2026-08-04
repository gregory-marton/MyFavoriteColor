// OLED frame rendering helpers.
// Co-authored-by: GPT-5, Aug 2026

export function drawFrame(canvas, pngBase64) {
  const ctx = canvas.getContext("2d");
  const img = new Image();
  img.onload = () => {
    ctx.imageSmoothingEnabled = false;
    ctx.fillStyle = "#000814";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    drawPixelGrid(ctx, canvas.width, canvas.height);
  };
  img.src = `data:image/png;base64,${pngBase64}`;
}

function drawPixelGrid(ctx, width, height) {
  ctx.save();
  ctx.strokeStyle = "rgba(80, 180, 255, 0.08)";
  ctx.lineWidth = 1;
  for (let x = 0; x <= width; x += 4) {
    ctx.beginPath();
    ctx.moveTo(x + 0.5, 0);
    ctx.lineTo(x + 0.5, height);
    ctx.stroke();
  }
  for (let y = 0; y <= height; y += 4) {
    ctx.beginPath();
    ctx.moveTo(0, y + 0.5);
    ctx.lineTo(width, y + 0.5);
    ctx.stroke();
  }
  ctx.restore();
}
