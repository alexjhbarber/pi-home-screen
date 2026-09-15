import logging
from collections.abc import Callable
from collections.abc import Iterable

from gpiozero import Button, OutputDevice
from gpiozero.exc import BadPinFactory, GPIOPinInUse


LOGGER = logging.getLogger(__name__)


class GpioController:
    """Manages named and persisted direct BCM GPIO outputs."""

    def __init__(
        self,
        output_pins: dict[str, int] | None = None,
        input_pins: Iterable[tuple[str, int]] | dict[str, int] | None = None,
    ) -> None:
        self._outputs: dict[str, OutputDevice] = {}
        self._configured_output_pins = set((output_pins or {}).values())
        self._direct_outputs: dict[int, OutputDevice] = {}
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

    def output_pins(self) -> dict[str, int]:
        return {
            name: output.pin.number
            for name, output in self._outputs.items()
        }

    def input_names(self) -> list[str]:
        return []

    def is_input_pin(self, pin: int) -> bool:
        return pin in self._buttons

    def is_output_pin(self, pin: int) -> bool:
        return (
            pin in self._configured_output_pins
            or pin in self._direct_outputs
            or any(output.pin.number == pin for output in self._outputs.values())
        )

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
        except GPIOPinInUse as error:
            for button in self._buttons.values():
                button.close()
            self._buttons.clear()
            raise ValueError("That BCM pin is already configured as an output.") from error
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

    def activate_pin(self, pin: int) -> None:
        self._direct_output(pin).on()

    def deactivate_pin(self, pin: int) -> None:
        self._direct_output(pin).off()

    def release_pin(self, pin: int) -> None:
        output = self._direct_outputs.pop(pin, None)
        if output is not None:
            output.close()

    def close(self) -> None:
        for device in (
            *self._outputs.values(),
            *self._direct_outputs.values(),
            *self._buttons.values(),
        ):
            device.close()
        self._outputs.clear()
        self._direct_outputs.clear()
        self._buttons.clear()

    def _direct_output(self, pin: int) -> OutputDevice:
        if not isinstance(pin, int) or not 0 <= pin <= 27:
            raise ValueError("GPIO pin must be a BCM pin number from 0 to 27.")
        output = self._direct_outputs.get(pin)
        if output is not None:
            return output
        if self.is_input_pin(pin):
            raise ValueError("That BCM pin is already configured as an input.")
        if self.is_output_pin(pin):
            raise ValueError("That BCM pin is already configured as an output.")
        try:
            output = OutputDevice(pin, initial_value=False)
        except GPIOPinInUse as error:
            raise ValueError("That BCM pin is already in use.") from error
        except BadPinFactory as error:
            self.available = False
            raise RuntimeError("GPIO hardware is unavailable.") from error
        self._direct_outputs[pin] = output
        return output

    @staticmethod
    def _log_input(pin: int, name: str) -> None:
        LOGGER.info("GPIO %s input '%s' was activated.", pin, name)
