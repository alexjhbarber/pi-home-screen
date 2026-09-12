import json
import os
import secrets
from threading import Timer
from pathlib import Path
from typing import Any
from uuid import uuid4

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.datastructures import FileStorage

from .database import initialize
from .display import DisplaySettingsStore
from .events import DisplayUpdateBroker
from .gpio import GpioController


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    project_directory = Path(__file__).resolve().parents[2]
    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder=str(project_directory / "templates"),
        static_folder=str(project_directory / "static"),
    )
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD"),
        DATABASE=str(Path(app.instance_path) / "home_screen.db"),
        GPIO_OUTPUTS=os.environ.get("GPIO_OUTPUTS", "{}"),
        GPIO_INPUTS=os.environ.get("GPIO_INPUTS", "{}"),
        UPLOAD_FOLDER=str(Path(app.instance_path) / "uploads"),
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,
    )
    if test_config is not None:
        app.config.update(test_config)
    if not app.config["SECRET_KEY"] or not app.config["ADMIN_PASSWORD"]:
        raise RuntimeError("SECRET_KEY and ADMIN_PASSWORD environment variables must be set.")

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
    app.extensions["display_store"] = store
    app.extensions["display_broker"] = broker
    app.extensions["gpio"] = gpio
    auto_hint_timer: Timer | None = None

    def configure_gpio_inputs() -> None:
        saved_mappings = store.get_gpio_mappings()
        gpio.configure_inputs(
            (
                [(event, pin) for event, pin in configured_gpio_inputs.items()]
                if not saved_mappings
                else [(mapping.event, mapping.pin) for mapping in saved_mappings]
            ),
            handle_gpio_event,
        )

    def handle_gpio_event(pin: int, event: str) -> None:
        paused, _activity = store.get_gpio_activity()
        if paused:
            store.record_gpio_event(pin, event, accepted=False)
            return
        try:
            mapping = store.get_gpio_mapping_by_pin(pin)
            if mapping is None:
                # fallback to old behaviour for compatibility
                if event == "complete-room":
                    broker.publish(store.complete_room())
                    store.record_gpio_event(pin, event, accepted=True)
                return
            if mapping.event == "complete-room":
                broker.publish(store.complete_room())
                store.record_gpio_event(pin, mapping.event, accepted=True)
            elif mapping.event == "send-preset":
                if mapping.preset_id is None:
                    store.record_gpio_event(pin, mapping.event, accepted=False)
                    app.logger.warning("GPIO mapping has no preset_id.")
                    return
                preset = store.get_hint_preset(mapping.preset_id)
                if preset is None:
                    store.record_gpio_event(pin, mapping.event, accepted=False)
                    app.logger.warning("GPIO mapping refers to missing preset id %s.", mapping.preset_id)
                    return
                media_type = None if preset.kind == "text" else preset.kind
                try:
                    settings, hint = store.send_announcement(
                        preset.message or "",
                        media_type=media_type,
                        media_filename=preset.media_filename,
                        media_full_screen=preset.full_screen,
                    )
                except ValueError:
                    store.record_gpio_event(pin, mapping.event, accepted=False)
                    app.logger.warning("Ignored GPIO send-preset input because the timer is not running.")
                    return
                try:
                    store.record_action('announcement', f"GPIO sent preset hint: {preset.title}")
                except Exception:
                    app.logger.exception('Failed to record action')
                broker.publish(settings)
                store.record_gpio_event(pin, mapping.event, accepted=True)
        except ValueError:
            store.record_gpio_event(pin, event, accepted=False)
            app.logger.warning("Ignored GPIO room-complete input because the timer is not running.")

    def schedule_automatic_hint(settings) -> None:
        nonlocal auto_hint_timer
        if auto_hint_timer is not None:
            auto_hint_timer.cancel()
            auto_hint_timer = None
        if settings.auto_hint_remaining_minutes is None or settings.auto_hint_message is None:
            return
        delay = (60 - settings.auto_hint_remaining_minutes) * 60

        def send_if_room_is_incomplete() -> None:
            current = store.get()
            if current.timer_started_at == settings.timer_started_at and current.room_completed_at is None:
                updated, _hint = store.send_announcement(settings.auto_hint_message)
                broker.publish(updated)

        auto_hint_timer = Timer(delay, send_if_room_is_incomplete)
        auto_hint_timer.daemon = True
        auto_hint_timer.start()

    configure_gpio_inputs()

    @app.get("/")
    def home() -> str:
        return render_template("home.html", settings=store.get())

    @app.get("/api/display")
    def get_display() -> Response:
        settings = store.get().to_dict()
        latest = store.get_latest_result()
        if latest is not None:
            settings["latest_result"] = latest.to_dict()
        return jsonify(settings)

    @app.get("/api/gpio/activity")
    def get_gpio_activity() -> Response:
        paused, activity = store.get_gpio_activity()
        return jsonify(
            paused=paused,
            activity=[
                {
                    "pin": entry.pin, "event": entry.event, "accepted": entry.accepted,
                    "triggered_at": entry.triggered_at,
                }
                for entry in activity
            ],
        )

    @app.get("/uploads/<path:filename>")
    def uploaded_file(filename: str) -> Response:
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    @app.get("/events")
    def display_events() -> Response:
        return Response(
            broker.stream(store.get()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login() -> str | Response:
        if request.method == "POST":
            if secrets.compare_digest(
                request.form.get("password", ""), app.config["ADMIN_PASSWORD"]
            ):
                session.clear()
                session["admin"] = True
                session["csrf_token"] = secrets.token_urlsafe(32)
                return redirect(url_for("admin"))
            return render_template("login.html", error="Invalid password."), 401
        return render_template("login.html")

    @app.post("/admin/logout")
    def admin_logout() -> Response:
        _require_admin()
        _require_csrf()
        session.clear()
        return redirect(url_for("admin_login"))

    @app.get("/admin")
    def admin() -> str | Response:
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        gpio_paused, _activity = store.get_gpio_activity()
        return render_template(
            "admin.html",
            hints=store.get_hints(),
            hint_presets=store.get_hint_presets(),
            gpio_outputs=gpio.output_names(),
            gpio_available=gpio.available,
            gpio_paused=gpio_paused,
            csrf_token=session["csrf_token"],
        )

    @app.route("/admin/settings", methods=["GET", "POST"])
    def settings() -> str | Response:
        _require_admin()
        if request.method == "POST":
            _require_csrf()
            try:
                uploaded_image = _save_background_image(request.files.get("background_image"))
                settings = store.update(
                    {
                        name: request.form.get(name, "")
                        for name in (
                            "title",
                            "message",
                            "background_colour",
                            "accent_colour",
                        )
                    },
                    background_image=uploaded_image,
                    remove_background_image=request.form.get("remove_background_image")
                    == "on",
                )
            except ValueError as error:
                return render_template(
                    "settings.html",
                    settings=store.get(),
                    csrf_token=session["csrf_token"],
                    error=str(error),
                ), 400
            broker.publish(settings)
            return redirect(url_for("settings"))
        return render_template(
            "settings.html",
            settings=store.get(),
            csrf_token=session["csrf_token"],
        )

    @app.get("/admin/stats")
    def statistics() -> str:
        _require_admin()
        leaderboard = store.get_leaderboard()
        return render_template(
            "stats.html",
            statistics=store.get_statistics(),
            leaderboard=leaderboard,
            csrf_token=session["csrf_token"],
        )

    @app.get("/admin/hints")
    def hint_library() -> str:
        _require_admin()
        return render_template(
            "hints.html",
            presets=store.get_hint_presets(),
            csrf_token=session["csrf_token"],
        )

    @app.post("/admin/hints")
    def create_hint_preset() -> Response:
        _require_admin()
        _require_csrf()
        json_values = request.get_json(silent=True) if not request.form else None
        values = json_values if isinstance(json_values, dict) else request.form
        kind = values.get("kind", "text")
        try:
            media_filename = None
            if kind in ("image", "video"):
                media_filename = _save_hint_media(request.files.get("media"), kind)
            preset = store.add_hint_preset(
                kind,
                values.get("title"),
                values.get("message"),
                media_filename,
                values.get("full_screen"),
            )
        except ValueError as error:
            if request.form:
                return render_template(
                    "hints.html",
                    presets=store.get_hint_presets(),
                    csrf_token=session["csrf_token"],
                    error=str(error),
                ), 400
            return jsonify(error=str(error)), 400
        try:
            store.record_action('hint_preset', f"Created hint preset '{preset.title}'")
        except Exception:
            app.logger.exception('Failed to record action')
        if request.form:
            return redirect(url_for("hint_library"))
        return jsonify(preset.to_dict())

    @app.post("/admin/hints/<int:preset_id>/delete")
    def delete_hint_preset(preset_id: int) -> Response:
        _require_admin()
        _require_csrf()
        preset = store.get_hint_preset(preset_id)
        deleted = store.delete_hint_preset(preset_id)
        if deleted and preset is not None and preset.media_filename:
            try:
                (Path(app.config["UPLOAD_FOLDER"]) / preset.media_filename).unlink(missing_ok=True)
            except OSError:
                app.logger.exception('Failed to delete hint media file')
        if deleted and preset is not None:
            try:
                store.record_action('hint_preset', f"Deleted hint preset '{preset.title}'")
            except Exception:
                app.logger.exception('Failed to record action')
        if request.form:
            return redirect(url_for("hint_library"))
        return jsonify(deleted=deleted)

    @app.post("/admin/hints/<int:preset_id>/send")
    def send_hint_preset(preset_id: int) -> Response:
        _require_admin()
        _require_csrf()
        preset = store.get_hint_preset(preset_id)
        if preset is None:
            return jsonify(error="Hint preset not found."), 404
        media_type = None if preset.kind == "text" else preset.kind
        try:
            settings, hint = store.send_announcement(
                preset.message or "",
                media_type=media_type,
                media_filename=preset.media_filename,
                media_full_screen=preset.full_screen,
            )
        except ValueError as error:
            return jsonify(error=str(error)), 400
        try:
            store.record_action('announcement', f"Sent preset hint: {preset.title}")
        except Exception:
            app.logger.exception('Failed to record action')
        broker.publish(settings)
        response = settings.to_dict()
        response["hint"] = hint.to_dict()
        return jsonify(response)

    @app.get("/admin/gpio")
    def gpio_settings() -> str:
        _require_admin()
        paused, activity = store.get_gpio_activity()
        return render_template(
            "gpio.html", mappings=store.get_gpio_mappings(), paused=paused,
            activity=activity, csrf_token=session["csrf_token"], gpio_available=gpio.available,
            hint_presets=store.get_hint_presets(),
        )

    @app.post("/admin/gpio/mappings")
    def add_gpio_mapping() -> Response:
        _require_admin()
        _require_csrf()
        try:
            store.add_gpio_mapping(request.form.get("pin"), request.form.get("event"), request.form.get("preset_id"))
            try:
                store.record_action('gpio', f"Added GPIO mapping pin={request.form.get('pin')} event={request.form.get('event')} preset={request.form.get('preset_id')}")
            except Exception:
                app.logger.exception('Failed to record action')
        except ValueError as error:
            paused, activity = store.get_gpio_activity()
            return render_template(
                "gpio.html", mappings=store.get_gpio_mappings(), paused=paused,
                activity=activity, csrf_token=session["csrf_token"], gpio_available=gpio.available,
                error=str(error),
            ), 400
        configure_gpio_inputs()
        return redirect(url_for("gpio_settings"))

    @app.post("/admin/gpio/mappings/<int:pin>/delete")
    def delete_gpio_mapping(pin: int) -> Response:
        _require_admin()
        _require_csrf()
        if not store.delete_gpio_mapping(pin):
            abort(404)
        try:
            store.record_action('gpio', f"Deleted GPIO mapping pin={pin}")
        except Exception:
            app.logger.exception('Failed to record action')
        configure_gpio_inputs()
        return redirect(url_for("gpio_settings"))

    @app.post("/admin/gpio/pause")
    def set_gpio_paused() -> Response:
        _require_admin()
        _require_csrf()
        values = request.get_json(silent=True) or request.form.to_dict()
        if not isinstance(values, dict):
            return jsonify(error="A GPIO pause setting is required."), 400
        paused = values.get("paused")
        if not isinstance(paused, bool) and paused not in ("on", "off"):
            return jsonify(error="GPIO pause setting must be true or false."), 400
        store.set_gpio_paused(paused is True or paused == "on")
        try:
            store.record_action('gpio', f"Set GPIO paused = {paused}")
        except Exception:
            app.logger.exception('Failed to record action')
        if request.is_json:
            return jsonify(paused=paused is True or paused == "on")
        return redirect(url_for("gpio_settings"))

    @app.post("/admin/stats")
    def add_statistic() -> Response:
        _require_admin()
        _require_csrf()
        try:
            store.add_statistic(request.form.get("label"), request.form.get("value"))
        except ValueError as error:
            return render_template(
                "stats.html",
                statistics=store.get_statistics(),
                csrf_token=session["csrf_token"],
                error=str(error),
            ), 400
        return redirect(url_for("statistics"))

    @app.post("/admin/stats/<int:statistic_id>/delete")
    def delete_statistic(statistic_id: int) -> Response:
        _require_admin()
        _require_csrf()
        if not store.delete_statistic(statistic_id):
            abort(404)
        return redirect(url_for("statistics"))

    @app.post("/api/admin/settings")
    def update_settings() -> Response:
        _require_admin()
        _require_csrf()
        values = request.get_json(silent=True)
        if not isinstance(values, dict):
            return jsonify(error="A JSON settings object is required."), 400
        try:
            settings = store.update(values)
        except ValueError as error:
            return jsonify(error=str(error)), 400
        broker.publish(settings)
        return jsonify(settings.to_dict())

    @app.post("/admin/timer/<action>")
    def update_timer(action: str) -> Response:
        _require_admin()
        _require_csrf()
        if action == "start":
            settings = store.start_timer()
            # record action
            try:
                store.record_action('timer', 'Started 60-minute timer')
            except Exception:
                app.logger.exception('Failed to record action')
        elif action == "reset":
            settings = store.reset_timer()
            try:
                store.record_action('timer', 'Reset timer')
            except Exception:
                app.logger.exception('Failed to record action')
        else:
            abort(404)
        broker.publish(settings)
        if action == "start":
            schedule_automatic_hint(settings)
        elif auto_hint_timer is not None:
            auto_hint_timer.cancel()
        if request.form:
            return redirect(url_for("admin"))
        return jsonify(settings.to_dict())

    @app.post("/admin/timer/adjust")
    def adjust_timer() -> Response:
        """Adjust the timer by a number of seconds. JSON: {"seconds": int} or form field 'seconds'."""
        _require_admin()
        _require_csrf()
        values = request.get_json(silent=True) or request.form.to_dict()
        if not isinstance(values, dict):
            return jsonify(error="A JSON timer adjust object is required."), 400
        seconds = values.get("seconds")
        try:
            seconds_int = int(seconds)
        except Exception:
            return jsonify(error="seconds must be an integer number of seconds."), 400
        try:
            settings = store.adjust_timer(seconds_int)
        except ValueError as error:
            return jsonify(error=str(error)), 400
        # record adjust action
        try:
            description = (
                f"Added {seconds_int} seconds to total time"
                if seconds_int >= 0
                else f"Added {-seconds_int} seconds penalty to time taken"
            )
            store.record_action('timer_adjust', description)
        except Exception:
            app.logger.exception('Failed to record action')
        broker.publish(settings)
        if request.form:
            return redirect(url_for("admin"))
        return jsonify(settings.to_dict())

    @app.post("/admin/complete")
    def complete_room() -> Response:
        _require_admin()
        _require_csrf()
        try:
            settings = store.complete_room()
        except ValueError as error:
            return jsonify(error=str(error)), 409
        # record completion action
        try:
            store.record_action('room', 'Completed room')
        except Exception:
            app.logger.exception('Failed to record action')
        broker.publish(settings)
        if auto_hint_timer is not None:
            auto_hint_timer.cancel()
        if request.form:
            return redirect(url_for("admin"))
        return jsonify(settings.to_dict())

    @app.get("/admin/api/hints")
    def admin_hints() -> Response:
        _require_admin()
        hints = [h.to_dict() for h in store.get_hints()]
        return jsonify(hints)

    @app.get("/admin/api/actions")
    def admin_actions() -> Response:
        _require_admin()
        actions = store.get_actions_for_current_run()
        return jsonify(actions)

    @app.post("/admin/results")
    def save_completion_result() -> Response:
        _require_admin()
        _require_csrf()
        values = request.get_json(silent=True) or request.form.to_dict()
        if not isinstance(values, dict):
            return jsonify(error="A room result object is required."), 400
        try:
            result = store.save_completion_result(
                values.get("group_name"),
                values.get("group_size"),
                values.get("hints_used"),
                values.get("penalties"),
            )
        except ValueError as error:
            return jsonify(error=str(error)), 400
        # record save result action
        try:
            store.record_action('result', f"Saved result for {result.group_name} ({result.group_size} players)")
        except Exception:
            app.logger.exception('Failed to record action')
        if request.form:
            return redirect(url_for("admin"))
        return jsonify(result.to_dict())

    @app.post("/admin/announcement")
    def send_announcement() -> Response:
        _require_admin()
        _require_csrf()
        values = request.get_json(silent=True) or request.form.to_dict()
        if not isinstance(values, dict):
            return jsonify(error="A JSON announcement object is required."), 400
        try:
            settings, hint = store.send_announcement(values.get("message"))
        except ValueError as error:
            return jsonify(error=str(error)), 400
        # record announcement action
        try:
            store.record_action('announcement', f"Sent announcement: {hint.message}")
        except Exception:
            app.logger.exception('Failed to record action')
        broker.publish(settings)
        if request.form:
            return redirect(url_for("admin"))
        response = settings.to_dict()
        response["hint"] = hint.to_dict()
        return jsonify(response)

    @app.post("/admin/automatic-hint")
    def set_automatic_hint() -> Response:
        _require_admin()
        _require_csrf()
        try:
            store.set_automatic_hint(
                request.form.get("remaining_minutes"),
                request.form.get("message"),
            )
        except ValueError as error:
            return redirect(url_for("admin", auto_hint_error=str(error)))
        return redirect(url_for("admin"))

    @app.post("/admin/gpio/<name>/<state>")
    def update_gpio(name: str, state: str) -> Response:
        _require_admin()
        _require_csrf()
        try:
            if state == "on":
                gpio.activate(name)
            elif state == "off":
                gpio.deactivate(name)
            else:
                abort(404)
        except KeyError:
            abort(404)
        return jsonify(name=name, state=state)

    @app.errorhandler(401)
    def handle_unauthorized(_error: Exception) -> Response:
        if request.method == "GET" and request.path.startswith("/admin"):
            return redirect(url_for("admin_login"))
        return jsonify(error="Authentication is required."), 401

    def _require_admin() -> None:
        if not session.get("admin"):
            abort(401)

    def _require_csrf() -> None:
        token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
        if token is None or not secrets.compare_digest(token, session["csrf_token"]):
            abort(400, "Invalid CSRF token.")

    def _save_background_image(upload: FileStorage | None) -> str | None:
        if upload is None or not upload.filename:
            return None
        filename = upload.filename
        extension = Path(filename).suffix.lower()
        allowed_extensions = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
        signatures = {
            ".gif": (b"GIF87a", b"GIF89a"),
            ".jpeg": (b"\xff\xd8\xff",),
            ".jpg": (b"\xff\xd8\xff",),
            ".png": (b"\x89PNG\r\n\x1a\n",),
            ".webp": (b"RIFF",),
        }
        header = upload.stream.read(12)
        upload.stream.seek(0)
        is_valid_webp = extension == ".webp" and header[:4] == b"RIFF" and header[8:12] == b"WEBP"
        if (
            extension not in allowed_extensions
            or (extension != ".webp" and not header.startswith(signatures[extension]))
            or (extension == ".webp" and not is_valid_webp)
        ):
            raise ValueError("Background image must be a PNG, JPEG, GIF, or WebP file.")
        saved_name = f"{uuid4().hex}{extension}"
        upload.save(Path(app.config["UPLOAD_FOLDER"]) / saved_name)
        return saved_name

    def _save_hint_media(upload: FileStorage | None, kind: str) -> str | None:
        if upload is None or not upload.filename:
            return None
        extension = Path(upload.filename).suffix.lower()
        if kind == "image":
            allowed_extensions = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
            signatures = {
                ".gif": (b"GIF87a", b"GIF89a"),
                ".jpeg": (b"\xff\xd8\xff",),
                ".jpg": (b"\xff\xd8\xff",),
                ".png": (b"\x89PNG\r\n\x1a\n",),
                ".webp": (b"RIFF",),
            }
            header = upload.stream.read(12)
            upload.stream.seek(0)
            is_valid_webp = extension == ".webp" and header[:4] == b"RIFF" and header[8:12] == b"WEBP"
            if (
                extension not in allowed_extensions
                or (extension != ".webp" and not header.startswith(signatures[extension]))
                or (extension == ".webp" and not is_valid_webp)
            ):
                raise ValueError("Hint image must be a PNG, JPEG, GIF, or WebP file.")
        elif kind == "video":
            allowed_extensions = {".mp4", ".webm", ".mov"}
            if extension not in allowed_extensions:
                raise ValueError("Hint video must be an MP4, WebM, or MOV file.")
        else:
            raise ValueError("Unsupported hint media kind.")
        saved_name = f"{uuid4().hex}{extension}"
        upload.save(Path(app.config["UPLOAD_FOLDER"]) / saved_name)
        return saved_name

    return app


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
        raise RuntimeError(f"{setting_name} must map names to GPIO pin numbers from 0 to 27.")
    return mapping


def _parse_gpio_input_mapping(value: str | dict[str, int]) -> dict[str, int]:
    mapping = _parse_pin_mapping(value, "GPIO_INPUTS")
    if set(mapping) - {"complete-room"}:
        raise RuntimeError("GPIO_INPUTS supports only the 'complete-room' event.")
    return mapping
