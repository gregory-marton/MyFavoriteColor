// Clock control & filterable trace log timeline for SmartMotor emulator.
// Co-authored-by: Gemini 3.6 Flash, Aug 2026

export function initClockAndTrace({ send }) {
  const clockPanel = document.querySelector("#clock-panel");
  const tracePanel = document.querySelector("#trace-panel");

  if (clockPanel) {
    const speedSelect = document.querySelector("#clock-speed");
    const pauseBtn = document.querySelector("#clock-pause");
    const readout = document.querySelector("#clock-readout");

    let isPaused = false;

    if (speedSelect) {
      speedSelect.addEventListener("change", (e) => {
        const val = e.target.value;
        isPaused = false;
        if (pauseBtn) pauseBtn.textContent = "Pause";
        if (val === "instant") {
          send({ type: "clock", mode: "instant" });
        } else {
          const speed = parseFloat(val) || 1.0;
          send({ type: "clock", mode: "scaled", speed });
        }
      });
    }

    if (pauseBtn) {
      pauseBtn.addEventListener("click", () => {
        isPaused = !isPaused;
        pauseBtn.textContent = isPaused ? "Resume" : "Pause";
        if (isPaused) {
          send({ type: "clock", mode: "paused" });
        } else {
          const speed = parseFloat(speedSelect ? speedSelect.value : "1") || 1.0;
          send({ type: "clock", mode: "scaled", speed });
        }
      });
    }

    window.__updateClockReadout = (ms) => {
      if (readout) readout.textContent = `Clock: ${ms} ms`;
    };
  }

  if (tracePanel) {
    const filterSelect = document.querySelector("#trace-filter");
    const logList = document.querySelector("#trace-log-list");
    let logs = [];
    let activeFilter = "all";

    if (filterSelect) {
      filterSelect.addEventListener("change", (e) => {
        activeFilter = e.target.value;
        renderLogs();
      });
    }

    window.__pushTraceLog = (entry) => {
      logs.push(entry);
      if (logs.length > 500) logs.shift();
      renderLogs();
    };

    function renderLogs() {
      if (!logList) return;
      logList.innerHTML = "";
      const filtered = logs.filter((item) => {
        if (activeFilter === "all") return true;
        if (activeFilter === "print") return item.kind === "log";
        return item.kind === activeFilter;
      });

      filtered.slice(-100).forEach((item) => {
        const div = document.createElement("div");
        div.className = `trace-item kind-${item.kind || "log"}`;
        const timeStr = item.t != null ? `[${(item.t / 1000).toFixed(1)}ms] ` : "";
        div.textContent = `${timeStr}${item.text || JSON.stringify(item)}`;
        logList.appendChild(div);
      });
      logList.scrollTop = logList.scrollHeight;
    }
  }
}
