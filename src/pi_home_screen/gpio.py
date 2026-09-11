import logging
from collections.abc import Callable
from collections.abc import Iterable

from gpiozero import Button, OutputDevice
from gpiozero.exc import BadPinFactory


LOGGER = logging.getLogger(__name__)


class GpioController:
    """Manages named BCM GPIO outputs and optional button callbacks."""

    def __init__(
        self,
        output_pins: dict[str, int] | None = None,
        input_pins: Iterable[tuple[str, int]] | dict[str, int] | None = None,
    ) -> None:
        self._outputs: dict[str, OutputDevice] = {}
        self._buttons: dict[int, Button] = {}
        self.available = True
        try:
            for name, pin in (output_pins or {}).items():
                self._outputs[name] = OutputDevice(pin)
            self.configure_inputs(input_pins or {}, self._log_input)
        except BadPinFactory:
            self.available = False
            self.close()
            LOGGER.warning("GPIO hardware is unavailable; running without physical pin control.")

    def output_names(self) -> list[str]:
        return sorted(self._outputs)

    def input_names(self) -> list[str]:
        return []

    def configure_inputs(
        self,
        input_pins: Iterable[tuple[str, int]] | dict[str, int],
        callback: Callable[[int, str], None],
    ) -> None:
        for button in self._buttons.values():
            button.close()
        self._buttons.clear()
        try:
            pins = input_pins.items() if isinstance(input_pins, dict) else input_pins
            for name, pin in pins:
                button = Button(pin)
                button.when_pressed = lambda pin=pin, name=name: callback(pin, name)
                self._buttons[pin] = button
        except BadPinFactory:
            self.available = False
            self.close()
            LOGGER.warning("GPIO hardware is unavailable; running without physical pin control.")

    def activate(self, name: str) -> None:
        output = self._outputs.get(name)
        if output is None:
            raise KeyError(name)
        output.on()

    def deactivate(self, name: str) -> None:
        output = self._outputs.get(name)
        if output is None:
            raise KeyError(name)
        output.off()

    def close(self) -> None:
        for device in (*self._outputs.values(), *self._buttons.values()):
            device.close()
        self._outputs.clear()
        self._buttons.clear()

    @staticmethod
    def _log_input(pin: int, name: str) -> None:
        LOGGER.info("GPIO %s input '%s' was activated.", pin, name)
