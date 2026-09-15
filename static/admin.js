const announcementForm = document.querySelector("#announcement-form");
const hintHistory = document.querySelector("#hint-history");
const status = document.querySelector("#status");
const currentAnnouncement = document.querySelector("#current-announcement");
const currentAnnouncementMessage = document.querySelector("#current-announcement-message");
const currentAnnouncementImage = document.querySelector("#current-announcement-image");
const currentAnnouncementVideo = document.querySelector("#current-announcement-video");
const cancelAnnouncementForm = document.querySelector("#cancel-announcement-form");
const previewDialog = document.querySelector("#preview-dialog");
const completionDialog = document.querySelector("#completion-dialog");
const completionForm = document.querySelector("#completion-form");
const completionTime = document.querySelector("#completion-time");
const gpioPauseButton = document.querySelector("#toggle-gpio-pause");
const timerPauseButton = document.querySelector("#toggle-timer-pause");
const activeTimerState = document.querySelector("#active-timer-state");
const activeTimerElapsed = document.querySelector("#active-timer-elapsed");
const activeTimerRemaining = document.querySelector("#active-timer-remaining");
const actionLogList = document.querySelector("#action-log-list");
const actionLogStorageKey = "admin-action-log-cache";
const adminDom = window.AdminDom;
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
  if (!response.ok) throw new Error(payload.error || window.translate("js.request_failed"));
  return payload;
}

function loadActionLogCache() {
  if (!actionLogList) return;
  try {
    const cached = JSON.parse(localStorage.getItem(actionLogStorageKey) || "null");
    if (Array.isArray(cached)) {
      adminDom.renderActionLog(actionLogList, cached);
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
  adminDom.renderActionLog(actionLogList, []);
}

function updateActiveTimerDisplay() {
  if (!activeTimerState || !activeTimerElapsed || !activeTimerRemaining) return;
  if (!activeTimerSnapshot || !activeTimerSnapshot.timer_started_at) {
    activeTimerState.textContent = window.translate("js.timer_not_running");
    activeTimerElapsed.textContent = window.translate("js.elapsed", { value: "—" });
    activeTimerRemaining.textContent = window.translate("js.remaining", { value: "—" });
    return;
  }
  const startedAt = new Date(activeTimerSnapshot.timer_started_at);
  const completedAt = activeTimerSnapshot.room_completed_at || activeTimerSnapshot.timer_paused_at
    ? new Date(activeTimerSnapshot.room_completed_at || activeTimerSnapshot.timer_paused_at)
    : new Date();
  const extraTimeSeconds = Number(activeTimerSnapshot.extra_time_seconds || 0);
  const penaltyTimeSeconds = Number(activeTimerSnapshot.penalty_time_seconds || 0);
  const elapsedSeconds = Math.max(0, Math.floor((completedAt - startedAt) / 1000)) + penaltyTimeSeconds;
  const remainingSeconds = Math.max(0, (3600 + extraTimeSeconds) - elapsedSeconds);
  activeTimerState.textContent = activeTimerSnapshot.room_completed_at
    ? window.translate("js.timer_completed")
    : window.translate("js.timer_running");
  activeTimerElapsed.textContent = window.translate("js.elapsed", {
    value: adminDom.formatClockDuration(elapsedSeconds),
  });
  activeTimerRemaining.textContent = window.translate("js.remaining", {
    value: adminDom.formatClockDuration(remainingSeconds),
  });
}

async function refreshActiveTimer() {
  if (!activeTimerState || !activeTimerElapsed || !activeTimerRemaining) return;
  try {
    const response = await fetch("/api/display", { credentials: "same-origin" });
    if (!response.ok) throw new Error(window.translate("js.failed_to_fetch_timer"));
    const payload = await response.json();
    activeTimerSnapshot = {
      timer_started_at: payload.timer_started_at,
      timer_paused_at: payload.timer_paused_at,
      room_completed_at: payload.room_completed_at,
      extra_time_seconds: payload.extra_time_seconds,
      penalty_time_seconds: payload.penalty_time_seconds,
    };
    updateActiveTimerDisplay();
  } catch (error) {
    console.warn("refreshActiveTimer error", error);
  }
}

function setStatusText(text) {
  if (status) {
    status.textContent = text;
  }
}

function setCompletionMessage(text) {
  if (completionTime) {
    completionTime.textContent = text;
  }
}

function updateActiveTimerSnapshot(settings) {
  activeTimerSnapshot = {
    timer_started_at: settings.timer_started_at,
    timer_paused_at: settings.timer_paused_at,
    room_completed_at: settings.room_completed_at,
    extra_time_seconds: settings.extra_time_seconds,
    penalty_time_seconds: settings.penalty_time_seconds,
  };
}

function updateCurrentAnnouncement(settings) {
  if (
    !currentAnnouncement
    || !currentAnnouncementMessage
    || !currentAnnouncementImage
    || !currentAnnouncementVideo
  ) {
    return;
  }

  const hasAnnouncement = Boolean(
    settings.announcement || settings.announcement_media_filename,
  );
  currentAnnouncement.hidden = !hasAnnouncement;
  if (!hasAnnouncement) {
    currentAnnouncementVideo.pause();
    return;
  }

  currentAnnouncementMessage.textContent = settings.announcement || "";
  if (settings.announcement_media_type === "image") {
    currentAnnouncementImage.src = `/uploads/${encodeURIComponent(
      settings.announcement_media_filename,
    )}`;
    currentAnnouncementImage.hidden = false;
    currentAnnouncementVideo.hidden = true;
    currentAnnouncementVideo.removeAttribute("src");
    return;
  }

  if (settings.announcement_media_type === "video") {
    currentAnnouncementVideo.src = `/uploads/${encodeURIComponent(
      settings.announcement_media_filename,
    )}`;
    currentAnnouncementVideo.hidden = false;
    currentAnnouncementImage.hidden = true;
    currentAnnouncementImage.removeAttribute("src");
    return;
  }

  currentAnnouncementImage.hidden = true;
  currentAnnouncementImage.removeAttribute("src");
  currentAnnouncementVideo.hidden = true;
  currentAnnouncementVideo.removeAttribute("src");
}

function initCancelAnnouncementForm() {
  if (!cancelAnnouncementForm) return;

  cancelAnnouncementForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const settings = await post("/admin/announcement/cancel");
      updateCurrentAnnouncement(settings);
      setStatusText(window.translate("js.announcement_cancelled"));
      refreshActions();
    } catch (error) {
      setStatusText(error.message);
    }
  });
}

function initGpioPauseButton() {
  if (!gpioPauseButton) return;

  gpioPauseButton.addEventListener("click", async () => {
    try {
      const response = await post("/admin/gpio/pause", {
        paused: gpioPauseButton.dataset.paused !== "true",
      });
      const paused = response.paused;
      gpioPauseButton.dataset.paused = String(paused);
      gpioPauseButton.classList.toggle("btn-paused", paused);
      gpioPauseButton.classList.toggle("btn-active", !paused);
      gpioPauseButton.textContent = window.translate(
        paused ? "js.resume_room_input" : "js.pause_room_input",
      );
      setStatusText(window.translate(
        paused ? "js.room_input_paused" : "js.room_input_active",
      ));
      refreshActions();
    } catch (error) {
      setStatusText(error.message);
    }
  });
}

function updateTimerPauseButton(settings) {
  if (!timerPauseButton) return;
  const paused = Boolean(settings.timer_paused_at);
  timerPauseButton.dataset.paused = String(paused);
  timerPauseButton.classList.toggle("btn-paused", paused);
  timerPauseButton.classList.toggle("btn-active", !paused);
  timerPauseButton.textContent = window.translate(
    paused ? "js.resume_timer" : "js.pause_timer",
  );
}

function initTimerPauseButton() {
  if (!timerPauseButton) return;

  timerPauseButton.addEventListener("click", async () => {
    try {
      const settings = await post("/admin/timer/pause");
      updateTimerPauseButton(settings);
      updateActiveTimerSnapshot(settings);
      updateActiveTimerDisplay();
      setStatusText(window.translate(
        settings.timer_paused_at ? "js.timer_paused" : "js.timer_resumed",
      ));
      refreshActions();
    } catch (error) {
      setStatusText(error.message);
    }
  });
}

function initGpioButtons() {
  document.querySelectorAll("[data-gpio]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await post(`/admin/gpio/${button.dataset.gpio}/${button.dataset.state}`);
        setStatusText(`${button.dataset.gpio} turned ${button.dataset.state}.`);
      } catch (error) {
        setStatusText(error.message);
      }
    });
  });
}

function initGpioOutputActionButtons() {
  document.querySelectorAll("[data-gpio-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        const action = await post(`/admin/gpio/actions/${button.dataset.gpioAction}/trigger`);
        const target = action.pin == null ? action.output_name : `BCM ${action.pin}`;
        setStatusText(window.translate("js.gpio_action_triggered", {
          label: action.label,
          output: target,
          state: window.translate(
            action.state === "on" ? "js.output_on" : "js.output_off",
          ),
        }));
      } catch (error) {
        setStatusText(error.message);
      }
    });
  });
}

function initTimerActionButtons() {
  document.querySelectorAll("[data-timer-action]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.preventDefault();
      try {
        const settings = await post(`/admin/timer/${button.dataset.timerAction}`);
        setStatusText(
          button.dataset.timerAction === "start"
            ? window.translate("js.timer_started")
            : window.translate("js.timer_reset"),
        );
        clearActionLogCache();
        updateActiveTimerSnapshot(settings);
        updateActiveTimerDisplay();
        refreshActiveTimer();
        refreshHints();
        refreshActions();
      } catch (error) {
        setStatusText(error.message);
      }
    });
  });
}

function initTimerAdjustButtons() {
  document.querySelectorAll("[data-adjust]").forEach((button) => {
    button.addEventListener("click", async () => {
      const seconds = Number(button.dataset.adjust);
      try {
        await post("/admin/timer/adjust", { seconds });
        setStatusText(
          seconds >= 0
            ? window.translate("js.added_seconds_total", { seconds })
            : window.translate("js.added_seconds_taken", { seconds: -seconds }),
        );
        refreshHints();
        refreshActions();
        refreshActiveTimer();
      } catch (err) {
        setStatusText(err.message);
      }
    });
  });
}

function initTimerAdjustForm() {
  const timerAdjustForm = document.querySelector("#timer-adjust-form");
  if (!timerAdjustForm) return;

  timerAdjustForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const secondsField = document.querySelector("#timer-adjust-seconds");
    const seconds = Number(secondsField.value);
    if (!Number.isFinite(seconds)) {
      setStatusText(window.translate("js.valid_seconds"));
      return;
    }
    try {
      await post("/admin/timer/adjust", { seconds });
      setStatusText(
        seconds >= 0
          ? window.translate("js.added_seconds_total", { seconds })
          : window.translate("js.added_seconds_taken", { seconds: -seconds }),
      );
      refreshHints();
      refreshActions();
      refreshActiveTimer();
    } catch (err) {
      setStatusText(err.message);
    }
  });
}

function initCompleteRoomButton() {
  const completeRoomButton = document.querySelector("#complete-room");
  if (!completeRoomButton || !completionDialog || !completionTime) return;

  completeRoomButton.addEventListener("click", async (event) => {
    event.preventDefault();
    try {
      const settings = await post("/admin/complete");
      const extraTimeSeconds = Number(settings.extra_time_seconds || 0);
      const penaltyTimeSeconds = Number(settings.penalty_time_seconds || 0);
      const timeTaken = elapsedSeconds(settings.timer_started_at, settings.room_completed_at) + penaltyTimeSeconds;
      const timeRemaining = (3600 + extraTimeSeconds) - timeTaken;
      setCompletionMessage(
        timeRemaining >= 0
          ? window.translate("js.completion_time_left", {
            taken: adminDom.formatDuration(timeTaken),
            remaining: adminDom.formatDuration(timeRemaining),
          })
          : window.translate("js.completion_overtime", {
            taken: adminDom.formatDuration(timeTaken),
            remaining: adminDom.formatDuration(-timeRemaining),
          }),
      );
      completionDialog.showModal();
      updateActiveTimerSnapshot(settings);
      updateActiveTimerDisplay();
      refreshActions();
    } catch (error) {
      setStatusText(error.message);
    }
  });
}

async function sendHint() {
  if (!announcementForm) return;
  if (!announcementForm.reportValidity()) return;
  try {
    const response = await post(
      "/admin/announcement",
      Object.fromEntries(new FormData(announcementForm)),
    );
    appendHint(response.hint);
    updateCurrentAnnouncement(response);
    announcementForm.reset();
    setStatusText(window.translate("js.announcement_sent"));
    refreshActions();
  } catch (error) {
    setStatusText(error.message);
  }
}

function appendHint(hint) {
  if (!hintHistory) return;
  const noHints = document.querySelector("#no-hints");
  if (noHints) noHints.remove();
  hintHistory.append(adminDom.createHintHistoryItem(hint, hintHistory.children.length + 1));
}

async function refreshHints() {
  if (!hintHistory) return;
  try {
    const res = await fetch("/admin/api/hints", { credentials: "same-origin" });
    if (!res.ok) throw new Error("Failed to fetch hints");
    const hints = await res.json();
    adminDom.renderHintHistory(hintHistory, hints);
  } catch (err) {
    console.warn("refreshHints error", err);
  }
}

async function refreshActions() {
  if (!actionLogList) return;
  try {
    const res = await fetch("/admin/api/actions", { credentials: "same-origin" });
    if (!res.ok) throw new Error("Failed to fetch actions");
    const actions = await res.json();
    saveActionLogCache(actions);
    adminDom.renderActionLog(actionLogList, actions);
  } catch (err) {
    console.warn("refreshActions error", err);
  }
}

function elapsedSeconds(startedAt, completedAt) {
  return Math.max(0, Math.floor((new Date(completedAt) - new Date(startedAt)) / 1000));
}

function initHintForm() {
  if (!announcementForm) return;
  announcementForm.addEventListener("submit", (event) => {
    event.preventDefault();
    sendHint();
  });
}

function initHintPresetButton() {
  const hintPresetSelect = document.querySelector("#hint-preset-select");
  const sendHintPresetButton = document.querySelector("#send-hint-preset");
  if (!sendHintPresetButton || !hintPresetSelect) return;

  sendHintPresetButton.addEventListener("click", async () => {
    const presetId = hintPresetSelect.value;
    if (!presetId) {
      setStatusText(window.translate("js.select_hint"));
      return;
    }
    try {
      const response = await post(`/admin/hints/${presetId}/send`, {});
      appendHint(response.hint);
      updateCurrentAnnouncement(response);
      setStatusText(window.translate("js.saved_hint_sent"));
      refreshActions();
    } catch (error) {
      setStatusText(error.message);
    }
  });
}

function initCompletionForm() {
  if (!completionForm || !completionDialog || !completionTime) return;

  completionForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!completionForm.reportValidity()) return;
    try {
      await post("/admin/results", Object.fromEntries(new FormData(completionForm)));
      completionDialog.close();
      setStatusText(window.translate("js.room_result_saved"));
    } catch (error) {
      setCompletionMessage(error.message);
    }
  });
}

function initDialogs() {
  const openPreviewButton = document.querySelector("#open-preview");
  const closePreviewButton = document.querySelector("#close-preview");
  if (openPreviewButton && previewDialog) {
    openPreviewButton.addEventListener("click", () => {
      previewDialog.showModal();
    });
  }
  if (closePreviewButton && previewDialog) {
    closePreviewButton.addEventListener("click", () => {
      previewDialog.close();
    });
  }
}

function initCompletionDialogClose() {
  const closeCompletionButton = document.querySelector("#close-completion");
  if (!closeCompletionButton || !completionDialog) return;

  closeCompletionButton.addEventListener("click", () => {
    completionDialog.close();
  });
}

function initPage() {
  initGpioPauseButton();
  initTimerPauseButton();
  initGpioButtons();
  initGpioOutputActionButtons();
  initTimerActionButtons();
  initTimerAdjustButtons();
  initTimerAdjustForm();
  initCompleteRoomButton();
  initHintForm();
  initHintPresetButton();
  initCancelAnnouncementForm();
  initCompletionForm();
  initDialogs();
  initCompletionDialogClose();
  loadActionLogCache();
  refreshActiveTimer();
  refreshHints();
  refreshActions();
  setInterval(updateActiveTimerDisplay, 1000);
  setInterval(() => {
    refreshActiveTimer();
    refreshHints();
    refreshActions();
  }, 5000);
}

initPage();
