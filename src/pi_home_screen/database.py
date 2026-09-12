import sqlite3
from contextlib import closing
from pathlib import Path


def connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection


def initialize(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(database_path)) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS display_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                background_colour TEXT NOT NULL,
                accent_colour TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            INSERT INTO display_settings (
                id, title, message, background_colour, accent_colour
            )
            VALUES (1, 'Welcome', 'Your message appears here.', '#102a43', '#f6c453')
            ON CONFLICT(id) DO NOTHING;

            CREATE TABLE IF NOT EXISTS hints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT NOT NULL,
                given_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS room_statistics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                value TEXT NOT NULL,
                recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS room_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timer_started_at TEXT NOT NULL UNIQUE,
                completed_at TEXT NOT NULL,
                group_name TEXT NOT NULL,
                group_size INTEGER NOT NULL,
                hints_used INTEGER NOT NULL,
                penalties INTEGER NOT NULL,
                time_taken_seconds INTEGER NOT NULL,
                time_remaining_seconds INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS gpio_mappings (
                pin INTEGER PRIMARY KEY,
                event TEXT NOT NULL,
                preset_id INTEGER
            );

            CREATE TABLE IF NOT EXISTS gpio_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pin INTEGER NOT NULL,
                event TEXT NOT NULL,
                accepted INTEGER NOT NULL,
                triggered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS gpio_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                paused INTEGER NOT NULL DEFAULT 0
            );

            INSERT INTO gpio_settings (id, paused) VALUES (1, 0)
            ON CONFLICT(id) DO NOTHING;

            CREATE TABLE IF NOT EXISTS action_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timer_started_at TEXT,
                action_type TEXT NOT NULL,
                description TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS hint_presets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL CHECK (kind IN ('text', 'image', 'video')),
                title TEXT NOT NULL,
                message TEXT,
                media_filename TEXT,
                full_screen INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        existing_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(display_settings)")
        }
        gpio_mapping_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(gpio_mappings)")
        }
        if "preset_id" not in gpio_mapping_columns:
            connection.execute("ALTER TABLE gpio_mappings ADD COLUMN preset_id INTEGER")
        for column in (
            "timer_started_at TEXT",
            "room_completed_at TEXT",
            "announcement TEXT",
            "announcement_expires_at TEXT",
            "background_image TEXT",
            "timer_remaining_seconds INTEGER",
            "auto_hint_remaining_minutes INTEGER",
            "auto_hint_message TEXT",
            "extra_time_seconds INTEGER NOT NULL DEFAULT 0",
            "penalty_time_seconds INTEGER NOT NULL DEFAULT 0",
            "announcement_media_type TEXT",
            "announcement_media_filename TEXT",
            "announcement_media_full_screen INTEGER NOT NULL DEFAULT 0",
        ):
            name = column.split()[0]
            if name not in existing_columns:
                connection.execute(f"ALTER TABLE display_settings ADD COLUMN {column}")
        hint_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(hints)")
        }
        if "timer_remaining_seconds" not in hint_columns:
            connection.execute(
                "ALTER TABLE hints ADD COLUMN timer_remaining_seconds INTEGER NOT NULL DEFAULT 3600"
            )
        for column in ("media_type TEXT", "media_filename TEXT"):
            name = column.split()[0]
            if name not in hint_columns:
                connection.execute(f"ALTER TABLE hints ADD COLUMN {column}")
        preset_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(hint_presets)")
        }
        if "full_screen" not in preset_columns:
            connection.execute(
                "ALTER TABLE hint_presets ADD COLUMN full_screen INTEGER NOT NULL DEFAULT 0"
            )
        connection.commit()
