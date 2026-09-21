import json
import os
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, redirect, request, url_for

from .admin_routes import register_admin_routes
from .database import initialize
from .display import DisplaySettingsStore
from .display_power import DisplayPowerController
from .events import DisplayUpdateBroker
from .gpio import GpioController
from .localization import register_localization
from .public_routes import register_public_routes
from .runtime import DisplayRuntime


DEFAULT_MAX_UPLOAD_MB = 8
MAX_UPLOAD_MB_LIMIT = 1024


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    project_directory = Path(__file__).resolve().parents[2]
    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder=str(project_directory / "templates"),
        static_folder=str(project_directory / "static"),
    )
    max_upload_mb = _load_max_upload_mb()
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD"),
        DATABASE=str(Path(app.instance_path) / "home_screen.db"),
        GPIO_OUTPUTS=os.environ.get("GPIO_OUTPUTS", "{}"),
        GPIO_INPUTS=os.environ.get("GPIO_INPUTS", "{}"),
        UPLOAD_FOLDER=str(Path(app.instance_path) / "uploads"),
        MAX_CONTENT_LENGTH=max_upload_mb * 1024 * 1024,
        MAX_UPLOAD_MB=max_upload_mb,
        DEFAULT_LOCALE=os.environ.get("DEFAULT_LOCALE", "en"),
        SUPPORTED_LOCALES=("en", "es"),
        LOCALE_NAMES={"en": "English", "es": "Español"},
    )
    if test_config is not None:
        app.config.update(test_config)
    _validate_required_config(app)

    database_path = Path(app.config["DATABASE"])
    initialize(database_path)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    store = DisplaySettingsStore(database_path)
    broker = DisplayUpdateBroker()
    configured_gpio_inputs = _parse_gpio_input_mapping(app.config["GPIO_INPUTS"])
    gpio = GpioController(
        output_pins=_parse_pin_mapping(app.config["GPIO_OUTPUTS"], "GPIO_OUTPUTS"),
        input_pins={},
    )
    display_power = DisplayPowerController()

    app.extensions["display_store"] = store
    app.extensions["display_broker"] = broker
    app.extensions["gpio"] = gpio
    app.extensions["display_power"] = display_power
    runtime = DisplayRuntime(
        app=app,
        store=store,
        broker=broker,
        gpio=gpio,
        display_power=display_power,
        configured_gpio_inputs=configured_gpio_inputs,
    )
    app.extensions["display_runtime"] = runtime
    runtime.initialize()

    register_localization(app)
    register_public_routes(app, runtime)
    register_admin_routes(app, runtime)
    _register_error_handlers(app)

    return app


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(401)
    def handle_unauthorized(_error: Exception) -> Response:
        if request.method == "GET" and request.path.startswith("/admin"):
            return redirect(url_for("admin_login"))
        return jsonify(error="Authentication is required."), 401

    @app.errorhandler(413)
    def handle_request_entity_too_large(_error: Exception) -> Response:
        message = _request_entity_too_large_message(app)
        if request.is_json or request.path.startswith("/api"):
            return jsonify(error=message), 413
        return message, 413


def _load_max_upload_mb() -> int:
    try:
        raw_value = int(os.environ.get("MAX_UPLOAD_MB", str(DEFAULT_MAX_UPLOAD_MB)))
    except (TypeError, ValueError):
        return DEFAULT_MAX_UPLOAD_MB
    return max(1, min(raw_value, MAX_UPLOAD_MB_LIMIT))


def _validate_required_config(app: Flask) -> None:
    if not app.config["SECRET_KEY"] or not app.config["ADMIN_PASSWORD"]:
        raise RuntimeError(
            "SECRET_KEY and ADMIN_PASSWORD environment variables must be set."
        )


def _request_entity_too_large_message(app: Flask) -> str:
    max_upload_mb = app.config.get("MAX_UPLOAD_MB")
    if max_upload_mb is None:
        max_upload_mb = app.config.get(
            "MAX_CONTENT_LENGTH",
            DEFAULT_MAX_UPLOAD_MB * 1024 * 1024,
        ) // (1024 * 1024)
    try:
        max_upload_text = f"{int(max_upload_mb)} MB"
    except Exception:
        max_upload_text = f"{DEFAULT_MAX_UPLOAD_MB} MB"
    return f"Uploaded file is too large. Maximum allowed size is {max_upload_text}."


def _parse_pin_mapping(value: str | dict[str, int], setting_name: str) -> dict[str, int]:
    if isinstance(value, dict):
        mapping = value
    else:
        try:
            mapping = json.loads(value)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"{setting_name} must be a JSON object.") from error
    if not isinstance(mapping, dict) or not all(
        isinstance(name, str) and isinstance(pin, int) and 0 <= pin <= 27
        for name, pin in mapping.items()
    ):
        raise RuntimeError(
            f"{setting_name} must map names to GPIO pin numbers from 0 to 27."
        )
    return mapping


def _parse_gpio_input_mapping(value: str | dict[str, int]) -> dict[str, int]:
    mapping = _parse_pin_mapping(value, "GPIO_INPUTS")
    if set(mapping) - {"complete-room", "start-timer", "display-toggle"}:
        raise RuntimeError(
            "GPIO_INPUTS supports only the 'complete-room', 'start-timer', "
            "and 'display-toggle' events."
        )
    return mapping
