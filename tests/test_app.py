import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from pi_home_screen import create_app


class HomeScreenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "ADMIN_PASSWORD": "test-password",
                "DATABASE": str(Path(self.temporary_directory.name) / "screen.db"),
                "GPIO_OUTPUTS": {},
                "GPIO_INPUTS": {},
            }
        )
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.app.extensions["gpio"].close()
        self.temporary_directory.cleanup()

    def login(self) -> str:
        response = self.client.post(
            "/admin/login",
            data={"password": "test-password"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def test_home_renders_persisted_default_settings(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Welcome", response.data)

    def test_admin_includes_on_demand_live_display_preview(self) -> None:
        self.login()
        response = self.client.get("/admin")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="preview-dialog"', response.data)
        self.assertIn(b"Open live preview", response.data)

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
        uploaded_image.close()

    def test_statistics_can_be_added_and_deleted(self) -> None:
        csrf_token = self.login()
        response = self.client.post(
            "/admin/stats",
            data={"csrf_token": csrf_token, "label": "Players", "value": "4"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        stats_page = self.client.get("/admin/stats")
        self.assertIn(b"Players", stats_page.data)
        self.assertIn(b">4<", stats_page.data)
        statistic = self.app.extensions["display_store"].get_statistics()[0]

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

    def test_configured_gpio_input_records_activity_when_pressed(self) -> None:
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
                    "GPIO_INPUTS": {"complete-room": 17},
                }
            )

        app.extensions["display_store"].start_timer()
        self.assertEqual(FakeGpioController.instance.inputs, [("complete-room", 17)])
        FakeGpioController.instance.callback(17, "complete-room")

        activity = app.test_client().get("/api/gpio/activity").get_json()["activity"]
        self.assertEqual(activity[0]["pin"], 17)
        self.assertEqual(activity[0]["event"], "complete-room")
        self.assertTrue(activity[0]["accepted"])
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
            b'event: display\ndata: {"title":"Welcome","message":"Your message appears here.","background_colour":"#102a43","accent_colour":"#f6c453","timer_started_at":null,"room_completed_at":null,"announcement":null,"announcement_expires_at":null,"background_image":null,"auto_hint_remaining_minutes":null,"auto_hint_message":null}\n\n',
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
