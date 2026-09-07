from collections.abc import Generator
import json
from threading import Condition

from .display import DisplaySettings


class DisplayUpdateBroker:
    def __init__(self) -> None:
        self._condition = Condition()
        self._revision = 0
        self._settings: DisplaySettings | None = None

    def publish(self, settings: DisplaySettings) -> None:
        with self._condition:
            self._revision += 1
            self._settings = settings
            self._condition.notify_all()

    def stream(self, initial_settings: DisplaySettings) -> Generator[str, None, None]:
        revision = -1
        settings = initial_settings
        while True:
            with self._condition:
                if revision == self._revision and self._settings is not None:
                    self._condition.wait(timeout=20)
                if self._settings is not None:
                    settings = self._settings
                revision = self._revision
            payload = json.dumps(settings.to_dict(), separators=(",", ":"))
            yield f"event: display\ndata: {payload}\n\n"
