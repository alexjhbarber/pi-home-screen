# Pi Home Screen

Fullscreen, browser-based display for a Raspberry Pi. Open `/` on the Pi's
connected display and use `/admin` from another device on the same network to
change the screen immediately.

## Run

Set a unique Flask signing key and the admin password, then start the app:

```bash
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export ADMIN_PASSWORD="choose-a-strong-password"
poetry run flask --app pi_home_screen.app:create_app run --host=0.0.0.0
```

Open `http://<pi-address>:5000/` in Chromium's kiosk mode on the Pi. Browse to
`http://<pi-address>:5000/admin` from an authorised device to log in and alter
the title, message, and colours. Changes are stored in SQLite and pushed to
the display through Server-Sent Events without refreshing the page.

For this built-in live-update broker, run one application worker. If the
application later needs multiple workers or multiple Pis, replace the broker
with a shared service such as Redis pub/sub.

## GPIO

The optional `GPIO_OUTPUTS` variable maps a friendly output name to a BCM GPIO
pin number. Each output gains On and Off controls in `/admin`:

```bash
export GPIO_OUTPUTS='{"door-light": 17, "buzzer": 27}'
```

GPIO Zero controls the pins on Raspberry Pi OS. On a development computer,
the app logs that physical GPIO is unavailable and continues without touching
hardware. GPIO uses 3.3V logic only: do not connect relays, motors, or other
high-current devices directly to a pin. Use an appropriate driver board,
separate power supply where required, and a common ground.

On Raspberry Pi OS, install the GPIO pin driver before installing/running the
Poetry project:

```bash
sudo apt install python3-lgpio
```

Use **Admin > GPIO** to link a BCM-numbered input pin to the **Complete room**
event. The page can pause all mapped GPIO events before a pin is pressed; a
paused or invalid trigger is recorded as ignored instead of completing the
room. The home screen displays the recent GPIO activity.

## Test

```bash
poetry run python -m unittest discover -s tests -v
```