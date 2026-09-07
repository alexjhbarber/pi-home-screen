const title = document.querySelector("#title");
const message = document.querySelector("#message");
const timer = document.querySelector("#timer");
const announcement = document.querySelector("#announcement");
const announcementMessage = document.querySelector("#announcement-message");
const gpioActivity = document.querySelector("#gpio-activity");
let timerStartedAt = null;
let roomCompletedAt = null;
let announcementExpiresAt = null;
let originalTitle = title.textContent;
let originalMessage = message.textContent;

function updateDisplay(settings) {
  originalTitle = settings.title;
  originalMessage = settings.message;
  document.body.style.setProperty("--background-colour", settings.background_colour);
  document.body.style.setProperty("--accent-colour", settings.accent_colour);
  const backgroundImage = settings.background_image
    ? `url("/uploads/${encodeURIComponent(settings.background_image)}")`
    : "none";
  document.body.style.setProperty("--background-image", backgroundImage);
  timerStartedAt = settings.timer_started_at;
  roomCompletedAt = settings.room_completed_at;
  announcementExpiresAt = settings.announcement_expires_at;
  announcementMessage.textContent = settings.announcement || "";
  updateTimer();
  updateRoomCompletion();
  updateAnnouncement();
}

function updateTimer() {
  const elapsedSeconds = timerStartedAt
    ? Math.floor((Date.now() - Date.parse(timerStartedAt)) / 1000)
    : 0;
  // Allow negative remaining seconds when elapsed exceeds the timer duration
  const remainingSeconds = 60 * 60 - elapsedSeconds;
  timer.textContent = formatDuration(remainingSeconds);
}

function updateRoomCompletion() {
  const isComplete = Boolean(roomCompletedAt);
  document.body.classList.toggle("room-complete", isComplete);
  if (!isComplete) {
    title.textContent = originalTitle;
    message.textContent = originalMessage;
    return;
  }

  const startedAt = Date.parse(timerStartedAt);
  const completedAt = Date.parse(roomCompletedAt);
  // Allow elapsed to exceed the nominal duration so remaining may be negative
  const elapsedSeconds = Math.floor((completedAt - startedAt) / 1000);
  const remainingSeconds = 60 * 60 - elapsedSeconds;
  title.textContent = "Congratulations!";
  message.textContent = `Time remaining: ${formatDuration(remainingSeconds)} | Time taken: ${formatDuration(elapsedSeconds)}`;
  timer.textContent = formatDuration(remainingSeconds);
}

function formatDuration(totalSeconds) {
  const negative = totalSeconds < 0;
  const absSeconds = Math.abs(totalSeconds);
  const minutes = String(Math.floor(absSeconds / 60)).padStart(2, "0");
  const seconds = String(absSeconds % 60).padStart(2, "0");
  return `${negative ? '-' : ''}${minutes}:${seconds}`;
}

function updateAnnouncement() {
  const isActive = announcementMessage.textContent
    && announcementExpiresAt
    && Date.now() < Date.parse(announcementExpiresAt);
  announcement.hidden = !isActive;
}

setInterval(() => {
  updateTimer();
  updateRoomCompletion();
  updateAnnouncement();
}, 250);

const events = new EventSource("/events");
events.addEventListener("display", (event) => updateDisplay(JSON.parse(event.data)));

async function updateGpioActivity() {
  const response = await fetch("/api/gpio/activity");
  if (!response.ok) return;
  const { paused, activity } = await response.json();
  const status = paused ? "GPIO paused" : "GPIO active";
  const events = activity.map((entry) => (
    `BCM ${entry.pin}: ${entry.event} (${entry.accepted ? "triggered" : "ignored"})`
  ));
  gpioActivity.textContent = [status, ...events].join(" | ");
}

updateGpioActivity();
setInterval(updateGpioActivity, 1000);
