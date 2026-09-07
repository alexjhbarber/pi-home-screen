const settingsForm = document.querySelector("#settings-form");
const announcementForm = document.querySelector("#announcement-form");
const sendHintButton = document.querySelector("#send-hint");
const hintHistory = document.querySelector("#hint-history");
const status = document.querySelector("#status");
const previewDialog = document.querySelector("#preview-dialog");

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

if (settingsForm) {
  settingsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    status.textContent = "";
    try {
      await post("/api/admin/settings", Object.fromEntries(new FormData(settingsForm)));
      status.textContent = "Home screen updated.";
    } catch (error) {
      status.textContent = error.message;
    }
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
    const remainingSeconds = hint.timer_remaining_seconds;
    timerValue.className = "hint-timer";
    timerValue.dateTime = `PT${remainingSeconds}S`;
    timerValue.textContent = `Timer: ${formatDuration(remainingSeconds)}`;
    timestamp.dateTime = hint.given_at;
    timestamp.textContent = `${hint.given_at} UTC`;
    item.append(count, text, timerValue, timestamp);
    hintHistory.append(item);
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

  document.querySelector("#open-preview").addEventListener("click", () => {
    previewDialog.showModal();
  });

  document.querySelector("#close-preview").addEventListener("click", () => {
    previewDialog.close();
  });
});
