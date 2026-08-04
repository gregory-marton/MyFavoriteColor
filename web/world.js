// World editor for SmartMotor emulator.
// Co-authored-by: Gemini 3.6 Flash, Aug 2026

export function initWorldEditor({ send }) {
  const panel = document.querySelector("#world-editor-panel");
  if (!panel) return;

  const presetSelect = document.querySelector("#preset-select");
  const ambientInput = document.querySelector("#ambient-lux");
  const patchesContainer = document.querySelector("#patches-list");
  const addPatchBtn = document.querySelector("#add-patch");
  const downloadBtn = document.querySelector("#download-world");
  const uploadInput = document.querySelector("#upload-world");

  let ambientLux = 300;
  let patches = getPreset("three_patches");

  if (presetSelect) {
    presetSelect.addEventListener("change", (e) => {
      const preset = e.target.value;
      if (preset && PRESETS[preset]) {
        patches = [...PRESETS[preset]];
        renderPatches();
        emitWorld();
      }
    });
  }

  if (ambientInput) {
    ambientInput.addEventListener("input", (e) => {
      ambientLux = parseInt(e.target.value, 10) || 300;
      emitWorld();
    });
  }

  if (addPatchBtn) {
    addPatchBtn.addEventListener("click", () => {
      const lastEnd = patches.length > 0 ? patches[patches.length - 1].to : 0;
      const newStart = Math.min(170, lastEnd);
      const newEnd = Math.min(180, newStart + 20);
      patches.push({ from: newStart, to: newEnd, color: "#38bdf8", name: `patch_${patches.length + 1}` });
      renderPatches();
      emitWorld();
    });
  }

  if (downloadBtn) {
    downloadBtn.addEventListener("click", () => {
      const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(getWorldPayload(), null, 2));
      const downloadAnchor = document.createElement("a");
      downloadAnchor.setAttribute("href", dataStr);
      downloadAnchor.setAttribute("download", "world.json");
      document.body.appendChild(downloadAnchor);
      downloadAnchor.click();
      downloadAnchor.remove();
    });
  }

  if (uploadInput) {
    uploadInput.addEventListener("change", (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (event) => {
        try {
          const parsed = JSON.parse(event.target.result);
          const data = parsed.world || parsed;
          if (typeof data.ambient_lux === "number") ambientLux = data.ambient_lux;
          if (Array.isArray(data.patches)) patches = data.patches;
          if (ambientInput) ambientInput.value = String(ambientLux);
          renderPatches();
          emitWorld();
        } catch (err) {
          console.error("Failed to parse world JSON:", err);
        }
      };
      reader.readAsText(file);
    });
  }

  renderPatches();

  function renderPatches() {
    if (!patchesContainer) return;
    patchesContainer.innerHTML = "";
    patches.forEach((patch, index) => {
      const row = document.createElement("div");
      row.className = "patch-row";

      row.innerHTML = `
        <input type="color" class="patch-color" value="${patch.color || "#ffffff"}">
        <label>From <input type="number" class="patch-from" min="0" max="180" value="${patch.from}"></label>
        <label>To <input type="number" class="patch-to" min="0" max="180" value="${patch.to}"></label>
        <button type="button" class="patch-del">✕</button>
      `;

      const colorInput = row.querySelector(".patch-color");
      const fromInput = row.querySelector(".patch-from");
      const toInput = row.querySelector(".patch-to");
      const delBtn = row.querySelector(".patch-del");

      colorInput.addEventListener("input", (e) => {
        patches[index].color = e.target.value;
        emitWorld();
      });

      fromInput.addEventListener("change", (e) => {
        patches[index].from = parseFloat(e.target.value) || 0;
        emitWorld();
      });

      toInput.addEventListener("change", (e) => {
        patches[index].to = parseFloat(e.target.value) || 0;
        emitWorld();
      });

      delBtn.addEventListener("click", () => {
        patches.splice(index, 1);
        renderPatches();
        emitWorld();
      });

      patchesContainer.appendChild(row);
    });
  }

  function getWorldPayload() {
    return {
      ambient_lux: ambientLux,
      default_color: "#ffffff",
      blur_deg: 3,
      patches: patches.map((p) => ({
        from: p.from,
        to: p.to,
        color: p.color,
        name: p.name || "",
      })),
    };
  }

  function emitWorld() {
    const payload = getWorldPayload();
    const msg = { type: "set_world", world: payload };
    window.__last_sent = msg;
    send(msg);
  }
}

const PRESETS = {
  three_patches: [
    { from: 0, to: 60, color: "#ff0000", name: "red" },
    { from: 60, to: 120, color: "#ffffff", name: "white" },
    { from: 120, to: 180, color: "#0000ff", name: "blue" },
  ],
  rainbow: [
    { from: 0, to: 30, color: "#ef4444", name: "red" },
    { from: 30, to: 60, color: "#f97316", name: "orange" },
    { from: 60, to: 90, color: "#eab308", name: "yellow" },
    { from: 90, to: 120, color: "#22c55e", name: "green" },
    { from: 120, to: 150, color: "#3b82f6", name: "blue" },
    { from: 150, to: 180, color: "#a855f7", name: "violet" },
  ],
};

function getPreset(name) {
  return [...(PRESETS[name] || PRESETS.three_patches)];
}
