import re
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .database import connect


COLOUR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_TITLE_LENGTH = 80
MAX_MESSAGE_LENGTH = 500
TIMER_DURATION_SECONDS = 60 * 60
ANNOUNCEMENT_DURATION = timedelta(minutes=2)


@dataclass(frozen=True)
class DisplaySettings:
    title: str
    message: str
    background_colour: str
    accent_colour: str
    timer_started_at: str | None = None
    room_completed_at: str | None = None
    announcement: str | None = None
    announcement_expires_at: str | None = None
    background_image: str | None = None
    auto_hint_remaining_minutes: int | None = None
    auto_hint_message: str | None = None
    extra_time_seconds: int = 0
    penalty_time_seconds: int = 0
    announcement_media_type: str | None = None
    announcement_media_filename: str | None = None
    announcement_media_full_screen: bool = False

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


@dataclass(frozen=True)
class Hint:
    id: int
    message: str
    given_at: str
    timer_remaining_seconds: int
    media_type: str | None = None
    media_filename: str | None = None

    def to_dict(self) -> dict[str, int | str]:
        return asdict(self)


@dataclass(frozen=True)
class HintPreset:
    id: int
    kind: str
    title: str
    message: str | None
    media_filename: str | None
    created_at: str
    full_screen: bool = False

    def to_dict(self) -> dict[str, int | str | None]:
        return asdict(self)


@dataclass(frozen=True)
class RoomStatistic:
    id: int
    label: str
    value: str
    recorded_at: str


@dataclass(frozen=True)
class CompletionResult:
    group_name: str
    group_size: int
    hints_used: int
    penalties: int
    time_taken_seconds: int
    time_remaining_seconds: int

    def to_dict(self) -> dict[str, int | str]:
        return asdict(self)


@dataclass(frozen=True)
class GpioMapping:
    pin: int
    event: str
    preset_id: int | None = None


@dataclass(frozen=True)
class GpioActivity:
    pin: int
    event: str
    accepted: bool
    triggered_at: str


class DisplaySettingsStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def get(self) -> DisplaySettings:
        with closing(connect(self.database_path)) as connection:
            row = connection.execute(
                """
                SELECT
                    title, message, background_colour, accent_colour, timer_started_at,
                    room_completed_at,
                    announcement, announcement_expires_at, background_image,
                    auto_hint_remaining_minutes, auto_hint_message,
                    extra_time_seconds, penalty_time_seconds,
                    announcement_media_type, announcement_media_filename,
                    announcement_media_full_screen
                FROM display_settings
                WHERE id = 1
                """
            ).fetchone()
        values = dict(row)
        values["announcement_media_full_screen"] = bool(values["announcement_media_full_screen"])
        return DisplaySettings(**values)

    def update(
        self,
        values: dict[str, object],
        background_image: str | None = None,
        remove_background_image: bool = False,
    ) -> DisplaySettings:
        settings = self._validate(values)
        with closing(connect(self.database_path)) as connection:
            if background_image is not None or remove_background_image:
                connection.execute(
                    """
                    UPDATE display_settings
                    SET title = ?, message = ?, background_colour = ?, accent_colour = ?,
                        background_image = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1
                    """,
                    (
                        settings.title, settings.message, settings.background_colour,
                        settings.accent_colour,
                        None if remove_background_image else background_image,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE display_settings
                    SET title = ?, message = ?, background_colour = ?, accent_colour = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1
                    """,
                    (
                        settings.title, settings.message, settings.background_colour,
                        settings.accent_colour,
                    ),
                )
            connection.commit()
        return self.get()

    def start_timer(self) -> DisplaySettings:
        return self._update_timer(datetime.now(timezone.utc).isoformat())

    def reset_timer(self) -> DisplaySettings:
        # When resetting the timer via admin, preserve previously given hints.
        return self._update_timer(None, clear_hints=False)

    def complete_room(self) -> DisplaySettings:
        settings = self.get()
        if settings.timer_started_at is None:
            raise ValueError("Start the timer before completing the room.")
        with closing(connect(self.database_path)) as connection:
            connection.execute(
                """
                UPDATE display_settings
                SET room_completed_at = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                """,
                (datetime.now(timezone.utc).isoformat(),),
            )
            connection.commit()
        return self.get()

    def adjust_timer(self, seconds_delta: int) -> DisplaySettings:
        """Adjust the current run's time budget by seconds_delta.

        Positive seconds_delta adds to the total time available (time remaining increases,
        time taken is unaffected). Negative seconds_delta adds a penalty to time taken
        (time taken increases, the total time budget is unaffected).
        """
        if not isinstance(seconds_delta, int):
            raise ValueError("seconds_delta must be an integer number of seconds.")
        settings = self.get()
        if settings.timer_started_at is None:
            raise ValueError("Start the timer before adjusting it.")
        with closing(connect(self.database_path)) as connection:
            if seconds_delta >= 0:
                new_extra = max(0, settings.extra_time_seconds + seconds_delta)
                connection.execute(
                    """
                    UPDATE display_settings
                    SET extra_time_seconds = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1
                    """,
                    (new_extra,),
                )
            else:
                new_penalty = max(0, settings.penalty_time_seconds + (-seconds_delta))
                connection.execute(
                    """
                    UPDATE display_settings
                    SET penalty_time_seconds = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1
                    """,
                    (new_penalty,),
                )
            connection.commit()
        return self.get()

    def send_announcement(
        self,
        message: object,
        media_type: str | None = None,
        media_filename: str | None = None,
        media_full_screen: bool = False,
    ) -> tuple[DisplaySettings, Hint]:
        if media_type is not None and media_type not in ("image", "video"):
            raise ValueError("media_type must be 'image' or 'video'.")
        if media_type is not None and not media_filename:
            raise ValueError("media_filename is required when media_type is set.")
        message_text = message if isinstance(message, str) else ""
        if media_type is None and not message_text.strip():
            raise ValueError("Announcement text is required.")
        if len(message_text) > MAX_MESSAGE_LENGTH:
            raise ValueError(
                f"Announcement can contain at most {MAX_MESSAGE_LENGTH} characters."
            )
        now = datetime.now(timezone.utc)
        expires_at = now + ANNOUNCEMENT_DURATION
        current_settings = self.get()
        timer_remaining_seconds = TIMER_DURATION_SECONDS + current_settings.extra_time_seconds
        if current_settings.timer_started_at is not None:
            started_at = datetime.fromisoformat(current_settings.timer_started_at)
            elapsed_seconds = int((now - started_at).total_seconds()) + current_settings.penalty_time_seconds
            # Allow negative remaining seconds so announcements capture overtime situations
            timer_remaining_seconds = (
                TIMER_DURATION_SECONDS + current_settings.extra_time_seconds - elapsed_seconds
            )
        with closing(connect(self.database_path)) as connection:
            connection.execute(
                """
                UPDATE display_settings
                SET announcement = ?, announcement_expires_at = ?,
                    announcement_media_type = ?, announcement_media_filename = ?,
                    announcement_media_full_screen = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                """,
                (
                    message_text.strip(),
                    expires_at.isoformat(),
                    media_type,
                    media_filename,
                    1 if (media_type is not None and media_full_screen) else 0,
                ),
            )
            hint_id = connection.execute(
                """
                INSERT INTO hints (message, timer_remaining_seconds, media_type, media_filename)
                VALUES (?, ?, ?, ?)
                """,
                (message_text.strip(), timer_remaining_seconds, media_type, media_filename),
            ).lastrowid
            connection.commit()
        with closing(connect(self.database_path)) as connection:
            row = connection.execute(
                """
                SELECT id, message, given_at, timer_remaining_seconds, media_type, media_filename
                FROM hints
                WHERE id = ?
                """,
                (hint_id,),
            ).fetchone()
        return self.get(), Hint(**dict(row))

    def get_hints(self) -> list[Hint]:
        with closing(connect(self.database_path)) as connection:
            rows = connection.execute(
                """
                SELECT id, message, given_at, timer_remaining_seconds, media_type, media_filename
                FROM hints
                ORDER BY id
                """
            )
            return [Hint(**dict(row)) for row in rows]

    def get_statistics(self) -> list[RoomStatistic]:
        with closing(connect(self.database_path)) as connection:
            rows = connection.execute(
                "SELECT id, label, value, recorded_at FROM room_statistics ORDER BY id DESC"
            )
            return [RoomStatistic(**dict(row)) for row in rows]

    @dataclass(frozen=True)
    class LeaderboardEntry:
        group_name: str
        group_size: int
        hints_used: int
        penalties: int
        time_taken_seconds: int
        time_remaining_seconds: int
        completed_at: str

        def to_dict(self) -> dict[str, int | str]:
            return asdict(self)

    def get_leaderboard(self) -> list[LeaderboardEntry]:
        """Return leaderboard entries ordered by best performance.

        Ordering: time_remaining_seconds DESC (more time left is better),
        then penalties ASC, then hints_used ASC, then completed_at ASC.
        """
        with closing(connect(self.database_path)) as connection:
            rows = connection.execute(
                """
                SELECT group_name, group_size, hints_used, penalties,
                       time_taken_seconds, time_remaining_seconds, completed_at
                FROM room_results
                ORDER BY time_remaining_seconds DESC, penalties ASC, hints_used ASC, completed_at ASC
                """
            ).fetchall()
            return [
                DisplaySettingsStore.LeaderboardEntry(**dict(row))
                for row in rows
            ]

    def get_latest_result(self) -> CompletionResult | None:
        with closing(connect(self.database_path)) as connection:
            row = connection.execute(
                "SELECT group_name, group_size, hints_used, penalties, time_taken_seconds, time_remaining_seconds FROM room_results ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            return CompletionResult(**dict(row))

    def save_completion_result(
        self,
        group_name: object,
        group_size: object,
        hints_used: object,
        penalties: object,
    ) -> CompletionResult:
        name = self._validate_result_name(group_name)
        size = self._validate_result_count(group_size, "Group size")
        hints = self._validate_result_count(hints_used, "Hints used")
        penalty_count = self._validate_result_count(penalties, "Penalties")
        settings = self.get()
        if settings.timer_started_at is None or settings.room_completed_at is None:
            raise ValueError("Complete the room before recording its result.")

        started_at = datetime.fromisoformat(settings.timer_started_at)
        completed_at = datetime.fromisoformat(settings.room_completed_at)
        time_taken_seconds = max(0, int((completed_at - started_at).total_seconds())) + settings.penalty_time_seconds
        time_remaining_seconds = TIMER_DURATION_SECONDS + settings.extra_time_seconds - time_taken_seconds
        with closing(connect(self.database_path)) as connection:
            connection.execute(
                """
                INSERT INTO room_results (
                    timer_started_at, completed_at, group_name, group_size, hints_used,
                    penalties, time_taken_seconds, time_remaining_seconds
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(timer_started_at) DO UPDATE SET
                    completed_at = excluded.completed_at,
                    group_name = excluded.group_name,
                    group_size = excluded.group_size,
                    hints_used = excluded.hints_used,
                    penalties = excluded.penalties,
                    time_taken_seconds = excluded.time_taken_seconds,
                    time_remaining_seconds = excluded.time_remaining_seconds
                """,
                (
                    settings.timer_started_at, settings.room_completed_at, name, size, hints,
                    penalty_count, time_taken_seconds, time_remaining_seconds,
                ),
            )
            connection.commit()
        return CompletionResult(
            group_name=name,
            group_size=size,
            hints_used=hints,
            penalties=penalty_count,
            time_taken_seconds=time_taken_seconds,
            time_remaining_seconds=time_remaining_seconds,
        )

    def add_statistic(self, label: object, value: object) -> None:
        if not isinstance(label, str) or not label.strip():
            raise ValueError("Statistic name is required.")
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Statistic value is required.")
        if len(label) > 80 or len(value) > 200:
            raise ValueError("Statistic name or value is too long.")
        with closing(connect(self.database_path)) as connection:
            connection.execute(
                "INSERT INTO room_statistics (label, value) VALUES (?, ?)",
                (label.strip(), value.strip()),
            )
            connection.commit()

    def delete_statistic(self, statistic_id: int) -> bool:
        with closing(connect(self.database_path)) as connection:
            result = connection.execute(
                "DELETE FROM room_statistics WHERE id = ?",
                (statistic_id,),
            )
            connection.commit()
        return result.rowcount == 1

    def add_hint_preset(
        self,
        kind: object,
        title: object,
        message: object,
        media_filename: object,
        full_screen: object = False,
    ) -> HintPreset:
        if kind not in ("text", "image", "video"):
            raise ValueError("Hint type must be text, image, or video.")
        if not isinstance(title, str) or not title.strip() or len(title) > 80:
            raise ValueError("Hint title must contain 1 to 80 characters.")
        message_text = message.strip() if isinstance(message, str) else ""
        if kind == "text":
            if not message_text:
                raise ValueError("Text hints require message content.")
            if len(message_text) > MAX_MESSAGE_LENGTH:
                raise ValueError(f"Hint message can contain at most {MAX_MESSAGE_LENGTH} characters.")
            media_filename = None
        else:
            if not media_filename:
                raise ValueError(f"A {kind} file is required.")
            if len(message_text) > MAX_MESSAGE_LENGTH:
                raise ValueError(f"Hint caption can contain at most {MAX_MESSAGE_LENGTH} characters.")
        is_full_screen = 1 if (kind != "text" and full_screen in (True, "on", "true", "1", 1)) else 0
        with closing(connect(self.database_path)) as connection:
            preset_id = connection.execute(
                """
                INSERT INTO hint_presets (kind, title, message, media_filename, full_screen)
                VALUES (?, ?, ?, ?, ?)
                """,
                (kind, title.strip(), message_text or None, media_filename, is_full_screen),
            ).lastrowid
            connection.commit()
        return self.get_hint_preset(preset_id)

    def get_hint_presets(self) -> list[HintPreset]:
        with closing(connect(self.database_path)) as connection:
            rows = connection.execute(
                "SELECT id, kind, title, message, media_filename, created_at, full_screen"
                " FROM hint_presets ORDER BY id DESC"
            )
            return [HintPreset(**{**dict(row), "full_screen": bool(row["full_screen"])}) for row in rows]

    def get_hint_preset(self, preset_id: int) -> HintPreset | None:
        with closing(connect(self.database_path)) as connection:
            row = connection.execute(
                "SELECT id, kind, title, message, media_filename, created_at, full_screen"
                " FROM hint_presets WHERE id = ?",
                (preset_id,),
            ).fetchone()
            if row is None:
                return None
            return HintPreset(**{**dict(row), "full_screen": bool(row["full_screen"])})

    def delete_hint_preset(self, preset_id: int) -> bool:
        with closing(connect(self.database_path)) as connection:
            result = connection.execute("DELETE FROM hint_presets WHERE id = ?", (preset_id,))
            connection.commit()
        return result.rowcount == 1

    def set_automatic_hint(self, remaining_minutes: object, message: object) -> None:
        if not isinstance(remaining_minutes, str) or not remaining_minutes.isdecimal():
            raise ValueError("Automatic hint time must be a whole number of minutes.")
        minutes = int(remaining_minutes)
        if not 0 <= minutes < 60:
            raise ValueError("Automatic hint time must be between 0 and 59 minutes.")
        if not isinstance(message, str) or not message.strip() or len(message) > MAX_MESSAGE_LENGTH:
            raise ValueError(f"Automatic hint must contain 1 to {MAX_MESSAGE_LENGTH} characters.")
        with closing(connect(self.database_path)) as connection:
            connection.execute(
                """
                UPDATE display_settings
                SET auto_hint_remaining_minutes = ?, auto_hint_message = ?
                WHERE id = 1
                """,
                (minutes, message.strip()),
            )
            connection.commit()

    def get_gpio_mappings(self) -> list[GpioMapping]:
        with closing(connect(self.database_path)) as connection:
            rows = connection.execute("SELECT pin, event, preset_id FROM gpio_mappings ORDER BY pin")
            mappings = []
            for row in rows:
                d = dict(row)
                d["preset_id"] = d.get("preset_id") if d.get("preset_id") is not None else None
                mappings.append(GpioMapping(**d))
            return mappings

    def get_gpio_mapping_by_pin(self, pin: int) -> GpioMapping | None:
        with closing(connect(self.database_path)) as connection:
            row = connection.execute(
                "SELECT pin, event, preset_id FROM gpio_mappings WHERE pin = ?",
                (pin,),
            ).fetchone()
            if row is None:
                return None
            d = dict(row)
            d["preset_id"] = d.get("preset_id") if d.get("preset_id") is not None else None
            return GpioMapping(**d)

    def record_action(self, action_type: str, description: str) -> None:
        if not isinstance(action_type, str) or not action_type.strip():
            raise ValueError("action_type is required")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("description is required")
        settings = self.get()
        timer_started_at = settings.timer_started_at
        with closing(connect(self.database_path)) as connection:
            connection.execute(
                "INSERT INTO action_log (timer_started_at, action_type, description) VALUES (?, ?, ?)",
                (timer_started_at, action_type.strip(), description.strip()),
            )
            connection.commit()

    def get_actions_for_current_run(self) -> list[dict]:
        settings = self.get()
        timer_started_at = settings.timer_started_at
        if timer_started_at is None:
            return []
        with closing(connect(self.database_path)) as connection:
            rows = connection.execute(
                "SELECT id, timer_started_at, action_type, description, created_at FROM action_log WHERE timer_started_at = ? ORDER BY id",
                (timer_started_at,),
            ).fetchall()
            return [dict(row) for row in rows]

    def add_gpio_mapping(self, pin: object, event: object, preset_id: object = None) -> None:
        if not isinstance(pin, str) or not pin.isdecimal() or not 0 <= int(pin) <= 27:
            raise ValueError("GPIO pin must be a BCM pin number from 0 to 27.")
        if event not in ("complete-room", "send-preset"):
            raise ValueError("Choose a supported GPIO event.")
        p_id = None
        if event == "send-preset":
            if preset_id is None:
                raise ValueError("Preset id is required for send-preset events.")
            if isinstance(preset_id, str) and preset_id.isdecimal():
                p_id = int(preset_id)
            elif isinstance(preset_id, int):
                p_id = preset_id
            else:
                raise ValueError("Invalid preset id.")
            # check preset exists
            with closing(connect(self.database_path)) as connection:
                row = connection.execute("SELECT id FROM hint_presets WHERE id = ?", (p_id,)).fetchone()
                if row is None:
                    raise ValueError("Specified hint preset does not exist.")
        with closing(connect(self.database_path)) as connection:
            try:
                if p_id is None:
                    connection.execute(
                        "INSERT INTO gpio_mappings (pin, event) VALUES (?, ?)",
                        (int(pin), event),
                    )
                else:
                    connection.execute(
                        "INSERT INTO gpio_mappings (pin, event, preset_id) VALUES (?, ?, ?)",
                        (int(pin), event, p_id),
                    )
            except sqlite3.IntegrityError as error:
                raise ValueError("That GPIO pin is already linked to an event.") from error
            connection.commit()

    def delete_gpio_mapping(self, pin: int) -> bool:
        with closing(connect(self.database_path)) as connection:
            result = connection.execute("DELETE FROM gpio_mappings WHERE pin = ?", (pin,))
            connection.commit()
        return result.rowcount == 1

    def set_gpio_paused(self, paused: bool) -> None:
        with closing(connect(self.database_path)) as connection:
            connection.execute("UPDATE gpio_settings SET paused = ? WHERE id = 1", (paused,))
            connection.commit()

    def get_gpio_activity(self) -> tuple[bool, list[GpioActivity]]:
        with closing(connect(self.database_path)) as connection:
            paused = bool(connection.execute("SELECT paused FROM gpio_settings WHERE id = 1").fetchone()["paused"])
            rows = connection.execute(
                "SELECT pin, event, accepted, triggered_at FROM gpio_events ORDER BY id DESC LIMIT 5"
            )
            activity = [
                GpioActivity(
                    pin=row["pin"], event=row["event"], accepted=bool(row["accepted"]),
                    triggered_at=row["triggered_at"],
                )
                for row in rows
            ]
        return paused, activity

    def record_gpio_event(self, pin: int, event: str, accepted: bool) -> None:
        with closing(connect(self.database_path)) as connection:
            connection.execute(
                "INSERT INTO gpio_events (pin, event, accepted) VALUES (?, ?, ?)",
                (pin, event, accepted),
            )
            connection.commit()

    def _update_timer(self, started_at: str | None, clear_hints: bool = True) -> DisplaySettings:
        with closing(connect(self.database_path)) as connection:
            connection.execute(
                """
                UPDATE display_settings
                SET timer_started_at = ?, room_completed_at = NULL,
                    extra_time_seconds = 0, penalty_time_seconds = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
                """,
                (started_at,),
            )
            if clear_hints:
                connection.execute("DELETE FROM hints")
            connection.commit()
        return self.get()

    @staticmethod
    def _validate_result_name(value: object) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > 80:
            raise ValueError("Group name must contain 1 to 80 characters.")
        return value.strip()

    @staticmethod
    def _validate_result_count(value: object, label: str) -> int:
        if not isinstance(value, str) or not value.isdecimal():
            raise ValueError(f"{label} must be a whole number.")
        count = int(value)
        if count > 999:
            raise ValueError(f"{label} must be 999 or less.")
        return count

    @staticmethod
    def _validate(values: dict[str, object]) -> DisplaySettings:
        required_fields = {
            "title",
            "message",
            "background_colour",
            "accent_colour",
        }
        if set(values) != required_fields:
            raise ValueError("All display settings are required.")

        title = values["title"]
        message = values["message"]
        background_colour = values["background_colour"]
        accent_colour = values["accent_colour"]
        if not all(
            isinstance(value, str)
            for value in (title, message, background_colour, accent_colour)
        ):
            raise ValueError("Display settings must be strings.")
        if not title.strip() or len(title) > MAX_TITLE_LENGTH:
            raise ValueError(f"Title must contain 1 to {MAX_TITLE_LENGTH} characters.")
        if len(message) > MAX_MESSAGE_LENGTH:
            raise ValueError(f"Message can contain at most {MAX_MESSAGE_LENGTH} characters.")
        if not COLOUR_PATTERN.fullmatch(background_colour):
            raise ValueError("Background colour must be a six-digit hex value.")
        if not COLOUR_PATTERN.fullmatch(accent_colour):
            raise ValueError("Accent colour must be a six-digit hex value.")

        return DisplaySettings(
            title=title.strip(),
            message=message.strip(),
            background_colour=background_colour.lower(),
            accent_colour=accent_colour.lower(),
        )
