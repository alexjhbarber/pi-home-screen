const announcementForm = document.querySelector("#announcement-form");
const sendHintButton = document.querySelector("#send-hint");
const hintHistory = document.querySelector("#hint-history");
const status = document.querySelector("#status");
const previewDialog = document.querySelector("#preview-dialog");
const completionDialog = document.querySelector("#completion-dialog");
const completionForm = document.querySelector("#completion-form");
const completionTime = document.querySelector("#completion-time");
const controlGrid = document.querySelector("#control-grid");
const editControlsButton = document.querySelector("#edit-controls");
const editControlsHelp = document.querySelector("#edit-controls-help");
const gpioPauseButton = document.querySelector("#toggle-gpio-pause");
const addControlButton = document.querySelector("#add-control");

async function post(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": window.csrfToken,
    },
    body: body ? JSON.stringify(body) : null,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "Request failed.");
  return payload;
}

function restoreControlOrder() {
  if (!controlGrid) return;
  const savedLayout = JSON.parse(localStorage.getItem("admin-control-layout") || "{}");
  const savedOrder = Array.isArray(savedLayout.order) ? savedLayout.order : [];
  const sizes = typeof savedLayout.sizes === "object" && savedLayout.sizes ? savedLayout.sizes : {};
  const cards = new Map(
    [...controlGrid.querySelectorAll("[data-control-id]")].map((card) => [card.dataset.controlId, card]),
  );
  savedOrder.forEach((id) => {
    const card = cards.get(id);
    if (card) {
      controlGrid.append(card);
      cards.delete(id);
    }
  });
  cards.forEach((card) => controlGrid.append(card));
  controlGrid.querySelectorAll("[data-control-id]").forEach((card) => {
    const size = sizes[card.dataset.controlId] || {};
    card.classList.toggle("width-2", size.width === 2);
    card.classList.toggle("height-2", size.height === 2);
  });
}

function saveControlOrder() {
  const cards = [...controlGrid.querySelectorAll("[data-control-id]")];
  const layout = {
    order: cards.map((card) => card.dataset.controlId),
    sizes: Object.fromEntries(cards.map((card) => [
      card.dataset.controlId,
      {
        width: card.classList.contains("width-2") ? 2 : 1,
        height: card.classList.contains("height-2") ? 2 : 1,
      },
    ])),
  };
  localStorage.setItem("admin-control-layout", JSON.stringify(layout));
}

if (controlGrid && editControlsButton && editControlsHelp) {
  let editingControls = false;
  let draggedCard;
  const cards = [...controlGrid.querySelectorAll("[data-control-id]")];

  restoreControlOrder();
  cards.forEach((card) => {
    const editor = document.createElement("div");
    editor.className = "control-card-editor";
    editor.hidden = true;
    const isWide = card.classList.contains("width-2");
    const isTall = card.classList.contains("height-2");
    editor.innerHTML = [
      `<button type="button" data-size="width" aria-pressed="${!isWide}">One column</button>`,
      `<button type="button" data-size="width" data-value="2" aria-pressed="${isWide}">Two columns</button>`,
      `<button type="button" data-size="height" aria-pressed="${!isTall}">Half height</button>`,
      `<button type="button" data-size="height" data-value="2" aria-pressed="${isTall}">Double height</button>`,
    ].join("");
    editor.querySelectorAll("[data-size]").forEach((button) => {
      button.addEventListener("click", () => {
        const isWidth = button.dataset.size === "width";
        const twoPanels = button.dataset.value === "2";
        card.classList.toggle(isWidth ? "width-2" : "height-2", twoPanels);
        editor.querySelectorAll(`[data-size="${button.dataset.size}"]`).forEach((sizeButton) => {
          sizeButton.setAttribute("aria-pressed", String(sizeButton === button));
        });
      });
    });
    card.prepend(editor);

    // If this is the GPIO card, add per-output visibility toggles
    if (card.dataset.controlId === "gpio") {
      const outputsJson = card.dataset.outputs || "[]";
      let outputs = [];
      try { outputs = JSON.parse(outputsJson); } catch (_) { outputs = []; }
      const gpioEditor = document.createElement("div");
      gpioEditor.style.display = "flex";
      gpioEditor.style.flexWrap = "wrap";
      gpioEditor.style.gap = ".4rem";
      outputs.forEach((name) => {
        const id = `gpio-toggle-${name}`;
        const label = document.createElement("label");
        label.style.fontWeight = "400";
        label.innerHTML = `<input type="checkbox" checked data-gpio-name="${name}" id="${id}"> ${name}`;
        gpioEditor.append(label);
      });
      editor.append(gpioEditor);
      gpioEditor.querySelectorAll("[data-gpio-name]").forEach((cb) => {
        cb.addEventListener("change", () => {
          const name = cb.dataset.gpioName;
          const visible = cb.checked;
          const buttonEls = card.querySelectorAll(`[data-gpio]`);
          buttonEls.forEach((btn) => {
            if (btn.dataset.gpio === name) {
              btn.parentElement.style.display = visible ? "flex" : "none";
            }
          });
        });
      });
    }
  });
  editControlsButton.addEventListener("click", () => {
    editingControls = !editingControls;
    controlGrid.classList.toggle("is-editing", editingControls);
    editControlsButton.textContent = editingControls ? "Done editing" : "Edit controls";
    editControlsButton.setAttribute("aria-pressed", String(editingControls));
    editControlsHelp.hidden = !editingControls;
    cards.forEach((card) => {
      card.draggable = editingControls;
      card.querySelector(".control-card-editor").hidden = !editingControls;
    });
    if (!editingControls) saveControlOrder();
  });

  cards.forEach((card) => {
    card.addEventListener("dragstart", () => {
      if (!editingControls) return;
      draggedCard = card;
      card.classList.add("dragging");
    });
    card.addEventListener("dragend", () => {
      card.classList.remove("dragging");
      draggedCard = undefined;
    });
  });
  controlGrid.addEventListener("dragover", (event) => {
    if (!editingControls || !draggedCard) return;
    event.preventDefault();
    const target = event.target.closest("[data-control-id]");
    if (target && target !== draggedCard) {
      const insertAfter = event.clientY > target.getBoundingClientRect().top + target.offsetHeight / 2;
      controlGrid.insertBefore(draggedCard, insertAfter ? target.nextSibling : target);
    }
  });
}

if (gpioPauseButton) {
  gpioPauseButton.addEventListener("click", async () => {
    try {
      const response = await post("/admin/gpio/pause", {
        paused: gpioPauseButton.dataset.paused !== "true",
      });
      gpioPauseButton.dataset.paused = String(response.paused);
      gpioPauseButton.textContent = response.paused ? "Resume GPIO events" : "Pause GPIO events";
      status.textContent = response.paused ? "GPIO events paused." : "GPIO events resumed.";
    } catch (error) {
      status.textContent = error.message;
    }
  });
}

if (addControlButton && controlGrid) {
  addControlButton.addEventListener("click", () => {
    const type = prompt("Control type (button/custom):", "button");
    if (!type) return;
    if (type !== "button" && type !== "custom") {
      alert("Unknown control type.");
      return;
    }
    const label = prompt("Label for the control:", "New control");
    if (!label) return;
    const id = `${type}-${Date.now()}`;
    const card = document.createElement("section");
    card.className = "control-card";
    card.dataset.controlId = id;
    const h2 = document.createElement("h2");
    h2.textContent = label;
    card.append(h2);
    if (type === "button") {
      const action = prompt("POST path for button action (e.g. /admin/some-action):", "");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = label;
      btn.addEventListener("click", async () => {
        if (!action) return;
        try {
          await post(action, {});
          status.textContent = `${label} action sent.`;
        } catch (err) {
          status.textContent = err.message;
        }
      });
      card.append(btn);
    }
    controlGrid.append(card);
    saveControlOrder();
  });
}

document.querySelectorAll("[data-gpio]").forEach((button) => {
  button.addEventListener("click", async () => {
    try {
      await post(`/admin/gpio/${button.dataset.gpio}/${button.dataset.state}`);
      status.textContent = `${button.dataset.gpio} turned ${button.dataset.state}.`;
    } catch (error) {
      status.textContent = error.message;
    }
  });
});

document.querySelectorAll("[data-timer-action]").forEach((button) => {
  button.addEventListener("click", async (event) => {
    event.preventDefault();
    try {
      await post(`/admin/timer/${button.dataset.timerAction}`);
      status.textContent = button.dataset.timerAction === "start"
        ? "60-minute timer started."
        : "Timer reset to 60:00.";
    } catch (error) {
      status.textContent = error.message;
    }
  });
});

const completeRoomButton = document.querySelector("#complete-room");
if (completeRoomButton && completionDialog && completionTime) {
  completeRoomButton.addEventListener("click", async (event) => {
    event.preventDefault();
    try {
      const settings = await post("/admin/complete");
      const timeTaken = elapsedSeconds(settings.timer_started_at, settings.room_completed_at);
      const timeRemaining = 3600 - timeTaken;
      completionTime.textContent = timeRemaining >= 0
        ? `Time taken: ${formatDuration(timeTaken)}. Time left: ${formatDuration(timeRemaining)}.`
        : `Time taken: ${formatDuration(timeTaken)}. Overtime: ${formatDuration(-timeRemaining)}.`;
      completionDialog.showModal();
    } catch (error) {
      status.textContent = error.message;
    }
  });
}

async function sendHint() {
  if (!announcementForm.reportValidity()) return;
  try {
    const response = await post(
      "/admin/announcement",
      Object.fromEntries(new FormData(announcementForm)),
    );
    appendHint(response.hint);
    announcementForm.reset();
    status.textContent = "Announcement sent for 2 minutes.";
  } catch (error) {
    status.textContent = error.message;
  }
}

function appendHint(hint) {
  const noHints = document.querySelector("#no-hints");
  if (noHints) noHints.remove();

  const item = document.createElement("li");
  const count = document.createElement("span");
  const text = document.createElement("span");
  const timestamp = document.createElement("time");
  const timerValue = document.createElement("time");
  count.className = "hint-count";
  count.textContent = `Hint ${hintHistory.children.length + 1}`;
  text.textContent = hint.message;
  timerValue.className = "hint-timer";
  timerValue.dateTime = `PT${hint.timer_remaining_seconds}S`;
  timerValue.textContent = `Timer: ${formatDuration(hint.timer_remaining_seconds)}`;
  timestamp.dateTime = hint.given_at;
  timestamp.textContent = `${hint.given_at} UTC`;
  item.append(count, text, timerValue, timestamp);
  hintHistory.append(item);
}

function elapsedSeconds(startedAt, completedAt) {
  return Math.max(0, Math.floor((new Date(completedAt) - new Date(startedAt)) / 1000));
}

function formatDuration(totalSeconds) {
  const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

sendHintButton.addEventListener("click", sendHint);
announcementForm.addEventListener("submit", (event) => {
  event.preventDefault();
  sendHint();
});

if (completionForm && completionDialog && completionTime) {
  completionForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!completionForm.reportValidity()) return;
    try {
      await post("/admin/results", Object.fromEntries(new FormData(completionForm)));
      completionDialog.close();
      status.textContent = "Room result saved.";
    } catch (error) {
      completionTime.textContent = error.message;
    }
  });
}

document.querySelector("#open-preview").addEventListener("click", () => {
  previewDialog.showModal();
});
document.querySelector("#close-preview").addEventListener("click", () => {
  previewDialog.close();
});
const closeCompletionButton = document.querySelector("#close-completion");
if (closeCompletionButton && completionDialog) {
  closeCompletionButton.addEventListener("click", () => {
    completionDialog.close();
  });
}
