import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from flask import Flask, g, request, session


CATALOG_DIRECTORY = Path(__file__).with_name("translations")
CLIENT_TRANSLATION_GROUPS = {
    "admin": (
        "js.request_failed",
        "js.timer_not_running",
        "js.elapsed",
        "js.remaining",
        "js.timer_completed",
        "js.timer_running",
        "js.timer_paused",
        "js.timer_resumed",
        "js.pause_timer",
        "js.resume_timer",
        "js.failed_to_fetch_timer",
        "js.resume_room_input",
        "js.pause_room_input",
        "js.room_input_paused",
        "js.room_input_active",
        "js.control_type_prompt",
        "js.button",
        "js.unknown_control_type",
        "js.control_label_prompt",
        "js.new_control",
        "js.post_path_prompt",
        "js.action_sent",
        "js.timer_started",
        "js.timer_reset",
        "js.added_seconds_total",
        "js.added_seconds_taken",
        "js.valid_seconds",
        "js.completion_time_left",
        "js.completion_overtime",
        "js.announcement_sent",
        "js.announcement_cancelled",
        "js.select_hint",
        "js.saved_hint_sent",
        "js.room_result_saved",
        "js.hint_number",
        "js.timer_value",
        "js.utc",
        "js.hint_image",
        "js.no_hints",
        "js.no_actions",
        "js.one_column",
        "js.two_columns",
        "js.half_height",
        "js.double_height",
        "js.done_editing",
        "js.edit_controls",
        "js.gpio_action_triggered",
        "js.output_on",
        "js.output_off",
    ),
    "home": (
        "js.players",
        "js.hints",
        "js.penalties",
        "js.time",
        "js.left",
        "js.overtime",
        "js.congratulations",
        "js.time_remaining",
        "js.time_taken",
    ),
}


@lru_cache(maxsize=None)
def _load_catalog(locale: str) -> dict[str, str]:
    with (CATALOG_DIRECTORY / f"{locale}.json").open(encoding="utf-8") as file:
        catalog = json.load(file)
    if not isinstance(catalog, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in catalog.items()
    ):
        raise RuntimeError(
            f"Translation catalog for {locale!r} must map strings to strings."
        )
    return catalog


@lru_cache(maxsize=1)
def _catalog_locales() -> frozenset[str]:
    return frozenset(path.stem for path in CATALOG_DIRECTORY.glob("*.json"))


def _supported_locales(app: Flask) -> tuple[str, ...]:
    configured = app.config.get("SUPPORTED_LOCALES", ("en",))
    if isinstance(configured, str):
        configured = (configured,)
    catalogs = _catalog_locales()
    return tuple(
        locale
        for locale in configured
        if isinstance(locale, str) and locale in catalogs
    ) or ("en",)


def _current_locale(app: Flask) -> str:
    supported = _supported_locales(app)
    requested = request.args.get("locale")
    if requested in supported:
        session["locale"] = requested
        return requested
    saved = session.get("locale")
    if saved in supported:
        return saved
    default = app.config.get("DEFAULT_LOCALE", "en")
    return default if default in supported else supported[0]


def translate(locale: str, key: str, **values: object) -> str:
    catalog = _load_catalog(locale)
    source_catalog = _load_catalog("en")
    text = catalog.get(key, source_catalog.get(key, key))
    try:
        return text.format(**values)
    except (KeyError, ValueError):
        return text


def _client_translations(locale: str, group: str) -> dict[str, str]:
    return {
        key: translate(locale, key)
        for key in CLIENT_TRANSLATION_GROUPS.get(group, ())
    }


def register_localization(app: Flask) -> None:
    _load_catalog("en")

    @app.before_request
    def select_locale() -> None:
        g.locale = _current_locale(app)

    @app.context_processor
    def inject_localization() -> Mapping[str, Any]:
        locale = g.locale
        return {
            "current_locale": locale,
            "supported_locales": _supported_locales(app),
            "locale_names": app.config["LOCALE_NAMES"],
            "t": lambda key, **values: translate(locale, key, **values),
            "client_translations": lambda group: _client_translations(locale, group),
        }
