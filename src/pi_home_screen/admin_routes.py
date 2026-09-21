import secrets
import subprocess
from pathlib import Path
from typing import Any, cast

from flask import (
    Flask,
    Response,
    abort,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .runtime import DisplayRuntime
from .localization import translate
from .uploads import (
    delete_uploaded_files,
    save_background_image,
    save_hint_media,
    save_sound,
)


def register_admin_routes(app: Flask, runtime: DisplayRuntime) -> None:
    store = runtime.store
    gpio = runtime.gpio
    display_power = runtime.display_power
    upload_folder = Path(app.config["UPLOAD_FOLDER"])

    def require_admin() -> None:
        if not session.get("admin"):
            abort(401)

    def require_csrf() -> None:
        token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
        session_token = session.get("csrf_token")
        if (
            token is None
            or session_token is None
            or not secrets.compare_digest(token, session_token)
        ):
            abort(400, "Invalid CSRF token.")

    def csrf_token() -> str:
        return cast(str, session["csrf_token"])

    def request_values() -> dict[str, Any] | None:
        values = request.get_json(silent=True) or request.form.to_dict()
        return values if isinstance(values, dict) else None

    def render_admin_page() -> str:
        gpio_paused, _activity = store.get_gpio_activity()
        return render_template(
            "admin.html",
            settings=store.get(),
            hints=store.get_hints(),
            hint_presets=store.get_hint_presets(),
            gpio_outputs=gpio.output_names(),
            gpio_output_actions=store.get_gpio_output_actions(),
            gpio_available=gpio.available,
            display_power_available=display_power.available,
            gpio_paused=gpio_paused,
            csrf_token=csrf_token(),
        )

    def render_settings_page(error: str | None = None) -> str:
        context: dict[str, Any] = {
            "settings": store.get(),
            "csrf_token": csrf_token(),
        }
        if error is not None:
            context["error"] = error
        return render_template("settings.html", **context)

    def render_hint_library(error: str | None = None) -> str:
        context: dict[str, Any] = {
            "settings": store.get(),
            "presets": store.get_hint_presets(),
            "csrf_token": csrf_token(),
        }
        if error is not None:
            context["error"] = error
        return render_template("hints.html", **context)

    def render_gpio_page(error: str | None = None) -> str:
        paused, activity = store.get_gpio_activity()
        context: dict[str, Any] = {
            "settings": store.get(),
            "mappings": store.get_gpio_mappings(),
            "paused": paused,
            "activity": activity,
            "csrf_token": csrf_token(),
            "gpio_available": gpio.available,
            "display_power_available": display_power.available,
            "gpio_outputs": gpio.output_names(),
            "gpio_output_pins": gpio.output_pins(),
            "gpio_output_actions": store.get_gpio_output_actions(),
            "hint_presets": store.get_hint_presets(),
        }
        if error is not None:
            context["error"] = error
        return render_template("gpio.html", **context)

    def render_statistics_page(error: str | None = None) -> str:
        context: dict[str, Any] = {
            "settings": store.get(),
            "statistics": store.get_statistics(),
            "leaderboard": store.get_leaderboard(),
            "csrf_token": csrf_token(),
        }
        if error is not None:
            context["error"] = error
        return render_template("stats.html", **context)

    def render_sound_page(error: str | None = None) -> str:
        context: dict[str, Any] = {
            "settings": store.get(),
            "csrf_token": csrf_token(),
        }
        if error is not None:
            context["error"] = error
        return render_template("sounds.html", **context)

    def remove_old_sound_files(
        old_settings: Any,
        notification_filename: str | None,
        success_filename: str | None,
        failed_filename: str | None,
        remove_notification: bool,
        remove_success: bool,
        remove_failed: bool,
    ) -> None:
        filenames_to_remove: list[str | None] = []
        if notification_filename and old_settings.notification_sound_filename:
            filenames_to_remove.append(old_settings.notification_sound_filename)
        if success_filename and old_settings.success_sound_filename:
            filenames_to_remove.append(old_settings.success_sound_filename)
        if failed_filename and old_settings.failed_sound_filename:
            filenames_to_remove.append(old_settings.failed_sound_filename)
        if (
            remove_notification
            and old_settings.notification_sound_filename
            and not notification_filename
        ):
            filenames_to_remove.append(old_settings.notification_sound_filename)
        if remove_success and old_settings.success_sound_filename and not success_filename:
            filenames_to_remove.append(old_settings.success_sound_filename)
        if remove_failed and old_settings.failed_sound_filename and not failed_filename:
            filenames_to_remove.append(old_settings.failed_sound_filename)
        try:
            delete_uploaded_files(upload_folder, filenames_to_remove)
        except OSError:
            app.logger.exception("Failed to delete old sound file")

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login() -> str | Response:
        if request.method == "POST":
            if secrets.compare_digest(
                request.form.get("password", ""),
                app.config["ADMIN_PASSWORD"],
            ):
                locale = g.locale
                session.clear()
                session["locale"] = locale
                session["admin"] = True
                session["csrf_token"] = secrets.token_urlsafe(32)
                return redirect(url_for("admin"))
            return (
                render_template(
                    "login.html",
                    error=translate(g.locale, "login.invalid_password"),
                ),
                401,
            )
        return render_template("login.html")

    @app.post("/admin/logout")
    def admin_logout() -> Response:
        require_admin()
        require_csrf()
        session.clear()
        return redirect(url_for("admin_login"))

    @app.get("/admin")
    def admin() -> str | Response:
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return render_admin_page()

    @app.route("/admin/settings", methods=["GET", "POST"])
    def settings() -> str | Response:
        require_admin()
        if request.method == "POST":
            require_csrf()
            try:
                uploaded_image = save_background_image(
                    request.files.get("background_image"),
                    upload_folder,
                )
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
                    remove_background_image=request.form.get(
                        "remove_background_image"
                    )
                    == "on",
                )
            except ValueError as error:
                return render_settings_page(str(error)), 400
            runtime.publish(settings)
            return redirect(url_for("settings"))
        return render_settings_page()

    @app.get("/admin/stats")
    def statistics() -> str:
        require_admin()
        return render_statistics_page()

    @app.get("/admin/hints")
    def hint_library() -> str:
        require_admin()
        return render_hint_library()

    @app.post("/admin/hints")
    def create_hint_preset() -> Response:
        require_admin()
        require_csrf()
        json_values = request.get_json(silent=True) if not request.form else None
        values = json_values if isinstance(json_values, dict) else request.form
        kind = values.get("kind", "text")
        try:
            media_filename = None
            if kind in ("image", "video"):
                media_filename = save_hint_media(
                    request.files.get("media"),
                    kind,
                    upload_folder,
                )
            preset = store.add_hint_preset(
                kind,
                values.get("title"),
                values.get("message"),
                media_filename,
                values.get("full_screen"),
            )
        except ValueError as error:
            if request.form:
                return render_hint_library(str(error)), 400
            return jsonify(error=str(error)), 400
        runtime.record_action("hint_preset", f"Created hint preset '{preset.title}'")
        if request.form:
            return redirect(url_for("hint_library"))
        return jsonify(preset.to_dict())

    @app.post("/admin/hints/<int:preset_id>/delete")
    def delete_hint_preset(preset_id: int) -> Response:
        require_admin()
        require_csrf()
        preset = store.get_hint_preset(preset_id)
        deleted = store.delete_hint_preset(preset_id)
        if deleted and preset is not None and preset.media_filename:
            try:
                delete_uploaded_files(upload_folder, [preset.media_filename])
            except OSError:
                app.logger.exception("Failed to delete hint media file")
        if deleted and preset is not None:
            runtime.record_action(
                "hint_preset",
                f"Deleted hint preset '{preset.title}'",
            )
        if request.form:
            return redirect(url_for("hint_library"))
        return jsonify(deleted=deleted)

    @app.post("/admin/hints/<int:preset_id>/send")
    def send_hint_preset(preset_id: int) -> Response:
        require_admin()
        require_csrf()
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
        runtime.record_action("announcement", f"Sent preset hint: {preset.title}")
        runtime.publish(settings)
        response = settings.to_dict()
        response["hint"] = hint.to_dict()
        return jsonify(response)

    @app.get("/admin/gpio")
    def gpio_settings() -> str:
        require_admin()
        return render_gpio_page()

    @app.post("/admin/gpio/mappings")
    def add_gpio_mapping() -> Response:
        require_admin()
        require_csrf()
        try:
            raw_pin = request.form.get("pin")
            if (
                isinstance(raw_pin, str)
                and raw_pin.isdecimal()
                and 0 <= int(raw_pin) <= 27
                and gpio.is_output_pin(int(raw_pin))
            ):
                raise ValueError("That BCM pin is already configured as an output.")
            store.add_gpio_mapping(
                raw_pin,
                request.form.get("event"),
                request.form.get("preset_id"),
            )
        except ValueError as error:
            return render_gpio_page(str(error)), 400
        runtime.record_action(
            "gpio",
            "Added GPIO mapping "
            f"pin={request.form.get('pin')} "
            f"event={request.form.get('event')} "
            f"preset={request.form.get('preset_id')}",
        )
        try:
            runtime.configure_gpio_inputs()
        except ValueError as error:
            store.delete_gpio_mapping(int(raw_pin))
            return render_gpio_page(str(error)), 400
        return redirect(url_for("gpio_settings"))

    @app.post("/admin/gpio/mappings/<int:pin>/delete")
    def delete_gpio_mapping(pin: int) -> Response:
        require_admin()
        require_csrf()
        if not store.delete_gpio_mapping(pin):
            abort(404)
        runtime.record_action("gpio", f"Deleted GPIO mapping pin={pin}")
        runtime.configure_gpio_inputs()
        return redirect(url_for("gpio_settings"))

    @app.post("/admin/gpio/actions")
    def add_gpio_output_action() -> Response:
        require_admin()
        require_csrf()
        try:
            if request.form.get("output_name") is not None:
                action = store.add_gpio_output_action(
                    request.form.get("label") or request.form.get("title"),
                    request.form.get("output_name"),
                    request.form.get("state"),
                    gpio.output_names(),
                )
            else:
                raw_pin = request.form.get("pin")
                if (
                    isinstance(raw_pin, str)
                    and raw_pin.isdecimal()
                    and 0 <= int(raw_pin) <= 27
                    and runtime.is_gpio_input_pin(int(raw_pin))
                ):
                    raise ValueError("That BCM pin is already configured as an input.")
                if (
                    isinstance(raw_pin, str)
                    and raw_pin.isdecimal()
                    and 0 <= int(raw_pin) <= 27
                    and gpio.is_output_pin(int(raw_pin))
                ):
                    raise ValueError("That BCM pin is already configured as an output.")
                action = store.add_gpio_trigger_event(
                    request.form.get("title") or request.form.get("label"),
                    raw_pin,
                    request.form.get("state"),
                )
        except ValueError as error:
            return render_gpio_page(str(error)), 400
        runtime.record_action(
            "gpio",
            f"Created trigger event '{action.title}' for "
            f"{action.output_name or f'BCM {action.pin}'} ({action.state})",
        )
        return redirect(url_for("gpio_settings"))

    @app.post("/admin/gpio/actions/<int:action_id>/delete")
    def delete_gpio_output_action(action_id: int) -> Response:
        require_admin()
        require_csrf()
        action = store.get_gpio_output_action(action_id)
        if action is None:
            abort(404)
        if not store.delete_gpio_output_action(action_id):
            abort(404)
        if action.pin is not None and not store.has_gpio_trigger_event_for_pin(action.pin):
            gpio.release_pin(action.pin)
        runtime.record_action("gpio", f"Deleted extra GPIO button id={action_id}")
        return redirect(url_for("gpio_settings"))

    @app.post("/admin/gpio/pause")
    def set_gpio_paused() -> Response:
        require_admin()
        require_csrf()
        values = request_values()
        if values is None:
            return jsonify(error="A GPIO pause setting is required."), 400
        paused = values.get("paused")
        if not isinstance(paused, bool) and paused not in ("on", "off"):
            return jsonify(error="GPIO pause setting must be true or false."), 400
        is_paused = paused is True or paused == "on"
        store.set_gpio_paused(is_paused)
        runtime.record_action("gpio", f"Set GPIO paused = {paused}")
        if request.is_json:
            return jsonify(paused=is_paused)
        return redirect(url_for("gpio_settings"))

    @app.post("/admin/display/toggle")
    def toggle_display_power() -> Response:
        require_admin()
        require_csrf()
        try:
            is_on = runtime.toggle_display_power()
        except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
            return jsonify(error=str(error)), 503
        if request.is_json:
            return jsonify(display_on=is_on)
        return redirect(url_for("admin"))

    @app.post("/admin/stats")
    def add_statistic() -> Response:
        require_admin()
        require_csrf()
        try:
            store.add_statistic(
                request.form.get("label"),
                request.form.get("value"),
            )
        except ValueError as error:
            return render_statistics_page(str(error)), 400
        return redirect(url_for("statistics"))

    @app.post("/admin/stats/<int:statistic_id>/delete")
    def delete_statistic(statistic_id: int) -> Response:
        require_admin()
        require_csrf()
        if not store.delete_statistic(statistic_id):
            abort(404)
        return redirect(url_for("statistics"))

    @app.post("/api/admin/settings")
    def update_settings() -> Response:
        require_admin()
        require_csrf()
        values = request.get_json(silent=True)
        if not isinstance(values, dict):
            return jsonify(error="A JSON settings object is required."), 400
        try:
            settings = store.update(values)
        except ValueError as error:
            return jsonify(error=str(error)), 400
        runtime.publish(settings)
        return jsonify(settings.to_dict())

    @app.post("/admin/timer/<action>")
    def update_timer(action: str) -> Response:
        require_admin()
        require_csrf()
        try:
            if action == "start":
                settings = store.start_timer()
                runtime.record_action("timer", "Started 60-minute timer")
            elif action == "reset":
                settings = store.reset_timer()
                runtime.record_action("timer", "Reset timer")
            elif action == "pause":
                settings = store.toggle_timer_paused()
                description = "Paused timer" if settings.timer_paused_at else "Resumed timer"
                runtime.record_action("timer", description)
            else:
                abort(404)
        except ValueError as error:
            return jsonify(error=str(error)), 400
        runtime.publish(settings)
        if action in ("start", "pause") and settings.timer_paused_at is None:
            runtime.schedule_automatic_hint(settings)
        else:
            runtime.cancel_automatic_hint()
        if request.form:
            return redirect(url_for("admin"))
        return jsonify(settings.to_dict())

    @app.post("/admin/timer/adjust")
    def adjust_timer() -> Response:
        require_admin()
        require_csrf()
        values = request_values()
        if values is None:
            return jsonify(error="A JSON timer adjust object is required."), 400
        seconds = values.get("seconds")
        try:
            seconds_int = int(seconds)
        except Exception:
            return jsonify(
                error="seconds must be an integer number of seconds."
            ), 400
        try:
            settings = store.adjust_timer(seconds_int)
        except ValueError as error:
            return jsonify(error=str(error)), 400
        description = (
            f"Added {seconds_int} seconds to total time"
            if seconds_int >= 0
            else f"Added {-seconds_int} seconds penalty to time taken"
        )
        runtime.record_action("timer_adjust", description)
        runtime.publish(settings)
        if request.form:
            return redirect(url_for("admin"))
        return jsonify(settings.to_dict())

    @app.post("/admin/complete")
    def complete_room() -> Response:
        require_admin()
        require_csrf()
        try:
            settings = store.complete_room()
        except ValueError as error:
            return jsonify(error=str(error)), 409
        runtime.record_action("room", "Completed room")
        runtime.publish(settings)
        runtime.cancel_automatic_hint()
        if request.form:
            return redirect(url_for("admin"))
        return jsonify(settings.to_dict())

    @app.get("/admin/api/hints")
    def admin_hints() -> Response:
        require_admin()
        hints = [hint.to_dict() for hint in store.get_hints()]
        return jsonify(hints)

    @app.get("/admin/api/actions")
    def admin_actions() -> Response:
        require_admin()
        return jsonify(store.get_actions_for_current_run())

    @app.post("/admin/results")
    def save_completion_result() -> Response:
        require_admin()
        require_csrf()
        values = request_values()
        if values is None:
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
        runtime.record_action(
            "result",
            f"Saved result for {result.group_name} ({result.group_size} players)",
        )
        if request.form:
            return redirect(url_for("admin"))
        return jsonify(result.to_dict())

    @app.post("/admin/announcement")
    def send_announcement() -> Response:
        require_admin()
        require_csrf()
        values = request_values()
        if values is None:
            return jsonify(error="A JSON announcement object is required."), 400
        try:
            settings, hint = store.send_announcement(values.get("message"))
        except ValueError as error:
            return jsonify(error=str(error)), 400
        runtime.record_action("announcement", f"Sent announcement: {hint.message}")
        runtime.publish(settings)
        if request.form:
            return redirect(url_for("admin"))
        response = settings.to_dict()
        response["hint"] = hint.to_dict()
        return jsonify(response)

    @app.post("/admin/announcement/cancel")
    def cancel_announcement() -> Response:
        require_admin()
        require_csrf()
        settings = store.cancel_announcement()
        if settings is None:
            return jsonify(error="No active announcement to cancel."), 409
        runtime.record_action("announcement", "Cancelled active announcement")
        runtime.publish(settings)
        if request.form:
            return redirect(url_for("admin"))
        return jsonify(settings.to_dict())

    @app.post("/admin/automatic-hint")
    def set_automatic_hint() -> Response:
        require_admin()
        require_csrf()
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
        require_admin()
        require_csrf()
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

    @app.post("/admin/gpio/actions/<int:action_id>/trigger")
    def trigger_gpio_output_action(action_id: int) -> Response:
        require_admin()
        require_csrf()
        action = store.get_gpio_output_action(action_id)
        if action is None:
            abort(404)
        try:
            if action.pin is not None:
                if action.state == "on":
                    gpio.activate_pin(action.pin)
                else:
                    gpio.deactivate_pin(action.pin)
            elif action.output_name is None or action.output_name not in gpio.output_names():
                abort(404)
            elif action.state == "on":
                gpio.activate(action.output_name)
            else:
                gpio.deactivate(action.output_name)
        except KeyError:
            abort(404)
        except ValueError as error:
            return jsonify(error=str(error)), 409
        except RuntimeError:
            return jsonify(error="GPIO hardware is unavailable."), 503
        runtime.record_action(
            "gpio",
            f"Triggered extra GPIO button '{action.title}' for "
            f"{action.output_name or f'BCM {action.pin}'} ({action.state})",
        )
        response: dict[str, object] = dict(
            action_id=action.id,
            label=action.title,
            output_name=action.output_name,
            state=action.state,
        )
        if action.pin is not None:
            response.update(title=action.title, pin=action.pin)
        return jsonify(response)

    @app.get("/admin/sounds")
    def sound_settings() -> str:
        require_admin()
        return render_sound_page()

    @app.post("/admin/sounds")
    def upload_sounds() -> Response:
        require_admin()
        require_csrf()
        old_settings = store.get()
        uploaded_filenames: list[str] = []
        try:
            notification_filename = save_sound(
                request.files.get("notification_sound"),
                upload_folder,
            )
            if notification_filename:
                uploaded_filenames.append(notification_filename)
            success_filename = save_sound(
                request.files.get("success_sound"),
                upload_folder,
            )
            if success_filename:
                uploaded_filenames.append(success_filename)
            failed_filename = save_sound(
                request.files.get("failed_sound"),
                upload_folder,
            )
            if failed_filename:
                uploaded_filenames.append(failed_filename)
        except ValueError as error:
            delete_uploaded_files(upload_folder, uploaded_filenames)
            return render_sound_page(str(error)), 400
        remove_notification = request.form.get("remove_notification_sound") == "on"
        remove_success = request.form.get("remove_success_sound") == "on"
        remove_failed = request.form.get("remove_failed_sound") == "on"
        settings = store.update_sounds(
            notification_filename=notification_filename,
            success_filename=success_filename,
            failed_filename=failed_filename,
            remove_notification=remove_notification,
            remove_success=remove_success,
            remove_failed=remove_failed,
        )
        remove_old_sound_files(
            old_settings,
            notification_filename,
            success_filename,
            failed_filename,
            remove_notification,
            remove_success,
            remove_failed,
        )
        runtime.record_action("sounds", "Updated event sounds")
        runtime.publish(settings)
        if request.form:
            return redirect(url_for("sound_settings"))
        return jsonify(settings.to_dict())
