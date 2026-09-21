from datetime import datetime, timezone
import subprocess
from threading import Timer

from flask import Flask

from .display import DisplaySettings, DisplaySettingsStore
from .display_power import DisplayPowerController
from .events import DisplayUpdateBroker
from .gpio import GpioController


class DisplayRuntime:
    def __init__(
        self,
        app: Flask,
        store: DisplaySettingsStore,
        broker: DisplayUpdateBroker,
        gpio: GpioController,
        display_power: DisplayPowerController,
        configured_gpio_inputs: dict[str, int],
    ) -> None:
        self.app = app
        self.store = store
        self.broker = broker
        self.gpio = gpio
        self.display_power = display_power
        self._configured_gpio_inputs = configured_gpio_inputs
        self._auto_hint_timer: Timer | None = None

    def initialize(self) -> None:
        self._clear_expired_announcement()
        self.configure_gpio_inputs()

    def publish(self, settings: DisplaySettings) -> None:
        self.broker.publish(settings)

    def publish_current_settings(self) -> None:
        self.publish(self.store.get())

    def record_action(self, action_type: str, description: str) -> None:
        try:
            self.store.record_action(action_type, description)
        except Exception:
            self.app.logger.exception("Failed to record action")

    def configure_gpio_inputs(self) -> None:
        inputs = self.gpio_inputs()
        self.gpio.configure_inputs(inputs, self.handle_gpio_event)

    def gpio_inputs(self) -> list[tuple[str, int]]:
        saved_mappings = self.store.get_gpio_mappings()
        if not saved_mappings:
            return list(self._configured_gpio_inputs.items())
        return [(mapping.event, mapping.pin) for mapping in saved_mappings]

    def is_gpio_input_pin(self, pin: int) -> bool:
        return any(input_pin == pin for _event, input_pin in self.gpio_inputs())

    def handle_gpio_event(self, pin: int, event: str) -> None:
        paused, _activity = self.store.get_gpio_activity()
        if paused:
            self.store.record_gpio_event(pin, event, accepted=False)
            return
        try:
            mapping = self.store.get_gpio_mapping_by_pin(pin)
            if mapping is None:
                self._handle_legacy_gpio_event(pin, event)
                return
            if mapping.event == "complete-room":
                settings = self.store.complete_room()
                self.publish(settings)
                self.store.record_gpio_event(pin, mapping.event, accepted=True)
                return
            if mapping.event == "start-timer":
                self._start_timer_from_gpio(pin, mapping.event)
                return
            if mapping.event == "send-preset":
                self._send_gpio_preset(pin, mapping.preset_id)
                return
            if mapping.event == "display-toggle":
                self.toggle_display_power(pin)
        except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError):
            self.store.record_gpio_event(pin, event, accepted=False)
            self.app.logger.warning(
                "Ignored GPIO event %s on pin %s.", event, pin
            )

    def schedule_automatic_hint(self, settings: DisplaySettings) -> None:
        self.cancel_automatic_hint()
        if (
            settings.auto_hint_remaining_minutes is None
            or settings.auto_hint_message is None
        ):
            return
        started_at = datetime.fromisoformat(settings.timer_started_at)
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        elapsed_seconds = max(
            0,
            (datetime.now(timezone.utc) - started_at).total_seconds(),
        )
        target_seconds = (60 - settings.auto_hint_remaining_minutes) * 60
        delay = max(0, target_seconds - elapsed_seconds)

        def send_if_room_is_incomplete() -> None:
            current = self.store.get()
            if (
                current.timer_started_at == settings.timer_started_at
                and current.room_completed_at is None
            ):
                updated, _hint = self.store.send_announcement(
                    settings.auto_hint_message
                )
                self.publish(updated)

        self._auto_hint_timer = Timer(delay, send_if_room_is_incomplete)
        self._auto_hint_timer.daemon = True
        self._auto_hint_timer.start()

    def cancel_automatic_hint(self) -> None:
        if self._auto_hint_timer is None:
            return
        self._auto_hint_timer.cancel()
        self._auto_hint_timer = None

    def _clear_expired_announcement(self) -> None:
        try:
            if self.store.clear_expired_announcement():
                self.publish_current_settings()
        except Exception:
            self.app.logger.exception(
                "Failed to clear expired announcement at startup"
            )

    def _handle_legacy_gpio_event(self, pin: int, event: str) -> None:
        if event == "start-timer":
            self._start_timer_from_gpio(pin, event)
            return
        if event != "complete-room":
            if event == "display-toggle":
                self.toggle_display_power(pin)
            return
        settings = self.store.complete_room()
        self.publish(settings)
        self.store.record_gpio_event(pin, event, accepted=True)

    def toggle_display_power(self, pin: int | None = None) -> bool:
        try:
            is_on = self.display_power.toggle()
        except (RuntimeError, OSError, subprocess.CalledProcessError):
            if pin is not None:
                self.store.record_gpio_event(pin, "display-toggle", accepted=False)
            self.app.logger.exception("Failed to toggle Raspberry Pi display power")
            raise
        if pin is not None:
            self.store.record_gpio_event(pin, "display-toggle", accepted=True)
        self.record_action("display", f"Turned HDMI display {'on' if is_on else 'off'}")
        return is_on

    def _start_timer_from_gpio(self, pin: int, event: str) -> None:
        settings = self.store.start_timer_if_not_running()
        if settings is None:
            self.store.record_gpio_event(pin, event, accepted=False)
            return
        self.record_action("timer", "Started 60-minute timer from GPIO")
        self.publish(settings)
        self.schedule_automatic_hint(settings)
        self.store.record_gpio_event(pin, event, accepted=True)

    def _send_gpio_preset(self, pin: int, preset_id: int | None) -> None:
        if preset_id is None:
            self.store.record_gpio_event(pin, "send-preset", accepted=False)
            self.app.logger.warning("GPIO mapping has no preset_id.")
            return
        preset = self.store.get_hint_preset(preset_id)
        if preset is None:
            self.store.record_gpio_event(pin, "send-preset", accepted=False)
            self.app.logger.warning(
                "GPIO mapping refers to missing preset id %s.", preset_id
            )
            return
        media_type = None if preset.kind == "text" else preset.kind
        try:
            settings, _hint = self.store.send_announcement(
                preset.message or "",
                media_type=media_type,
                media_filename=preset.media_filename,
                media_full_screen=preset.full_screen,
            )
        except ValueError:
            self.store.record_gpio_event(pin, "send-preset", accepted=False)
            self.app.logger.warning(
                "Ignored GPIO send-preset input because the timer is not running."
            )
            return
        self.record_action("announcement", f"GPIO sent preset hint: {preset.title}")
        self.publish(settings)
        self.store.record_gpio_event(pin, "send-preset", accepted=True)
