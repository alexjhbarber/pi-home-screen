const title = document.querySelector("#title");
const message = document.querySelector("#message");
const timer = document.querySelector("#timer");
const announcement = document.querySelector("#announcement");
const announcementMessage = document.querySelector("#announcement-message");
const announcementImage = document.querySelector("#announcement-image");
const announcementVideo = document.querySelector("#announcement-video");
const gpioActivity = document.querySelector("#gpio-activity");
let timerStartedAt = null;
let roomCompletedAt = null;
let announcementExpiresAt = null;
let extraTimeSeconds = 0;
let penaltyTimeSeconds = 0;
let originalTitle = title.textContent;
let originalMessage = message.textContent;
let videoAnnouncementActive = false;
let currentVideoFilename = null;
let _previousAnnouncementVisible = false;

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
  extraTimeSeconds = settings.extra_time_seconds || 0;
  penaltyTimeSeconds = settings.penalty_time_seconds || 0;
  announcementMessage.textContent = settings.announcement || "";
  announcement.classList.toggle("full-screen", Boolean(settings.announcement_media_full_screen));
  if (settings.announcement_media_type === "image" && settings.announcement_media_filename) {
    announcementImage.src = `/uploads/${encodeURIComponent(settings.announcement_media_filename)}`;
    announcementImage.hidden = false;
    announcementVideo.hidden = true;
    announcementVideo.removeAttribute("src");
  } else if (settings.announcement_media_type === "video" && settings.announcement_media_filename) {
    const newSrc = `/uploads/${encodeURIComponent(settings.announcement_media_filename)}`;
    // set src if changed
    if (settings.announcement_media_filename !== currentVideoFilename) {
      currentVideoFilename = settings.announcement_media_filename;
      announcementVideo.src = newSrc;
    }
    announcementVideo.hidden = false;
    announcementImage.hidden = true;
    announcementImage.removeAttribute("src");
    // ensure video tries to play (many browsers require play() to be called when src changes)
    try {
      // reload source and attempt play; keep the UI visible even if autoplay is blocked
      announcementVideo.load();
      const p = announcementVideo.play();
      if (p && typeof p.then === "function") {
        p.then(() => {
          videoAnnouncementActive = true;
        }).catch((err) => {
          console.warn('Auto-play blocked or failed:', err);
          // still mark active so admin can manually press play
          videoAnnouncementActive = true;
        });
      } else {
        videoAnnouncementActive = true;
      }
    } catch (err) {
      console.warn('Video play attempt failed:', err);
      videoAnnouncementActive = true;
    }
  } else {
    announcementImage.hidden = true;
    announcementVideo.hidden = true;
    announcementImage.removeAttribute("src");
    announcementVideo.removeAttribute("src");
    currentVideoFilename = null;
    videoAnnouncementActive = false;
  }

  announcementVideo.onended = () => {
    videoAnnouncementActive = false;
  };

  // Team info (latest result) — revealed when present
  const teamInfo = document.querySelector('#team-info');
  const teamName = document.querySelector('#team-name');
  const teamDetails = document.querySelector('#team-details');
  if (settings.latest_result) {
    if (teamInfo && teamName && teamDetails) {
      teamName.textContent = settings.latest_result.group_name;
      teamDetails.textContent = `Players: ${settings.latest_result.group_size} • Hints: ${settings.latest_result.hints_used} • Penalties: ${settings.latest_result.penalties} • Time: ${formatDuration(settings.latest_result.time_taken_seconds)} (${settings.latest_result.time_remaining_seconds >= 0 ? formatDuration(settings.latest_result.time_remaining_seconds) + ' left' : formatDuration(-settings.latest_result.time_remaining_seconds) + ' overtime'})`;
      teamInfo.hidden = false;
    }
  } else if (teamInfo) {
    teamInfo.hidden = true;
  }

  updateTimer();
  updateRoomCompletion();
  updateAnnouncement();
}

function updateTimer() {
  const elapsedSeconds = timerStartedAt
    ? Math.floor((Date.now() - Date.parse(timerStartedAt)) / 1000) + penaltyTimeSeconds
    : 0;
  // Allow negative remaining seconds when elapsed exceeds the timer duration
  const remainingSeconds = (60 * 60 + extraTimeSeconds) - elapsedSeconds;
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
  const elapsedSeconds = Math.floor((completedAt - startedAt) / 1000) + penaltyTimeSeconds;
  const remainingSeconds = (60 * 60 + extraTimeSeconds) - elapsedSeconds;
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

function playHintSound() {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.type = 'sine';
    o.frequency.value = 880;
    o.connect(g);
    g.connect(ctx.destination);
    g.gain.setValueAtTime(0.0001, ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.15, ctx.currentTime + 0.01);
    o.start();
    o.stop(ctx.currentTime + 0.18);
    g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.18);
    // close context shortly after to free resources
    setTimeout(() => { try { ctx.close(); } catch (e) {} }, 500);
  } catch (e) {
    console.warn('Audio unavailable', e);
  }
}

function updateAnnouncement() {
  if (!announcementVideo.hidden) {
    // Videos are shown for exactly their playback length rather than the fixed duration.
    announcement.hidden = !videoAnnouncementActive;
    // play sound when video starts showing
    if (!announcement.hidden && !_previousAnnouncementVisible) playHintSound();
    _previousAnnouncementVisible = !announcement.hidden;
    return;
  }
  const hasContent = announcementMessage.textContent || !announcementImage.hidden;
  const isActive = hasContent
    && announcementExpiresAt
    && Date.now() < Date.parse(announcementExpiresAt);
  announcement.hidden = !isActive;
  if (!announcement.hidden && !_previousAnnouncementVisible) playHintSound();
  _previousAnnouncementVisible = !announcement.hidden;
}

setInterval(() => {
  updateTimer();
  updateRoomCompletion();
  updateAnnouncement();
}, 250);

const events = new EventSource("/events");
events.addEventListener("display", (event) => updateDisplay(JSON.parse(event.data)));

//async function updateGpioActivity() {
//  const response = await fetch("/api/gpio/activity");
//  if (!response.ok) return;
//  const { paused, activity } = await response.json();
//  const status = paused ? "GPIO paused" : "GPIO active";/
//  const events = activity.map((entry) => (
//  `BCM ${entry.pin}: ${entry.event} (${entry.accepted ? "triggered" : "ignored"})`
//  ));
//  gpioActivity.textContent = [status, ...events].join(" | ");
//}

//updateGpioActivity();
//setInterval(updateGpioActivity, 1000);
