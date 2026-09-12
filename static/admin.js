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
const activeTimerState = document.querySelector("#active-timer-state");
const activeTimerElapsed = document.querySelector("#active-timer-elapsed");
const activeTimerRemaining = document.querySelector("#active-timer-remaining");
const actionLogList = document.querySelector("#action-log-list");
const actionLogStorageKey = "admin-action-log-cache";
let activeTimerSnapshot = null;

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

function formatClockDuration(totalSeconds) {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const hours = String(Math.floor(seconds / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
  const remainingSeconds = String(seconds % 60).padStart(2, "0");
  return `${hours}:${minutes}:${remainingSeconds}`;
}

function renderActionLog(actions) {
  if (!actionLogList) return;
  actionLogList.innerHTML = "";
  if (!Array.isArray(actions) || actions.length === 0) {
    const empty = document.createElement("li");
    empty.id = "no-actions";
    empty.textContent = "No actions recorded for this run.";
    actionLogList.append(empty);
    return;
  }
  actions.forEach((action) => {
    const item = document.createElement("li");
    item.textContent = `${action.created_at} — ${action.action_type}: ${action.description}`;
    actionLogList.append(item);
  });
}

function loadActionLogCache() {
  if (!actionLogList) return;
  try {
    const cached = JSON.parse(localStorage.getItem(actionLogStorageKey) || "null");
    if (Array.isArray(cached)) {
      renderActionLog(cached);
    }
  } catch (error) {
    localStorage.removeItem(actionLogStorageKey);
  }
}

function saveActionLogCache(actions) {
  if (!actionLogList) return;
  localStorage.setItem(actionLogStorageKey, JSON.stringify(actions));
}

function clearActionLogCache() {
  if (!actionLogList) return;
  localStorage.removeItem(actionLogStorageKey);
  renderActionLog([]);
}

function updateActiveTimerDisplay() {
  if (!activeTimerState || !activeTimerElapsed || !activeTimerRemaining) return;
  if (!activeTimerSnapshot || !activeTimerSnapshot.timer_started_at) {
    activeTimerState.textContent = "Timer not running.";
    activeTimerElapsed.textContent = "Elapsed: —";
    activeTimerRemaining.textContent = "Remaining: —";
    return;
  }
  const startedAt = new Date(activeTimerSnapshot.timer_started_at);
  const completedAt = activeTimerSnapshot.room_completed_at
    ? new Date(activeTimerSnapshot.room_completed_at)
    : new Date();
  const extraTimeSeconds = Number(activeTimerSnapshot.extra_time_seconds || 0);
  const penaltyTimeSeconds = Number(activeTimerSnapshot.penalty_time_seconds || 0);
  const elapsedSeconds = Math.max(0, Math.floor((completedAt - startedAt) / 1000)) + penaltyTimeSeconds;
  const remainingSeconds = Math.max(0, (3600 + extraTimeSeconds) - elapsedSeconds);
  activeTimerState.textContent = activeTimerSnapshot.room_completed_at
    ? "Timer completed."
    : "Timer running.";
  activeTimerElapsed.textContent = `Elapsed: ${formatClockDuration(elapsedSeconds)}`;
  activeTimerRemaining.textContent = `Remaining: ${formatClockDuration(remainingSeconds)}`;
}

async function refreshActiveTimer() {
  if (!activeTimerState || !activeTimerElapsed || !activeTimerRemaining) return;
  try {
    const response = await fetch("/api/display", { credentials: "same-origin" });
    if (!response.ok) throw new Error("Failed to fetch timer state.");
    const payload = await response.json();
    activeTimerSnapshot = {
      timer_started_at: payload.timer_started_at,
      room_completed_at: payload.room_completed_at,
      extra_time_seconds: payload.extra_time_seconds,
      penalty_time_seconds: payload.penalty_time_seconds,
    };
    updateActiveTimerDisplay();
  } catch (error) {
    console.warn("refreshActiveTimer error", error);
  }
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
      const paused = response.paused;
      gpioPauseButton.dataset.paused = String(paused);
      gpioPauseButton.classList.toggle('btn-paused', paused);
      gpioPauseButton.classList.toggle('btn-active', !paused);
      gpioPauseButton.textContent = paused ? "Resume room input" : "Pause room input";
      status.textContent = paused ? "Room input paused." : "Room input active.";
      refreshActions();
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
      const settings = await post(`/admin/timer/${button.dataset.timerAction}`);
      status.textContent = button.dataset.timerAction === "start"
        ? "60-minute timer started."
        : "Timer reset to 60:00.";
      clearActionLogCache();
      activeTimerSnapshot = {
        timer_started_at: settings.timer_started_at,
        room_completed_at: settings.room_completed_at,
        extra_time_seconds: settings.extra_time_seconds,
        penalty_time_seconds: settings.penalty_time_seconds,
      };
      updateActiveTimerDisplay();
      refreshActiveTimer();
      refreshHints();
      refreshActions();
    } catch (error) {
      status.textContent = error.message;
    }
  });
});

// Timer adjust buttons
document.querySelectorAll("[data-adjust]").forEach((button) => {
  button.addEventListener("click", async () => {
    const seconds = Number(button.dataset.adjust);
    try {
      await post('/admin/timer/adjust', { seconds });
      status.textContent = seconds >= 0
        ? `Added ${seconds} seconds to total time.`
        : `Added ${-seconds} seconds to time taken.`;
      refreshHints();
      refreshActions();
      refreshActiveTimer();
    } catch (err) {
      status.textContent = err.message;
    }
  });
});

const timerAdjustForm = document.getElementById('timer-adjust-form');
if (timerAdjustForm) {
  timerAdjustForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const secondsField = document.getElementById('timer-adjust-seconds');
    const seconds = Number(secondsField.value);
    if (!Number.isFinite(seconds)) {
      status.textContent = 'Enter a valid number of seconds.';
      return;
    }
    try {
      await post('/admin/timer/adjust', { seconds });
      status.textContent = seconds >= 0
        ? `Added ${seconds} seconds to total time.`
        : `Added ${-seconds} seconds to time taken.`;
      refreshHints();
      refreshActions();
      refreshActiveTimer();
    } catch (err) {
      status.textContent = err.message;
    }
  });
}

const completeRoomButton = document.querySelector("#complete-room");
if (completeRoomButton && completionDialog && completionTime) {
  completeRoomButton.addEventListener("click", async (event) => {
    event.preventDefault();
    try {
      const settings = await post("/admin/complete");
      const extraTimeSeconds = Number(settings.extra_time_seconds || 0);
      const penaltyTimeSeconds = Number(settings.penalty_time_seconds || 0);
      const timeTaken = elapsedSeconds(settings.timer_started_at, settings.room_completed_at) + penaltyTimeSeconds;
      const timeRemaining = (3600 + extraTimeSeconds) - timeTaken;
      completionTime.textContent = timeRemaining >= 0
        ? `Time taken: ${formatDuration(timeTaken)}. Time left: ${formatDuration(timeRemaining)}.`
        : `Time taken: ${formatDuration(timeTaken)}. Overtime: ${formatDuration(-timeRemaining)}.`;
      completionDialog.showModal();
      activeTimerSnapshot = {
        timer_started_at: settings.timer_started_at,
        room_completed_at: settings.room_completed_at,
        extra_time_seconds: settings.extra_time_seconds,
        penalty_time_seconds: settings.penalty_time_seconds,
      };
      updateActiveTimerDisplay();
      refreshActions();
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
    refreshActions();
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
  item.append(count, text);
  if (hint.media_type === "image" && hint.media_filename) {
    const img = document.createElement("img");
    img.className = "hint-media-preview";
    img.src = `/uploads/${hint.media_filename}`;
    img.alt = "Hint image";
    item.append(img);
  } else if (hint.media_type === "video" && hint.media_filename) {
    const video = document.createElement("video");
    video.className = "hint-media-preview";
    video.src = `/uploads/${hint.media_filename}`;
    video.controls = true;
    item.append(video);
  }
  item.append(timerValue, timestamp);
  hintHistory.append(item);
}

async function refreshHints() {
  if (!hintHistory) return;
  try {
    const res = await fetch('/admin/api/hints', { credentials: 'same-origin' });
    if (!res.ok) throw new Error('Failed to fetch hints');
    const hints = await res.json();
    hintHistory.innerHTML = '';
    if (!hints || hints.length === 0) {
      const li = document.createElement('li');
      li.id = 'no-hints';
      li.textContent = 'No hints sent yet.';
      hintHistory.append(li);
      return;
    }
    hints.forEach((h, idx) => {
      const item = document.createElement('li');
      const count = document.createElement('span');
      const text = document.createElement('span');
      const timestamp = document.createElement('time');
      const timerValue = document.createElement('time');
      count.className = 'hint-count';
      count.textContent = `Hint ${idx + 1}`;
      text.textContent = h.message;
      timerValue.className = 'hint-timer';
      timerValue.dateTime = `PT${h.timer_remaining_seconds}S`;
      timerValue.textContent = `Timer: ${formatDuration(h.timer_remaining_seconds)}`;
      timestamp.dateTime = h.given_at;
      timestamp.textContent = `${h.given_at} UTC`;
      item.append(count, text);
      if (h.media_type === 'image' && h.media_filename) {
        const img = document.createElement('img');
        img.className = 'hint-media-preview';
        img.src = `/uploads/${h.media_filename}`;
        img.alt = 'Hint image';
        item.append(img);
      } else if (h.media_type === 'video' && h.media_filename) {
        const video = document.createElement('video');
        video.className = 'hint-media-preview';
        video.src = `/uploads/${h.media_filename}`;
        video.controls = true;
        item.append(video);
      }
      item.append(timerValue, timestamp);
      hintHistory.append(item);
    });
  } catch (err) {
    console.warn('refreshHints error', err);
  }
}

async function refreshActions() {
  if (!actionLogList) return;
  try {
    const res = await fetch('/admin/api/actions', { credentials: 'same-origin' });
    if (!res.ok) throw new Error('Failed to fetch actions');
    const actions = await res.json();
    saveActionLogCache(actions);
    renderActionLog(actions);
  } catch (err) {
    console.warn('refreshActions error', err);
  }
}

function elapsedSeconds(startedAt, completedAt) {
  return Math.max(0, Math.floor((new Date(completedAt) - new Date(startedAt)) / 1000));
}

function formatDuration(totalSeconds) {
  const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

setInterval(updateActiveTimerDisplay, 1000);
setInterval(() => {
  refreshActiveTimer();
  refreshHints();
  refreshActions();
}, 5000);
loadActionLogCache();
refreshActiveTimer();
refreshHints();
refreshActions();

announcementForm.addEventListener("submit", (event) => {
  event.preventDefault();
  sendHint();
});

const hintPresetSelect = document.querySelector("#hint-preset-select");
const sendHintPresetButton = document.querySelector("#send-hint-preset");
if (sendHintPresetButton && hintPresetSelect) {
  sendHintPresetButton.addEventListener("click", async () => {
    const presetId = hintPresetSelect.value;
    if (!presetId) {
      status.textContent = "Select a saved hint first.";
      return;
    }
    try {
      const response = await post(`/admin/hints/${presetId}/send`, {});
      appendHint(response.hint);
      status.textContent = "Saved hint sent for 2 minutes.";
      refreshActions();
    } catch (error) {
      status.textContent = error.message;
    }
  });
}

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
