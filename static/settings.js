function setupColourControl(name) {
  const picker = document.querySelector(`#${name}-picker`);
  const hexInput = document.querySelector(`#${name}-hex`);
  const preview = document.querySelector(`#${name}-preview`);
  const acceptButton = document.querySelector(`[data-accept-colour="${name}"]`);
  const hexPattern = /^#[0-9a-fA-F]{6}$/;

  function updatePreview(value) {
    if (hexPattern.test(value)) {
      preview.style.background = value;
    }
  }

  acceptButton.addEventListener("click", () => {
    hexInput.value = picker.value;
    updatePreview(picker.value);
  });

  picker.addEventListener("input", () => updatePreview(picker.value));
  hexInput.addEventListener("input", () => {
    if (hexPattern.test(hexInput.value)) {
      picker.value = hexInput.value;
      updatePreview(hexInput.value);
    }
  });
}

setupColourControl("background");
setupColourControl("accent");
