// Keyboard and control inputs for SmartMotor emulator.
// Co-authored-by: Gemini 3.6 Flash, Aug 2026
// Co-authored-by: GPT-5, Aug 2026
// Co-authored-by: GPT-5.6-Sol-high, Aug 2026

export function initInputs({ send, getPot, setPot }) {
  let stickyMode = false;
  let powerOn = true;
  let potValue = getPot ? getPot() : 2048;
  const activeButtons = new Set();
  let potRepeatTimer = null;

  const els = {
    up: document.querySelector("#btn-up"),
    down: document.querySelector("#btn-down"),
    select: document.querySelector("#btn-select"),
    pot: document.querySelector("#pot-slider"),
    potVal: document.querySelector("#pot-val"),
    power: document.querySelector("#power-toggle"),
    sticky: document.querySelector("#sticky-mode"),
  };

  // Keyboard Event Listeners
  document.addEventListener("keydown", (event) => {
    if (shouldIgnoreKeyboard(event)) return;

    if (event.key === "ArrowUp") {
      event.preventDefault();
      if (!activeButtons.has("up")) {
        activeButtons.add("up");
        pressButton("up");
      }
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!activeButtons.has("down")) {
        activeButtons.add("down");
        pressButton("down");
      }
    } else if (event.key === " " || event.code === "Space") {
      event.preventDefault();
      if (!activeButtons.has("select")) {
        activeButtons.add("select");
        pressButton("select");
      }
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      adjustPot(-40);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      adjustPot(40);
    } else if (event.key === "~" || event.key === "`") {
      event.preventDefault();
      togglePower();
    } else if (event.key === "!") {
      event.preventDefault();
      sendMsg({ type: "detach" });
    }
  });

  document.addEventListener("keyup", (event) => {
    if (shouldIgnoreKeyboard(event)) return;

    if (event.key === "ArrowUp") {
      activeButtons.delete("up");
      releaseButton("up");
    } else if (event.key === "ArrowDown") {
      activeButtons.delete("down");
      releaseButton("down");
    } else if (event.key === " " || event.code === "Space") {
      activeButtons.delete("select");
      releaseButton("select");
    }
  });

  // On-Screen Button Listeners
  bindButton(els.up, "up");
  bindButton(els.down, "down");
  bindButton(els.select, "select");

  if (els.pot) {
    els.pot.addEventListener("input", (e) => {
      potValue = parseInt(e.target.value, 10);
      updatePotDisplay();
      sendMsg({ type: "set_pot", raw: potValue });
    });
  }

  if (els.power) {
    els.power.addEventListener("click", togglePower);
  }

  if (els.sticky) {
    els.sticky.addEventListener("change", (e) => {
      stickyMode = e.target.checked;
    });
  }

  function updateState(state) {
    if (state.pot != null) {
      potValue = Number(state.pot);
      if (els.pot) els.pot.value = String(potValue);
      updatePotDisplay();
    }
    if (state.buttons) {
      for (const name of ["up", "down", "select"]) {
        setButtonVisual(name, Boolean(state.buttons[name]));
      }
    }
  }

  function bindButton(el, name) {
    if (!el) return;
    el.addEventListener("mousedown", (e) => {
      e.preventDefault();
      if (stickyMode) {
        if (activeButtons.has(name)) {
          activeButtons.delete(name);
          releaseButton(name);
        } else {
          activeButtons.add(name);
          pressButton(name);
        }
      } else {
        activeButtons.add(name);
        pressButton(name);
      }
    });

    el.addEventListener("mouseup", (e) => {
      e.preventDefault();
      if (!stickyMode && activeButtons.has(name)) {
        activeButtons.delete(name);
        releaseButton(name);
      }
    });
  }

  function pressButton(name) {
    setButtonVisual(name, true);
    sendMsg({ type: "press", button: name });
  }

  function releaseButton(name) {
    setButtonVisual(name, false);
    sendMsg({ type: "release", button: name });
  }

  function setButtonVisual(name, isPressed) {
    const btn = els[name];
    if (btn) {
      if (isPressed) btn.classList.add("pressed");
      else btn.classList.remove("pressed");
    }
  }

  function adjustPot(delta) {
    potValue = Math.max(0, Math.min(4095, potValue + delta));
    if (els.pot) els.pot.value = String(potValue);
    updatePotDisplay();
    sendMsg({ type: "set_pot", raw: potValue });
  }

  function updatePotDisplay() {
    if (els.potVal) els.potVal.textContent = String(potValue);
  }

  function togglePower() {
    powerOn = !powerOn;
    if (els.power) {
      els.power.textContent = powerOn ? "Power ON" : "Power OFF";
      els.power.className = powerOn ? "btn-power on" : "btn-power off";
    }
    sendMsg({ type: "power", on: powerOn });
  }

  function sendMsg(msg) {
    window.__last_sent = msg;
    send(msg);
  }

  return { updateState };
}

function shouldIgnoreKeyboard(event) {
  const tag = event.target.tagName;
  return tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA";
}
