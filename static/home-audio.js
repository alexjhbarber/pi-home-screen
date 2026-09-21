window.HomeAudio = (() => {
  let audioContext = null;

  function getAudioContext() {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return null;
    if (!audioContext) {
      audioContext = new AudioCtx();
    }
    return audioContext;
  }

  function withAudioContext(callback) {
    try {
      const context = getAudioContext();
      if (!context) return;
      const resumed = context.resume();
      if (resumed && typeof resumed.then === "function") {
        resumed.then(() => callback(context)).catch(() => {});
      } else {
        callback(context);
      }
    } catch (error) {
      console.warn("Audio unavailable", error);
    }
  }

  function playHintOscillator() {
    withAudioContext((context) => {
      const oscillator = context.createOscillator();
      const gain = context.createGain();

      oscillator.type = "sine";
      oscillator.frequency.value = 880;
      oscillator.connect(gain);
      gain.connect(context.destination);
      gain.gain.setValueAtTime(0.0001, context.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.15, context.currentTime + 0.01);
      oscillator.start();
      oscillator.stop(context.currentTime + 0.18);
      gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.18);
    });
  }

  function playSuccessOscillator() {
    withAudioContext((context) => {
      const highOscillator = context.createOscillator();
      const lowOscillator = context.createOscillator();
      const gain = context.createGain();

      highOscillator.type = "sine";
      lowOscillator.type = "sine";
      highOscillator.frequency.value = 880;
      lowOscillator.frequency.value = 660;
      highOscillator.connect(gain);
      lowOscillator.connect(gain);
      gain.connect(context.destination);
      gain.gain.setValueAtTime(0.0001, context.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.25, context.currentTime + 0.02);
      highOscillator.start();
      lowOscillator.start();
      highOscillator.stop(context.currentTime + 0.45);
      lowOscillator.stop(context.currentTime + 0.45);
      gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.45);
    });
  }

  function playFailedOscillator() {
    withAudioContext((context) => {
      const oscillator = context.createOscillator();
      const gain = context.createGain();

      oscillator.type = "sawtooth";
      oscillator.frequency.value = 220;
      oscillator.connect(gain);
      gain.connect(context.destination);
      gain.gain.setValueAtTime(0.0001, context.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.2, context.currentTime + 0.01);
      oscillator.start();
      oscillator.stop(context.currentTime + 0.35);
      gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.35);
    });
  }

  function playUploadedSound(url, fallback) {
    try {
      const audio = new Audio(url);
      audio.preload = "auto";
      audio.addEventListener("ended", () => audio.remove());
      const playback = audio.play();
      if (playback && typeof playback.then === "function") {
        playback.catch(() => fallback());
      }
      return;
    } catch (error) {
      fallback();
    }
  }

  function isPreviewEmbedded(search) {
    const params = new URLSearchParams(search);
    const preview = params.get("preview");
    return preview === "1" || preview === "true";
  }

  function createSoundManager(search) {
    let notificationSoundUrl = null;
    let successSoundUrl = null;
    let failedSoundUrl = null;
    const allowSound = !isPreviewEmbedded(search);

    function buildUploadUrl(filename) {
      return filename ? `/uploads/${encodeURIComponent(filename)}` : null;
    }

    function updateFromSettings(settings) {
      notificationSoundUrl = buildUploadUrl(settings.notification_sound_filename);
      successSoundUrl = buildUploadUrl(settings.success_sound_filename);
      failedSoundUrl = buildUploadUrl(settings.failed_sound_filename);
    }

    function playHint() {
      if (!allowSound) return;
      if (notificationSoundUrl) {
        playUploadedSound(notificationSoundUrl, playHintOscillator);
        return;
      }
      playHintOscillator();
    }

    function playSuccess() {
      if (!allowSound) return;
      if (successSoundUrl) {
        playUploadedSound(successSoundUrl, playSuccessOscillator);
        return;
      }
      playSuccessOscillator();
    }

    function playFailed() {
      if (!allowSound) return;
      if (failedSoundUrl) {
        playUploadedSound(failedSoundUrl, playFailedOscillator);
        return;
      }
      playFailedOscillator();
    }

    return {
      playFailed,
      playHint,
      playSuccess,
      updateFromSettings,
    };
  }

  return {
    createSoundManager,
  };
})();
