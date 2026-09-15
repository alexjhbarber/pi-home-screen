const title = document.querySelector("#title");
const message = document.querySelector("#message");
const timer = document.querySelector("#timer");
const announcement = document.querySelector("#announcement");
const announcementMessage = document.querySelector("#announcement-message");
const announcementImage = document.querySelector("#announcement-image");
const announcementVideo = document.querySelector("#announcement-video");
const gpioActivity = document.querySelector("#gpio-activity");
const teamInfo = document.querySelector("#team-info");
const teamName = document.querySelector("#team-name");
const teamDetails = document.querySelector("#team-details");
const soundManager = window.HomeAudio.createSoundManager(window.location.search);
let timerStartedAt = null;
let timerPausedAt = null;
let roomCompletedAt = null;
let announcementExpiresAt = null;
let extraTimeSeconds = 0;
let penaltyTimeSeconds = 0;
let originalTitle = title.textContent;
let originalMessage = message.textContent;
let videoAnnouncementActive = false;
let currentVideoFilename = null;
let currentVideoAnnouncementExpiresAt = null;
let previousAnnouncementVisible = false;
let previousMessage = null;
let previousTitle = null;
let previousRoomComplete = null;

function updateDisplay(settings) {
  soundManager.updateFromSettings(settings);

  const hasAnnouncementNow = Boolean(settings.announcement || settings.announcement_media_filename);
  if (previousMessage !== null && settings.message !== previousMessage && !hasAnnouncementNow) {
    soundManager.playHint();
  }
  if (previousTitle !== null && settings.title !== previousTitle && !hasAnnouncementNow) {
    soundManager.playHint();
  }
  previousMessage = settings.message;
  previousTitle = settings.title;

  originalTitle = settings.title;
  originalMessage = settings.message;
  document.body.style.setProperty("--background-colour", settings.background_colour);
  document.body.style.setProperty("--accent-colour", settings.accent_colour);
  const backgroundImage = settings.background_image
    ? `url("/uploads/${encodeURIComponent(settings.background_image)}")`
    : "none";
  document.body.style.setProperty("--background-image", backgroundImage);
  timerStartedAt = settings.timer_started_at;
  timerPausedAt = settings.timer_paused_at;
  roomCompletedAt = settings.room_completed_at;
  announcementExpiresAt = settings.announcement_expires_at;
  extraTimeSeconds = settings.extra_time_seconds || 0;
  penaltyTimeSeconds = settings.penalty_time_seconds || 0;
  announcementMessage.textContent = settings.announcement || "";
  announcement.classList.toggle("full-screen", Boolean(settings.announcement_media_full_screen));
  updateAnnouncementMedia(settings);
  updateLatestResult(settings.latest_result);
  updateTimer();
  updateRoomCompletion();
  updateAnnouncement();
}

function updateAnnouncementMedia(settings) {
  if (settings.announcement_media_type === "image" && settings.announcement_media_filename) {
    announcementImage.src = `/uploads/${encodeURIComponent(settings.announcement_media_filename)}`;
    announcementImage.hidden = false;
    announcementVideo.hidden = true;
    announcementVideo.removeAttribute("src");
  } else if (settings.announcement_media_type === "video" && settings.announcement_media_filename) {
    const newSrc = `/uploads/${encodeURIComponent(settings.announcement_media_filename)}`;
    if (
      settings.announcement_media_filename !== currentVideoFilename
      || settings.announcement_expires_at !== currentVideoAnnouncementExpiresAt
    ) {
      currentVideoFilename = settings.announcement_media_filename;
      currentVideoAnnouncementExpiresAt = settings.announcement_expires_at;
      videoAnnouncementActive = false;
      announcementVideo.src = newSrc;
      try {
        announcementVideo.load();
        const p = announcementVideo.play();
        if (p && typeof p.then === "function") {
          p.then(() => {
            videoAnnouncementActive = true;
          }).catch((err) => {
            console.warn('Auto-play blocked or failed:', err);
            videoAnnouncementActive = true;
          });
        } else {
          videoAnnouncementActive = true;
        }
      } catch (err) {
        console.warn('Video play attempt failed:', err);
        videoAnnouncementActive = true;
      }
    }
    announcementVideo.hidden = false;
    announcementImage.hidden = true;
    announcementImage.removeAttribute("src");
  } else {
    announcementImage.hidden = true;
    announcementVideo.hidden = true;
    announcementImage.removeAttribute("src");
    announcementVideo.removeAttribute("src");
    currentVideoFilename = null;
    currentVideoAnnouncementExpiresAt = null;
    videoAnnouncementActive = false;
  }

  announcementVideo.onended = () => {
    videoAnnouncementActive = false;
    announcement.hidden = true;
    previousAnnouncementVisible = false;
  };
}

function updateLatestResult(latestResult) {
  if (!teamInfo || !teamName || !teamDetails) {
    return;
  }

  if (!latestResult) {
    teamInfo.hidden = true;
    return;
  }

  teamName.textContent = latestResult.group_name;
  const remaining = latestResult.time_remaining_seconds >= 0
    ? window.translate("js.left", {
      value: formatDuration(latestResult.time_remaining_seconds),
    })
    : window.translate("js.overtime", {
      value: formatDuration(-latestResult.time_remaining_seconds),
    });
  teamDetails.textContent = [
    window.translate("js.players", { value: latestResult.group_size }),
    window.translate("js.hints", { value: latestResult.hints_used }),
    window.translate("js.penalties", { value: latestResult.penalties }),
    `${window.translate("js.time", {
      value: formatDuration(latestResult.time_taken_seconds),
    })} (${remaining})`,
  ].join(" • ");
  teamInfo.hidden = false;
}

function updateTimer() {
  const elapsedSeconds = timerStartedAt
    ? Math.floor(
      (Date.parse(timerPausedAt || new Date()) - Date.parse(timerStartedAt)) / 1000,
    ) + penaltyTimeSeconds
    : 0;
  const remainingSeconds = (60 * 60 + extraTimeSeconds) - elapsedSeconds;
  timer.textContent = formatDuration(remainingSeconds);
}

function updateRoomCompletion() {
  const isComplete = Boolean(roomCompletedAt);
  document.body.classList.toggle("room-complete", isComplete);
  if (previousRoomComplete !== null && !previousRoomComplete && isComplete) {
    soundManager.playSuccess();
  }

  if (!isComplete) {
    title.textContent = originalTitle;
    message.textContent = originalMessage;
    previousRoomComplete = isComplete;
    return;
  }

  const startedAt = Date.parse(timerStartedAt);
  const completedAt = Date.parse(roomCompletedAt);
  const elapsedSeconds = Math.floor((completedAt - startedAt) / 1000) + penaltyTimeSeconds;
  const remainingSeconds = (60 * 60 + extraTimeSeconds) - elapsedSeconds;
  title.textContent = window.translate("js.congratulations");
  message.textContent = [
    window.translate("js.time_remaining", {
      value: formatDuration(remainingSeconds),
    }),
    window.translate("js.time_taken", {
      value: formatDuration(elapsedSeconds),
    }),
  ].join(" | ");
  timer.textContent = formatDuration(remainingSeconds);
  previousRoomComplete = isComplete;
}

function formatDuration(totalSeconds) {
  const negative = totalSeconds < 0;
  const absSeconds = Math.abs(totalSeconds);
  const minutes = String(Math.floor(absSeconds / 60)).padStart(2, "0");
  const seconds = String(absSeconds % 60).padStart(2, "0");
  return `${negative ? '-' : ''}${minutes}:${seconds}`;
}

function updateAnnouncement() {
  if (!announcementVideo.hidden) {
    announcement.hidden = !videoAnnouncementActive;
    if (!announcement.hidden && !previousAnnouncementVisible) {
      soundManager.playHint();
    }
    previousAnnouncementVisible = !announcement.hidden;
    return;
  }

  const hasContent = announcementMessage.textContent
    || !announcementImage.hidden;
  const isActive = hasContent
    && announcementExpiresAt
    && Date.now() < Date.parse(announcementExpiresAt);

  if (!isActive) {
    announcement.hidden = true;
    previousAnnouncementVisible = false;
    return;
  }

  announcement.hidden = false;
  if (!previousAnnouncementVisible) {
    soundManager.playHint();
  }
  previousAnnouncementVisible = true;
}

setInterval(() => {
  updateTimer();
  updateRoomCompletion();
  updateAnnouncement();
}, 250);

const displayEvents = new EventSource("/events");
displayEvents.addEventListener("display", (event) => updateDisplay(JSON.parse(event.data)));
