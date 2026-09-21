import shutil
import subprocess


class DisplayPowerController:
    """Controls the primary HDMI output on Raspberry Pi OS."""

    def __init__(self) -> None:
        self.command = shutil.which("vcgencmd")

    @property
    def available(self) -> bool:
        return self.command is not None

    def toggle(self) -> bool:
        if self.command is None:
            raise RuntimeError("Raspberry Pi display control is unavailable.")
        result = subprocess.run(
            [self.command, "display_power"],
            check=True,
            capture_output=True,
            text=True,
        )
        current_state = result.stdout.strip().endswith("=1")
        subprocess.run(
            [self.command, "display_power", "1" if not current_state else "0"],
            check=True,
            capture_output=True,
            text=True,
        )
        return not current_state
