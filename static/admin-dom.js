window.AdminDom = (() => {
  function buildUploadUrl(filename) {
    return `/uploads/${encodeURIComponent(filename)}`;
  }

  function formatClockDuration(totalSeconds) {
    const seconds = Math.max(0, Math.floor(totalSeconds));
    const hours = String(Math.floor(seconds / 3600)).padStart(2, "0");
    const minutes = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
    const remainingSeconds = String(seconds % 60).padStart(2, "0");
    return `${hours}:${minutes}:${remainingSeconds}`;
  }

  function formatDuration(totalSeconds) {
    const negative = totalSeconds < 0;
    const seconds = Math.abs(Math.floor(totalSeconds));
    const minutes = String(Math.floor(seconds / 60)).padStart(2, "0");
    const remainingSeconds = String(seconds % 60).padStart(2, "0");
    return `${negative ? "-" : ""}${minutes}:${remainingSeconds}`;
  }

  function createHintHistoryItem(hint, index) {
    const item = document.createElement("li");
    const count = document.createElement("span");
    const text = document.createElement("span");
    const timestamp = document.createElement("time");
    const timerValue = document.createElement("time");

    count.className = "hint-count";
    count.textContent = window.translate("js.hint_number", { number: index });
    text.textContent = hint.message;
    timerValue.className = "hint-timer";
    timerValue.dateTime = `PT${hint.timer_remaining_seconds}S`;
    timerValue.textContent = window.translate("js.timer_value", {
      value: formatDuration(hint.timer_remaining_seconds),
    });
    timestamp.dateTime = hint.given_at;
    timestamp.textContent = window.translate("js.utc", { value: hint.given_at });
    item.append(count, text);

    if (hint.media_type === "image" && hint.media_filename) {
      const image = document.createElement("img");
      image.className = "hint-media-preview";
      image.src = buildUploadUrl(hint.media_filename);
      image.alt = window.translate("js.hint_image");
      item.append(image);
    } else if (hint.media_type === "video" && hint.media_filename) {
      const video = document.createElement("video");
      video.className = "hint-media-preview";
      video.src = buildUploadUrl(hint.media_filename);
      video.controls = true;
      item.append(video);
    }

    item.append(timerValue, timestamp);
    return item;
  }

  function renderHintHistory(container, hints) {
    container.innerHTML = "";
    if (!Array.isArray(hints) || hints.length === 0) {
      const empty = document.createElement("li");
      empty.id = "no-hints";
      empty.textContent = window.translate("js.no_hints");
      container.append(empty);
      return;
    }

    hints.forEach((hint, index) => {
      container.append(createHintHistoryItem(hint, index + 1));
    });
  }

  function renderActionLog(list, actions) {
    list.innerHTML = "";
    if (!Array.isArray(actions) || actions.length === 0) {
      const empty = document.createElement("li");
      empty.id = "no-actions";
      empty.textContent = window.translate("js.no_actions");
      list.append(empty);
      return;
    }

    actions.forEach((action) => {
      const item = document.createElement("li");
      item.textContent = `${action.created_at} — ${action.action_type}: ${action.description}`;
      list.append(item);
    });
  }

  return {
    createHintHistoryItem,
    formatClockDuration,
    formatDuration,
    renderActionLog,
    renderHintHistory,
  };
})();
