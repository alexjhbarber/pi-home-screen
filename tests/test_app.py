import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import Flask
from flask.testing import FlaskClient

from pi_home_screen import create_app
from pi_home_screen.database import connect
from pi_home_screen.gpio import GpioController


class FakeOutputGpioController:
    def __init__(
        self,
        output_pins: dict[str, int] | None = None,
        **_kwargs: object,
    ) -> None:
        self._output_pins = output_pins or {}
        self._direct_pins: set[int] = set()
        self.available = True
        self.calls: list[tuple[str, str | int]] = []

    def configure_inputs(self, *_args: object) -> None:
        pass

    def output_names(self) -> list[str]:
        return sorted(self._output_pins)

    def output_pins(self) -> dict[str, int]:
        return dict(self._output_pins)

    def activate(self, name: str) -> None:
        if name not in self._output_pins:
            raise KeyError(name)
        self.calls.append(("on", name))

    def deactivate(self, name: str) -> None:
        if name not in self._output_pins:
            raise KeyError(name)
        self.calls.append(("off", name))

    def is_output_pin(self, pin: int) -> bool:
        return pin in self._output_pins.values() or pin in self._direct_pins

    def activate_pin(self, pin: int) -> None:
        self._direct_pins.add(pin)
        self.calls.append(("on", pin))

    def deactivate_pin(self, pin: int) -> None:
        self._direct_pins.add(pin)
        self.calls.append(("off", pin))

    def release_pin(self, pin: int) -> None:
        self._direct_pins.discard(pin)

    def close(self) -> None:
        pass


class HomeScreenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "screen.db"
        self.upload_folder = Path(self.temporary_directory.name) / "uploads"
        self.app = self.create_test_app()
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.app.extensions["gpio"].close()
        self.temporary_directory.cleanup()

    def create_test_app(self, **overrides: object) -> Flask:
        config: dict[str, object] = {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "ADMIN_PASSWORD": "test-password",
            "DATABASE": str(self.database_path),
            "UPLOAD_FOLDER": str(self.upload_folder),
            "GPIO_OUTPUTS": {},
            "GPIO_INPUTS": {},
        }
        config.update(overrides)
        return create_app(config)

    def login(self) -> str:
        return self.login_client(self.client)

    def login_client(self, client: FlaskClient) -> str:
        response = client.post(
            "/admin/login",
            data={"password": "test-password"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        with client.session_transaction() as session:
            return session["csrf_token"]

    def create_gpio_output_action_app(self) -> tuple[Flask, FlaskClient]:
        with patch("pi_home_screen.app.GpioController", FakeOutputGpioController):
            app = self.create_test_app(
                DATABASE=str(
                    Path(self.temporary_directory.name) / "gpio-output-actions.db"
                ),
                GPIO_OUTPUTS={"buzzer": 17},
            )
        self.addCleanup(app.extensions["gpio"].close)
        return app, app.test_client()

    def create_gpio_trigger_event_app(
        self,
        **overrides: object,
    ) -> tuple[Flask, FlaskClient]:
        with patch("pi_home_screen.app.GpioController", FakeOutputGpioController):
            app = self.create_test_app(
                DATABASE=str(
                    Path(self.temporary_directory.name) / "gpio-trigger-events.db"
                ),
                **overrides,
            )
        self.addCleanup(app.extensions["gpio"].close)
        return app, app.test_client()

    def test_home_renders_persisted_default_settings(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<html lang="en">', response.data)
        self.assertIn(b"Welcome", response.data)
        self.assertIn(b"Home screen", response.data)
        self.assertNotIn(b'class="language-selector"', response.data)

    def test_supported_locale_is_rendered_and_saved_for_the_current_session(self) -> None:
        response = self.client.get("/?locale=es")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<html lang="es">', response.data)
        self.assertIn("Pantalla principal".encode(), response.data)
        self.assertIn("Último equipo".encode(), response.data)

        follow_up = self.client.get("/")
        self.assertIn(b'<html lang="es">', follow_up.data)
        self.assertIn("Pantalla principal".encode(), follow_up.data)

    def test_unsupported_locale_keeps_the_safe_default(self) -> None:
        response = self.client.get("/?locale=unknown")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<html lang="en">', response.data)
        self.assertIn(b"Home screen", response.data)

    def test_admin_includes_on_demand_live_display_preview(self) -> None:
        self.login()
        response = self.client.get("/admin")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="preview-dialog"', response.data)
        self.assertIn(b"Open live preview", response.data)
        self.assertNotIn(b"Automatic hint", response.data)
        self.assertIn(b'id="completion-dialog"', response.data)
        self.assertIn(b"Group name", response.data)
        self.assertIn(b'id="control-grid"', response.data)
        self.assertIn(b"<summary>Settings</summary>", response.data)
        self.assertIn(b">Admin</a>", response.data)
        self.assertIn(b'class="admin-navigation-title">Welcome</h1>', response.data)
        self.assertIn(b'id="active-timer-state"', response.data)
        self.assertNotIn(b'id="edit-controls"', response.data)
        self.assertNotIn(b'id="add-control"', response.data)
        self.assertIn(b'id="toggle-gpio-pause"', response.data)
        self.assertIn(b"Pause room interaction", response.data)

    def test_all_admin_pages_include_global_navigation(self) -> None:
        self.login()

        for path in (
            "/admin",
            "/admin/settings",
            "/admin/gpio",
            "/admin/hints",
            "/admin/sounds",
            "/admin/stats",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'class="admin-navigation"', response.data)
                self.assertIn(b"<summary>Settings</summary>", response.data)

    def test_settings_page_saves_display_content(self) -> None:
        csrf_token = self.login()
        response = self.client.post(
            "/admin/settings",
            data={
                "csrf_token": csrf_token,
                "title": "Room One",
                "message": "Get ready.",
                "background_colour": "#012345",
                "accent_colour": "#abcdef",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        display = self.client.get("/api/display").get_json()
        self.assertEqual(display["title"], "Room One")
        self.assertIsNone(display["background_image"])
        admin_page = self.client.get("/admin")
        self.assertIn(b"<title>Room One</title>", admin_page.data)
        self.assertIn(
            b'<h1 class="admin-navigation-title">Room One</h1>',
            admin_page.data,
        )

    def test_logged_out_admin_pages_redirect_to_login(self) -> None:
        for path in ("/admin", "/admin/settings", "/admin/stats"):
            with self.subTest(path=path):
                response = self.client.get(path, follow_redirects=False)

                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["Location"], "/admin/login")

    def test_settings_page_includes_colour_selection_controls(self) -> None:
        self.login()
        response = self.client.get("/admin/settings")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="background-picker" type="color"', response.data)
        self.assertIn(b'id="background-hex" name="background_colour"', response.data)
        self.assertIn(b'id="background-preview"', response.data)
        self.assertIn(b"Accept background colour", response.data)
        self.assertIn(b'class="language-selector"', response.data)

    def test_settings_page_accepts_valid_background_image(self) -> None:
        csrf_token = self.login()
        response = self.client.post(
            "/admin/settings",
            data={
                "csrf_token": csrf_token,
                "title": "Room One",
                "message": "Get ready.",
                "background_colour": "#012345",
                "accent_colour": "#abcdef",
                "background_image": (BytesIO(b"\x89PNG\r\n\x1a\nimage-data"), "room.png"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        filename = self.client.get("/api/display").get_json()["background_image"]
        self.assertRegex(filename, r"^[0-9a-f]{32}\.png$")
        uploaded_image = self.client.get(f"/uploads/{filename}")
        self.assertEqual(uploaded_image.status_code, 200)
        response.close()
        uploaded_image.close()

    def test_sound_settings_accept_valid_sound_upload(self) -> None:
        csrf_token = self.login()
        response = self.client.post(
            "/admin/sounds",
            data={
                "csrf_token": csrf_token,
                "notification_sound": (BytesIO(b"RIFFsound-data"), "notify.wav"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        filename = self.client.get("/api/display").get_json()[
            "notification_sound_filename"
        ]
        self.assertRegex(filename, r"^[0-9a-f]{32}\.wav$")
        uploaded_sound = self.client.get(f"/uploads/{filename}")
        self.assertEqual(uploaded_sound.status_code, 200)
        response.close()
        uploaded_sound.close()

    def test_invalid_sound_upload_removes_earlier_uploads_in_the_request(self) -> None:
        csrf_token = self.login()
        response = self.client.post(
            "/admin/sounds",
            data={
                "csrf_token": csrf_token,
                "notification_sound": (BytesIO(b"RIFFsound-data"), "notify.wav"),
                "success_sound": (BytesIO(b"not-a-sound"), "success.txt"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(list(self.upload_folder.iterdir()), [])
        response.close()

    def test_sound_upload_rejects_request_larger_than_configured_limit(self) -> None:
        self.app.config.update(MAX_CONTENT_LENGTH=1024 * 1024, MAX_UPLOAD_MB=1)
        csrf_token = self.login()

        response = self.client.post(
            "/admin/sounds",
            data={
                "csrf_token": csrf_token,
                "notification_sound": (
                    BytesIO(b"0" * (1024 * 1024 + 1)),
                    "notify.mp3",
                ),
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 413)
        self.assertIn(b"Maximum allowed size is 1 MB.", response.data)
        response.close()

    def test_statistics_can_be_added_and_deleted(self) -> None:
        csrf_token = self.login()
        response = self.client.post(
            "/admin/stats",
            data={"csrf_token": csrf_token, "label": "Players", "value": "4"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        # UI removed; verify via the store directly
        stats = self.app.extensions["display_store"].get_statistics()
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0].label, "Players")
        self.assertEqual(stats[0].value, "4")
        statistic = stats[0]

        deleted = self.client.post(
            f"/admin/stats/{statistic.id}/delete",
            data={"csrf_token": csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(deleted.status_code, 302)
        self.assertEqual(self.app.extensions["display_store"].get_statistics(), [])

    def test_gpio_mapping_and_pause_setting_can_be_saved(self) -> None:
        csrf_token = self.login()
        response = self.client.post(
            "/admin/gpio/mappings",
            data={"csrf_token": csrf_token, "pin": "22", "event": "complete-room"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        page = self.client.get("/admin/gpio")
        self.assertIn(b"BCM 22", page.data)
        self.client.post(
            "/admin/gpio/pause",
            data={"csrf_token": csrf_token, "paused": "on"},
            follow_redirects=False,
        )
        self.assertTrue(self.client.get("/api/gpio/activity").get_json()["paused"])

    def test_admin_can_toggle_gpio_events(self) -> None:
        csrf_token = self.login()
        response = self.client.post(
            "/admin/gpio/pause",
            json={"paused": True},
            headers={"X-CSRF-Token": csrf_token},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["paused"])

    def test_gpio_output_action_can_be_created_rendered_and_deleted(self) -> None:
        app, client = self.create_gpio_output_action_app()
        csrf_token = self.login_client(client)

        empty_page = client.get("/admin")
        self.assertIn(b'id="no-gpio-output-actions"', empty_page.data)
        self.assertNotIn(b'class="btn placeholder"', empty_page.data)

        response = client.post(
            "/admin/gpio/actions",
            data={
                "csrf_token": csrf_token,
                "label": "Sound buzzer",
                "output_name": "buzzer",
                "state": "on",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        action = app.extensions["display_store"].get_gpio_output_actions()[0]
        self.assertEqual(action.label, "Sound buzzer")
        self.assertEqual(action.output_name, "buzzer")
        self.assertEqual(action.state, "on")
        self.assertIn(b"Sound buzzer", client.get("/admin").data)
        gpio_page = client.get("/admin/gpio")
        self.assertIn(b"Sound buzzer", gpio_page.data)
        self.assertIn(b"buzzer (BCM 17)", gpio_page.data)
        self.assertIn(b"Trigger event", gpio_page.data)

        deleted = client.post(
            f"/admin/gpio/actions/{action.id}/delete",
            data={"csrf_token": csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(deleted.status_code, 302)
        self.assertIn(b'id="no-gpio-output-actions"', client.get("/admin").data)

    def test_gpio_output_action_trigger_uses_its_configured_output(self) -> None:
        app, client = self.create_gpio_output_action_app()
        csrf_token = self.login_client(client)
        created = client.post(
            "/admin/gpio/actions",
            data={
                "csrf_token": csrf_token,
                "label": "Silence buzzer",
                "output_name": "buzzer",
                "state": "off",
            },
        )
        self.assertEqual(created.status_code, 302)
        action = app.extensions["display_store"].get_gpio_output_actions()[0]

        response = client.post(
            f"/admin/gpio/actions/{action.id}/trigger",
            headers={"X-CSRF-Token": csrf_token},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "action_id": action.id,
                "label": "Silence buzzer",
                "output_name": "buzzer",
                "state": "off",
            },
        )
        self.assertEqual(app.extensions["gpio"].calls, [("off", "buzzer")])

    def test_gpio_trigger_event_persists_renders_and_targets_its_bcm_pin(self) -> None:
        app, client = self.create_gpio_trigger_event_app()
        csrf_token = self.login_client(client)

        gpio_page = client.get("/admin/gpio")
        self.assertIn(
            b'name="pin" inputmode="numeric" min="0" max="27" type="number"',
            gpio_page.data,
        )
        self.assertIn(b"Trigger event", gpio_page.data)

        created = client.post(
            "/admin/gpio/actions",
            data={
                "csrf_token": csrf_token,
                "title": "Open magnetic lock",
                "pin": "18",
                "state": "on",
            },
            follow_redirects=False,
        )

        self.assertEqual(created.status_code, 302)
        action = app.extensions["display_store"].get_gpio_output_actions()[0]
        self.assertEqual(action.title, "Open magnetic lock")
        self.assertEqual(action.pin, 18)
        self.assertIsNone(action.output_name)
        self.assertEqual(action.state, "on")
        self.assertIn(b"Open magnetic lock", client.get("/admin").data)
        self.assertIn(b"BCM 18", client.get("/admin/gpio").data)

        triggered = client.post(
            f"/admin/gpio/actions/{action.id}/trigger",
            json={"pin": 27, "state": "off"},
            headers={"X-CSRF-Token": csrf_token},
        )

        self.assertEqual(triggered.status_code, 200)
        self.assertEqual(
            triggered.get_json(),
            {
                "action_id": action.id,
                "label": "Open magnetic lock",
                "output_name": None,
                "pin": 18,
                "state": "on",
                "title": "Open magnetic lock",
            },
        )
        self.assertEqual(app.extensions["gpio"].calls, [("on", 18)])

    def test_gpio_trigger_event_rejects_invalid_or_input_conflicting_pins(self) -> None:
        _app, client = self.create_gpio_trigger_event_app(
            GPIO_INPUTS={"complete-room": 20},
        )
        csrf_token = self.login_client(client)

        invalid = client.post(
            "/admin/gpio/actions",
            data={
                "csrf_token": csrf_token,
                "title": "Invalid target",
                "pin": "28",
                "state": "on",
            },
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertIn(b"GPIO pin must be a BCM pin number from 0 to 27.", invalid.data)

        conflicting = client.post(
            "/admin/gpio/actions",
            data={
                "csrf_token": csrf_token,
                "title": "Input conflict",
                "pin": "20",
                "state": "on",
            },
        )
        self.assertEqual(conflicting.status_code, 400)
        self.assertIn(b"That BCM pin is already configured as an input.", conflicting.data)

    def test_gpio_input_mapping_rejects_trigger_event_output_pin(self) -> None:
        _app, client = self.create_gpio_trigger_event_app()
        csrf_token = self.login_client(client)
        created = client.post(
            "/admin/gpio/actions",
            data={
                "csrf_token": csrf_token,
                "title": "Direct target",
                "pin": "21",
                "state": "off",
            },
        )
        self.assertEqual(created.status_code, 302)

        conflicting = client.post(
            "/admin/gpio/mappings",
            data={
                "csrf_token": csrf_token,
                "pin": "21",
                "event": "complete-room",
            },
        )
        self.assertEqual(conflicting.status_code, 400)
        self.assertIn(
            b"That BCM pin is already used by a trigger event output.",
            conflicting.data,
        )

    def test_direct_gpio_outputs_are_reused_and_reject_input_pins(self) -> None:
        with (
            patch("pi_home_screen.gpio.OutputDevice") as output_device,
            patch("pi_home_screen.gpio.Button", return_value=MagicMock()),
        ):
            controller = GpioController()
            controller.activate_pin(18)
            controller.deactivate_pin(18)
            output = output_device.return_value

            output_device.assert_called_once_with(18, initial_value=False)
            output.on.assert_called_once_with()
            output.off.assert_called_once_with()
            controller.configure_inputs({"complete-room": 20}, lambda *_args: None)
            with self.assertRaisesRegex(
                ValueError,
                "That BCM pin is already configured as an input.",
            ):
                controller.activate_pin(20)
            controller.release_pin(18)
            output.close.assert_called_once_with()
            controller.close()

    def test_gpio_trigger_event_creation_and_trigger_require_csrf_and_admin(self) -> None:
        app, client = self.create_gpio_trigger_event_app()
        csrf_token = self.login_client(client)

        self.assertEqual(
            client.post(
                "/admin/gpio/actions",
                data={"title": "Missing CSRF", "pin": "19", "state": "on"},
            ).status_code,
            400,
        )
        created = client.post(
            "/admin/gpio/actions",
            data={
                "csrf_token": csrf_token,
                "title": "Secure action",
                "pin": "19",
                "state": "on",
            },
        )
        self.assertEqual(created.status_code, 302)
        action = app.extensions["display_store"].get_gpio_output_actions()[0]
        self.assertEqual(
            client.post(f"/admin/gpio/actions/{action.id}/trigger").status_code,
            400,
        )
        self.assertEqual(
            app.test_client().post(
                f"/admin/gpio/actions/{action.id}/trigger"
            ).status_code,
            401,
        )

    def test_legacy_configured_output_actions_migrate_and_continue_to_trigger(self) -> None:
        legacy_database = Path(self.temporary_directory.name) / "legacy-gpio.db"
        with closing(connect(legacy_database)) as connection:
            connection.execute(
                """
                CREATE TABLE gpio_output_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label TEXT NOT NULL UNIQUE,
                    output_name TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('on', 'off'))
                )
                """
            )
            connection.execute(
                """
                INSERT INTO gpio_output_actions (label, output_name, state)
                VALUES ('Legacy buzzer', 'buzzer', 'on')
                """
            )
            connection.commit()

        with patch("pi_home_screen.app.GpioController", FakeOutputGpioController):
            app = self.create_test_app(
                DATABASE=str(legacy_database),
                GPIO_OUTPUTS={"buzzer": 17},
            )
        self.addCleanup(app.extensions["gpio"].close)
        client = app.test_client()
        csrf_token = self.login_client(client)
        action = app.extensions["display_store"].get_gpio_output_actions()[0]

        self.assertEqual(action.title, "Legacy buzzer")
        self.assertEqual(action.output_name, "buzzer")
        self.assertIsNone(action.pin)
        triggered = client.post(
            f"/admin/gpio/actions/{action.id}/trigger",
            headers={"X-CSRF-Token": csrf_token},
        )
        self.assertEqual(triggered.status_code, 200)
        self.assertEqual(app.extensions["gpio"].calls, [("on", "buzzer")])

    def test_gpio_output_action_rejects_unconfigured_output_and_invalid_state(self) -> None:
        _app, client = self.create_gpio_output_action_app()
        csrf_token = self.login_client(client)

        unconfigured = client.post(
            "/admin/gpio/actions",
            data={
                "csrf_token": csrf_token,
                "label": "Unsafe output",
                "output_name": "pin-27",
                "state": "on",
            },
        )
        self.assertEqual(unconfigured.status_code, 400)
        self.assertIn(b"Choose a configured GPIO output.", unconfigured.data)

        invalid_state = client.post(
            "/admin/gpio/actions",
            data={
                "csrf_token": csrf_token,
                "label": "Invalid signal",
                "output_name": "buzzer",
                "state": "pulse",
            },
        )
        self.assertEqual(invalid_state.status_code, 400)
        self.assertIn(
            b"Choose whether the GPIO output turns on or off.",
            invalid_state.data,
        )

        self.assertEqual(
            client.post(
                "/admin/gpio/actions",
                data={"label": "Missing CSRF", "output_name": "buzzer", "state": "on"},
            ).status_code,
            400,
        )

    def test_door_sensor_starts_timer_once_until_it_is_reset(self) -> None:
        class FakeGpioController:
            instance: "FakeGpioController"

            def __init__(self, **_kwargs: object) -> None:
                self.available = True
                self.inputs: list[tuple[str, int]] = []
                self.callback = None
                FakeGpioController.instance = self

            def configure_inputs(self, inputs, callback) -> None:
                self.inputs = list(inputs)
                self.callback = callback

            def output_names(self) -> list[str]:
                return []

            def close(self) -> None:
                pass

        with patch("pi_home_screen.app.GpioController", FakeGpioController):
            app = create_app(
                {
                    "TESTING": True,
                    "SECRET_KEY": "test-secret",
                    "ADMIN_PASSWORD": "test-password",
                    "DATABASE": str(Path(self.temporary_directory.name) / "configured-input.db"),
                    "GPIO_OUTPUTS": {},
                    "GPIO_INPUTS": {"start-timer": 17},
                }
            )

        self.assertEqual(FakeGpioController.instance.inputs, [("start-timer", 17)])
        FakeGpioController.instance.callback(17, "start-timer")
        self.assertIsNotNone(app.extensions["display_store"].get().timer_started_at)
        FakeGpioController.instance.callback(17, "start-timer")

        activity = app.test_client().get("/api/gpio/activity").get_json()["activity"]
        self.assertEqual(
            [(entry["event"], entry["accepted"]) for entry in activity],
            [("start-timer", False), ("start-timer", True)],
        )
        app.extensions["display_store"].reset_timer()
        FakeGpioController.instance.callback(17, "start-timer")
        activity = app.test_client().get("/api/gpio/activity").get_json()["activity"]
        self.assertTrue(activity[0]["accepted"])
        self.assertIsNotNone(app.extensions["display_store"].get().timer_started_at)
        app.extensions["gpio"].close()

    def test_automatic_hint_can_be_configured(self) -> None:
        csrf_token = self.login()
        response = self.client.post(
            "/admin/automatic-hint",
            data={
                "csrf_token": csrf_token,
                "remaining_minutes": "15",
                "message": "Check the painting.",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        settings = self.client.get("/api/display").get_json()
        self.assertEqual(settings["auto_hint_remaining_minutes"], 15)
        self.assertEqual(settings["auto_hint_message"], "Check the painting.")

    def test_events_emit_current_display_settings(self) -> None:
        response = self.client.get("/events", buffered=False)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            next(response.response),
            b'event: display\ndata: {"title":"Welcome","message":"Your message appears here.","background_colour":"#102a43","accent_colour":"#f6c453","timer_started_at":null,"room_completed_at":null,"announcement":null,"announcement_expires_at":null,"background_image":null,"auto_hint_remaining_minutes":null,"auto_hint_message":null,"extra_time_seconds":0,"penalty_time_seconds":0,"announcement_media_type":null,"announcement_media_filename":null,"announcement_media_full_screen":false,"notification_sound_filename":null,"success_sound_filename":null,"failed_sound_filename":null}\n\n',
        )
        response.close()

    def test_admin_settings_update_display_api(self) -> None:
        csrf_token = self.login()
        response = self.client.post(
            "/api/admin/settings",
            json={
                "title": "Game starts soon",
                "message": "Please wait outside.",
                "background_colour": "#001122",
                "accent_colour": "#ffeeaa",
            },
            headers={"X-CSRF-Token": csrf_token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["title"], "Game starts soon")
        self.assertEqual(
            self.client.get("/api/display").get_json()["message"],
            "Please wait outside.",
        )

    def test_admin_can_start_and_reset_the_timer(self) -> None:
        csrf_token = self.login()
        started = self.client.post(
            "/admin/timer/start",
            headers={"X-CSRF-Token": csrf_token},
        )

        self.assertEqual(started.status_code, 200)
        self.assertIsNotNone(started.get_json()["timer_started_at"])

        reset = self.client.post(
            "/admin/timer/reset",
            headers={"X-CSRF-Token": csrf_token},
        )
        self.assertEqual(reset.status_code, 200)
        self.assertIsNone(reset.get_json()["timer_started_at"])

    def test_timer_can_be_started_from_the_admin_form(self) -> None:
        csrf_token = self.login()
        response = self.client.post(
            "/admin/timer/start",
            data={"csrf_token": csrf_token},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIsNotNone(self.client.get("/api/display").get_json()["timer_started_at"])

    def test_admin_can_complete_a_started_room(self) -> None:
        csrf_token = self.login()
        self.client.post(
            "/admin/timer/start",
            headers={"X-CSRF-Token": csrf_token},
        )

        response = self.client.post(
            "/admin/complete",
            headers={"X-CSRF-Token": csrf_token},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.get_json()["room_completed_at"])

    def test_adding_time_increases_total_time_without_changing_time_taken(self) -> None:
        csrf_token = self.login()
        self.client.post(
            "/admin/timer/start",
            headers={"X-CSRF-Token": csrf_token},
        )

        response = self.client.post(
            "/admin/timer/adjust",
            json={"seconds": 120},
            headers={"X-CSRF-Token": csrf_token},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["extra_time_seconds"], 120)
        self.assertEqual(payload["penalty_time_seconds"], 0)

    def test_removing_time_increases_time_taken_without_changing_total_time(self) -> None:
        csrf_token = self.login()
        self.client.post(
            "/admin/timer/start",
            headers={"X-CSRF-Token": csrf_token},
        )

        response = self.client.post(
            "/admin/timer/adjust",
            json={"seconds": -90},
            headers={"X-CSRF-Token": csrf_token},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["extra_time_seconds"], 0)
        self.assertEqual(payload["penalty_time_seconds"], 90)

    def test_completed_room_result_records_group_and_time(self) -> None:
        csrf_token = self.login()
        self.client.post(
            "/admin/timer/start",
            headers={"X-CSRF-Token": csrf_token},
        )
        self.client.post(
            "/admin/complete",
            headers={"X-CSRF-Token": csrf_token},
        )

        response = self.client.post(
            "/admin/results",
            json={
                "group_name": "The Locksmiths",
                "group_size": "4",
                "hints_used": "2",
                "penalties": "1",
            },
            headers={"X-CSRF-Token": csrf_token},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["group_name"], "The Locksmiths")
        self.assertEqual(response.get_json()["group_size"], 4)
        self.assertEqual(response.get_json()["hints_used"], 2)
        self.assertEqual(response.get_json()["penalties"], 1)
        self.assertGreaterEqual(response.get_json()["time_taken_seconds"], 0)
        self.assertLessEqual(response.get_json()["time_remaining_seconds"], 3600)

    def test_completed_room_result_reflects_time_adjustments(self) -> None:
        csrf_token = self.login()
        self.client.post(
            "/admin/timer/start",
            headers={"X-CSRF-Token": csrf_token},
        )
        self.client.post(
            "/admin/timer/adjust",
            json={"seconds": 300},
            headers={"X-CSRF-Token": csrf_token},
        )
        self.client.post(
            "/admin/timer/adjust",
            json={"seconds": -60},
            headers={"X-CSRF-Token": csrf_token},
        )
        self.client.post(
            "/admin/complete",
            headers={"X-CSRF-Token": csrf_token},
        )

        response = self.client.post(
            "/admin/results",
            json={
                "group_name": "The Locksmiths",
                "group_size": "4",
                "hints_used": "0",
                "penalties": "0",
            },
            headers={"X-CSRF-Token": csrf_token},
        )

        payload = response.get_json()
        # time_taken should include the 60 second penalty
        self.assertGreaterEqual(payload["time_taken_seconds"], 60)
        # total time budget is 3600 + 300 extra seconds, so remaining should
        # reflect that budget minus time taken (well above the base 3600 - time_taken).
        expected_remaining = 3600 + 300 - payload["time_taken_seconds"]
        self.assertEqual(payload["time_remaining_seconds"], expected_remaining)

    def test_cannot_record_result_before_room_is_completed(self) -> None:
        csrf_token = self.login()
        response = self.client.post(
            "/admin/results",
            json={
                "group_name": "The Locksmiths",
                "group_size": "4",
                "hints_used": "0",
                "penalties": "0",
            },
            headers={"X-CSRF-Token": csrf_token},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json()["error"],
            "Complete the room before recording its result.",
        )

    def test_cannot_complete_room_before_timer_starts(self) -> None:
        csrf_token = self.login()
        response = self.client.post(
            "/admin/complete",
            headers={"X-CSRF-Token": csrf_token},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.get_json()["error"],
            "Start the timer before completing the room.",
        )

    def test_admin_can_send_a_two_minute_announcement(self) -> None:
        csrf_token = self.login()
        response = self.client.post(
            "/admin/announcement",
            json={"message": "Please return to the entrance."},
            headers={"X-CSRF-Token": csrf_token},
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["announcement"], "Please return to the entrance.")
        self.assertIsNotNone(data["announcement_expires_at"])
        self.assertEqual(data["hint"]["message"], "Please return to the entrance.")
        self.assertEqual(data["hint"]["timer_remaining_seconds"], 3600)

        admin = self.client.get("/admin")
        self.assertIn(b"Hints sent this session", admin.data)
        self.assertIn(b"Hint 1", admin.data)
        self.assertIn(b"Timer: 60:00", admin.data)
        self.assertIn(b"Please return to the entrance.", admin.data)

    def test_admin_can_cancel_an_active_announcement(self) -> None:
        csrf_token = self.login()
        self.client.post(
            "/admin/announcement",
            json={"message": "Please return to the entrance."},
            headers={"X-CSRF-Token": csrf_token},
        )

        admin = self.client.get("/admin")
        self.assertNotIn(b'id="current-announcement" aria-live="polite" hidden', admin.data)
        self.assertIn(b"Please return to the entrance.", admin.data)

        response = self.client.post(
            "/admin/announcement/cancel",
            headers={"X-CSRF-Token": csrf_token},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get_json()["announcement"])
        self.assertIsNone(response.get_json()["announcement_media_filename"])
        admin = self.client.get("/admin")
        self.assertIn(b'id="current-announcement" aria-live="polite" hidden', admin.data)

    def test_app_startup_clears_expired_announcement(self) -> None:
        store = self.app.extensions["display_store"]
        store.send_announcement("Expired hint")
        with closing(connect(self.database_path)) as connection:
            connection.execute(
                """
                UPDATE display_settings
                SET announcement_expires_at = ?
                WHERE id = 1
                """,
                ((datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),),
            )
            connection.commit()

        restarted_app = self.create_test_app()
        try:
            payload = restarted_app.test_client().get("/api/display").get_json()
        finally:
            restarted_app.extensions["gpio"].close()

        self.assertIsNone(payload["announcement"])
        self.assertIsNone(payload["announcement_expires_at"])

    def test_hint_library_can_create_send_and_delete_text_preset(self) -> None:
        csrf_token = self.login()
        create_response = self.client.post(
            "/admin/hints",
            json={"kind": "text", "title": "Look under the desk", "message": "Check the desk drawer."},
            headers={"X-CSRF-Token": csrf_token},
        )
        self.assertEqual(create_response.status_code, 200)
        preset = create_response.get_json()
        self.assertEqual(preset["title"], "Look under the desk")

        library_page = self.client.get("/admin/hints")
        self.assertIn(b"Look under the desk", library_page.data)

        self.client.post("/admin/timer/start", data={"csrf_token": csrf_token})
        send_response = self.client.post(
            f"/admin/hints/{preset['id']}/send",
            json={},
            headers={"X-CSRF-Token": csrf_token},
        )
        self.assertEqual(send_response.status_code, 200)
        sent = send_response.get_json()
        self.assertEqual(sent["announcement"], "Check the desk drawer.")
        self.assertEqual(sent["hint"]["message"], "Check the desk drawer.")

        delete_response = self.client.post(
            f"/admin/hints/{preset['id']}/delete",
            json={},
            headers={"X-CSRF-Token": csrf_token},
        )
        self.assertEqual(delete_response.status_code, 200)
        self.assertTrue(delete_response.get_json()["deleted"])

    def test_hint_library_can_create_and_send_image_preset(self) -> None:
        csrf_token = self.login()
        create_response = self.client.post(
            "/admin/hints",
            data={
                "csrf_token": csrf_token,
                "kind": "image",
                "title": "Padlock clue",
                "message": "Look closely at the numbers.",
                "media": (BytesIO(b"\x89PNG\r\n\x1a\nimage-data"), "clue.png"),
                "full_screen": "on",
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(create_response.status_code, 302)
        create_response.close()
        library_page = self.client.get("/admin/hints")
        self.assertIn(b"Padlock clue", library_page.data)
        self.assertIn(b"full screen", library_page.data)
        from pi_home_screen.display import DisplaySettingsStore

        store = DisplaySettingsStore(str(Path(self.temporary_directory.name) / "screen.db"))
        preset = store.get_hint_presets()[0]
        self.assertEqual(preset.kind, "image")
        self.assertRegex(preset.media_filename, r"^[0-9a-f]{32}\.png$")
        self.assertTrue(preset.full_screen)

        self.client.post("/admin/timer/start", data={"csrf_token": csrf_token})
        send_response = self.client.post(
            f"/admin/hints/{preset.id}/send",
            json={},
            headers={"X-CSRF-Token": csrf_token},
        )
        self.assertEqual(send_response.status_code, 200)
        sent = send_response.get_json()
        self.assertEqual(sent["announcement_media_type"], "image")
        self.assertEqual(sent["announcement_media_filename"], preset.media_filename)
        self.assertTrue(sent["announcement_media_full_screen"])
        self.assertEqual(sent["hint"]["media_type"], "image")

    def test_starting_or_resetting_timer_clears_session_hints(self) -> None:
        csrf_token = self.login()
        self.client.post(
            "/admin/announcement",
            json={"message": "Look under the table."},
            headers={"X-CSRF-Token": csrf_token},
        )

        self.client.post(
            "/admin/timer/start",
            headers={"X-CSRF-Token": csrf_token},
        )

        self.assertNotIn(
            b"Look under the table.",
            self.client.get("/admin").data,
        )

    def test_hint_form_sends_without_requiring_javascript(self) -> None:
        csrf_token = self.login()
        response = self.client.post(
            "/admin/announcement",
            data={
                "csrf_token": csrf_token,
                "message": "Use the map on the wall.",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(
            b"Use the map on the wall.",
            self.client.get("/admin").data,
        )

    def test_timer_and_announcement_actions_require_admin_session(self) -> None:
        self.assertEqual(self.client.post("/admin/timer/start").status_code, 401)
        self.assertEqual(self.client.post("/admin/announcement").status_code, 401)
        self.assertEqual(self.client.post("/admin/announcement/cancel").status_code, 401)
        self.assertEqual(self.client.post("/admin/gpio/pause").status_code, 401)
        self.assertEqual(
            self.client.post("/admin/gpio/actions/1/trigger").status_code,
            401,
        )

    def test_settings_require_admin_session_and_csrf_token(self) -> None:
        response = self.client.post("/api/admin/settings", json={})
        self.assertEqual(response.status_code, 401)

        self.login()
        response = self.client.post("/api/admin/settings", json={})
        self.assertEqual(response.status_code, 400)

    def test_invalid_display_settings_are_rejected(self) -> None:
        csrf_token = self.login()
        response = self.client.post(
            "/admin/settings",
            json={
                "title": "",
                "message": "Message",
                "background_colour": "blue",
                "accent_colour": "#ffeeaa",
            },
            headers={"X-CSRF-Token": csrf_token},
        )

        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
