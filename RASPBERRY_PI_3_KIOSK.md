# Raspberry Pi Zero W Lite Kiosk Setup

This guide documents deployment on Raspberry Pi OS Lite (64-bit), using a
minimal X11 session instead of a desktop environment. A **Raspberry Pi Zero 2
W or newer** is required for Chromium kiosk mode.


> [!NOTE]
> On a Pi Zero 2 W, the Flask application can still take 30-40 seconds to
> start after a cold boot. The X11 startup file deliberately makes Chromium
> wait for the web application rather than opening a failed page.

## Supported Raspberry Pi models

| Model | Recommendation | Notes |
|---|---|---|
| Pi Zero 2 W | Best small replacement | Same compact form factor as the Zero W, with a quad-core ARMv8 CPU that supports Chromium. |
| Pi 3B+ | Good budget option | Suitable for one Flask and Chromium display; use a reliable 2.5 A power supply. |
| Pi 4 Model B (2 GB or more) | Best overall choice | A fast, dependable choice for an always-on Chromium kiosk. |
| Pi 5 (2 GB or more) | Best performance | More performance than one display needs, with capacity for additional local services or displays. |
| Pi 400 | Works well | Pi 4-class hardware in a keyboard form factor; normally unsuitable for a concealed kiosk. |

Avoid the original Pi Zero, Pi Zero W, Pi 1, and other older single-core
models for Chromium kiosk mode. Current Chromium builds require CPU
capabilities that those boards do not provide.

## 1. Flash and boot Raspberry Pi OS Lite

Use Raspberry Pi Imager to write **Raspberry Pi OS Lite (32-bit)** to a
microSD card. Before writing, configure a hostname, Wi-Fi country and
credentials, an administrator account, and SSH.

Connect to the Pi:

```bash
ssh <admin-user>@<pi-hostname>.local
```

Use the Pi's IP address if the `.local` hostname does not resolve.

## 2. Install operating-system packages

Run as the administrator account:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y \
  build-essential \
  curl \
  git \
  pipx \
  python3 \
  python3-dev \
  python3-venv \
  python3-lgpio \
  alsa-utils \
  libraspberrypi-bin \
  swig \
  liblgpio-dev \
  chromium \
  xinit \
  xserver-xorg \
  x11-xserver-utils \
  unclutter
```

`build-essential`, `swig`, and `liblgpio-dev` are required because the
`lgpio` Python package builds a Raspberry Pi GPIO extension during install.

## 3. Create the kiosk account

```bash
sudo adduser kiosk
sudo usermod -aG gpio,video,audio,input,plugdev kiosk
```

Do not add `kiosk` to `sudo`.

## 4. Clone the application

```bash
sudo -u kiosk -H git clone \
  https://github.com/alexjhbarber/pi-home-screen.git \
  /home/kiosk/pi-home-screen
```

## 5. Install Poetry and application dependencies

Install Poetry for the account that runs the service:

```bash
sudo -u kiosk -H bash -c '
  cd /home/kiosk
  pipx install poetry
  /home/kiosk/.local/bin/poetry --version
'
```

Install the project's locked dependencies:

```bash
sudo -u kiosk -H bash -c '
  cd /home/kiosk/pi-home-screen
  /home/kiosk/.local/bin/poetry env use python3
  /home/kiosk/.local/bin/poetry install --only main
'
```

The project supports Python 3.11 or newer. Check the installed interpreter:

```bash
python3 --version
```

## 6. Set application secrets

Create a protected environment file:

```bash
sudo install -d -m 0750 -o kiosk -g kiosk /etc/pi-home-screen
SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

sudo tee /etc/pi-home-screen/environment >/dev/null <<EOF
SECRET_KEY=${SECRET_KEY}
ADMIN_PASSWORD=replace-this-with-a-long-unique-password

# Optional output pins, using BCM numbering:
# GPIO_OUTPUTS={"door-light":17,"buzzer":27}

# Optional GPIO inputs, using BCM numbering:
# GPIO_INPUTS={"complete-room":17}
# GPIO_INPUTS={"complete-room":17,"display-toggle":27}
EOF

sudo chown kiosk:kiosk /etc/pi-home-screen/environment
sudo chmod 0600 /etc/pi-home-screen/environment
```

Replace `ADMIN_PASSWORD` before starting the service:

```bash
sudo nano /etc/pi-home-screen/environment
```

## 7. Create and start the web application service

```bash
sudo tee /etc/systemd/system/pi-home-screen.service >/dev/null <<'EOF'
[Unit]
Description=Pi Home Screen
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=kiosk
Group=kiosk
WorkingDirectory=/home/kiosk/pi-home-screen
EnvironmentFile=/etc/pi-home-screen/environment
Environment=HOME=/home/kiosk
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/kiosk/.local/bin/poetry run flask --app pi_home_screen.app:create_app run --host=0.0.0.0 --port=5000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now pi-home-screen.service
```

Wait at least 40 seconds on an original Pi Zero W, then test:

```bash
curl -I --max-time 10 http://127.0.0.1:5000/
```

The expected response starts with `HTTP/1.1 200 OK`. The display and remote
administration pages are available at:

```text
http://<pi-ip-address>:5000/
http://<pi-ip-address>:5000/admin
```

## 8. Configure Chromium kiosk mode

Create the X11 session for the kiosk account:

```bash
sudo tee /home/kiosk/.xinitrc >/dev/null <<'EOF'
#!/bin/sh

xset -dpms
xset s off
xset s noblank

# Select the connected monitor's preferred resolution after X11 is available.
xrandr --output HDMI-1 --auto

unclutter --timeout 0.5 --start-hidden &

until curl --silent --fail http://127.0.0.1:5000/ >/dev/null; do
  sleep 2
done

exec /usr/bin/chromium \
  --no-first-run \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --autoplay-policy=no-user-gesture-required \
  --autoplay-policy=no-user-gesture-required \
  --alsa-output-device=hdmi:CARD=vc4hdmi,DEV=0 \
  --start-maximized \
  --window-position=0,0 \
  --window-size=1920,1080 \
  --kiosk \
  --incognito \
  http://127.0.0.1:5000/
EOF

sudo chown kiosk:kiosk /home/kiosk/.xinitrc
sudo chmod 0755 /home/kiosk/.xinitrc
```

Make the kiosk user start X11 when it automatically logs in to the first
console:

```bash
sudo tee /home/kiosk/.bash_profile >/dev/null <<'EOF'
[ -f "$HOME/.profile" ] && . "$HOME/.profile"

if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
  while true; do
    startx -- :0 -keeptty -nolisten tcp
    sleep 2
  done
fi
EOF

sudo chown kiosk:kiosk /home/kiosk/.bash_profile
sudo chmod 0644 /home/kiosk/.bash_profile
```

## 9. Enable automatic kiosk login

```bash
sudo mkdir -p /etc/systemd/system/getty@tty1.service.d

sudo tee /etc/systemd/system/getty@tty1.service.d/autologin.conf >/dev/null <<'EOF'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin kiosk --noclear %I $TERM
EOF

sudo systemctl set-default multi-user.target
sudo systemctl daemon-reload
sudo reboot
```

After reboot, systemd starts the app, logs in as `kiosk`, starts X11, and
opens the home screen in Chromium.

## 10. Configure HDMI audio and monitor power
Reboot after saving the file. Verify that ALSA can see an HDMI device:

```bash
aplay -l
aplay -L
speaker-test -c 2 -t wav
```
```bash
speaker-test -D hdmi:CARD=vc4hdmi0,DEV=0 -c 2 -t wav
```
```bash
sudo -u kiosk tee /home/kiosk/.asoundrc >/dev/null <<'EOF'
pcm.!default {
    type plug
    slave.pcm "hdmi:CARD=vc4hdmi0,DEV=0"
}

ctl.!default {
    type hw
    card vc4hdmi0
}
EOF
```

```bash
sudo nano /boot/firmware/config.txt
```

On older Raspberry Pi OS releases, edit `/boot/config.txt` instead. Add these
lines if they are not already present:

```ini
hdmi_force_hotplug=1
hdmi_drive=2
```



On systems using the Raspberry Pi `vc4` HDMI driver, the HDMI audio device is
typically exposed as `vc4hdmi0`, device `0`. Test it directly with:

```bash
speaker-test -D hdmi:CARD=vc4hdmi0,DEV=0 -c 2 -t wav
```

If that device name is not listed by `aplay -L`, use the exact `CARD=` and
`DEV=` values shown by the command output instead.

The home screen uses Chromium audio playback for notification, completion,
and failure sounds. The `--autoplay-policy=no-user-gesture-required` option in
the X11 startup command allows sounds received through live updates to play
without a separate click on the kiosk screen. Upload and test the sound files
from **Admin > Sounds**.

The admin page's monitor button uses `vcgencmd display_power` and displays
**Monitor on** or **Monitor off**. Confirm the command is installed and works
as the kiosk account:

```bash
command -v vcgencmd
sudo -u kiosk vcgencmd display_power
```

If the command is missing:

```bash
sudo apt update
sudo apt install -y libraspberrypi-bin
sudo systemctl restart pi-home-screen.service
```

To connect a physical monitor toggle button, set this in
`/etc/pi-home-screen/environment`:

```ini
GPIO_INPUTS={"display-toggle":17}
```

Use an unused BCM pin and connect the button according to the GPIO Zero
button wiring. Apply the environment change with:

```bash
sudo systemctl daemon-reload
sudo systemctl restart pi-home-screen.service
```

The web control and GPIO control both toggle the same HDMI output. The
monitor's own standby or backlight behavior can vary by model; the control
switches the Raspberry Pi HDMI signal using `vcgencmd`.

## Troubleshooting encountered during setup

### `poetry: command not found`

Poetry is not supplied by Raspberry Pi OS Lite by default. Install it with
`pipx` as the kiosk user, as shown in step 5. The service must use its actual
path:

```text
/home/kiosk/.local/bin/poetry
```

Do not use `/usr/bin/poetry` unless Poetry was installed system-wide there.

### `Permission denied: '/home/<admin-user>'`

`sudo -u kiosk` retains the current directory. If the current directory is
the administrator's private home directory, switch to the kiosk home before
running Poetry:

```bash
sudo -u kiosk -H bash -c '
  cd /home/kiosk
  /home/kiosk/.local/bin/poetry --version
'
```

For interactive work, use `sudo -iu kiosk`.

### `Current Python version (...) is not allowed by the project (>=3.14)`

Use the repository version of this guide, whose `pyproject.toml` supports
Python 3.11 through Python 3.x. Pull the updated project and run:

```bash
sudo -u kiosk -H bash -c '
  cd /home/kiosk/pi-home-screen
  /home/kiosk/.local/bin/poetry env use python3
  /home/kiosk/.local/bin/poetry install --only main
'
```

### `status=203/EXEC` or `Unable to locate executable '/usr/bin/poetry'`

The service file has the wrong Poetry path. Recreate the service from step 7,
then reload and restart it:

```bash
sudo systemctl daemon-reload
sudo systemctl restart pi-home-screen.service
```

### `startx: command not found`

The minimal graphical session package was not installed. Install X11 startup
support, verify the command exists, then reboot so the automatic kiosk login
starts it on the Pi's attached display:

```bash
sudo apt update
sudo apt install -y xinit xserver-xorg x11-xserver-utils
command -v startx
sudo reboot
```

### HDMI audio is missing or sounds are blocked

Check that the HDMI output is detected and that the kiosk user belongs to the
audio group:

```bash
aplay -l
groups kiosk
```

If no HDMI device is listed, confirm `hdmi_force_hotplug=1` and
`hdmi_drive=2` are present in `/boot/firmware/config.txt` (or
`/boot/config.txt` on older systems), then reboot. If the device is listed but
the kiosk is silent, confirm `--autoplay-policy=no-user-gesture-required` is in
`/home/kiosk/.xinitrc` and restart the X11 session.

### Monitor power button is disabled

The button is disabled when `vcgencmd` is unavailable. Check it with:

```bash
command -v vcgencmd
sudo -u kiosk vcgencmd display_power
```

Install `libraspberrypi-bin` if necessary, then restart
`pi-home-screen.service`.

The expected command path is `/usr/bin/startx`. Do not run `startx` through
SSH; it must start from the kiosk account's automatic login on the Pi's local
console.

### `xinit: giving up` with `Cannot open virtual console 7 (Permission denied)`

The kiosk user cannot open a different virtual console. It must keep the
automatically logged-in console (`tty1`) instead. Replace the X startup line
in `/home/kiosk/.bash_profile`:

```bash
sudo sed -i \
  's/startx -- :0 vt7 -nolisten tcp/startx -- :0 -keeptty -nolisten tcp/' \
  /home/kiosk/.bash_profile

sudo reboot
```

### Chromium fills only part of the display

Chromium's `--kiosk` flag fills the X11 display. If it appears in only half
of the monitor, X11 started at the wrong HDMI resolution rather than the web
application being constrained. At the Pi's local console or over SSH, inspect
the active X11 output and modes:

```bash
sudo -u kiosk DISPLAY=:0 XAUTHORITY=/home/kiosk/.Xauthority xrandr --query
```

Find the line ending in `connected` (normally `HDMI-1`) and a mode marked
with `+`, which is the monitor's preferred resolution. Set that mode now,
substituting the output and resolution shown by the preceding command:

```bash
sudo -u kiosk DISPLAY=:0 XAUTHORITY=/home/kiosk/.Xauthority \
  xrandr --output HDMI-1 --mode 1920x1080
```

The `xrandr --output HDMI-1 --auto` line in step 8 makes the selected
monitor mode persistent each time the kiosk starts. If the connected output
has a different name, replace `HDMI-1` in `/home/kiosk/.xinitrc` with the
name reported by `xrandr`, then reboot:

```bash
sudo nano /home/kiosk/.xinitrc
sudo reboot
```

If `xrandr` offers no correct mode, configure the HDMI mode before X11
starts. Raspberry Pi OS Bookworm stores this file at
`/boot/firmware/config.txt`; older Raspberry Pi OS releases use
`/boot/config.txt`. Edit the file that exists and add these lines for a
1080p monitor:

```text
hdmi_group=2
hdmi_mode=82
disable_overscan=1
```

`hdmi_mode=82` is 1920x1080 at 60 Hz. Use a mode supported by the monitor;
for a 720p monitor use `hdmi_mode=85` instead. Reboot after saving:

```bash
sudo reboot
```

### Chromium displays a NEON SIMD hardware warning

The original Raspberry Pi Zero W's ARMv6 CPU does not implement NEON SIMD.
Current Raspberry Pi OS Chromium requires NEON and exits after showing a
message similar to:

```text
The hardware on this system lacks support for NEON SIMD extensions.
```

This cannot be fixed by changing Chromium flags, X11 configuration, or the
Flask service. Use a Raspberry Pi Zero 2 W or newer for Chromium kiosk mode.
Older browsers may render a limited static page, but they are not a supported
replacement for this application's JavaScript and Server-Sent Events display.

### `No module named 'lgpio'`, `swig: No such file or directory`, or `cannot find -llgpio`

Install all packages from step 2, particularly `swig` and `liblgpio-dev`,
then reinstall the locked dependencies:

```bash
sudo -u kiosk -H bash -c '
  cd /home/kiosk/pi-home-screen
  /home/kiosk/.local/bin/poetry install --only main
'
```

### `lgpio.error: 'GPIO busy'`

A saved GPIO input mapping is attempting to use a pin claimed by another
process or system overlay. For example, BCM GPIO 18 (physical pin 12) is
often used by audio/PWM configuration.

To restore the display without deleting display settings, remove only the
blocked input mapping, then restart:

```bash
sudo systemctl stop pi-home-screen.service

sudo -u kiosk -H python3 -c '
import sqlite3
database = "/home/kiosk/pi-home-screen/src/instance/home_screen.db"
connection = sqlite3.connect(database)
connection.execute("DELETE FROM gpio_mappings WHERE pin = ?", (18,))
connection.commit()
print("Removed BCM GPIO 18 mapping.")
'

sudo systemctl start pi-home-screen.service
```

Rewire the input to an unused BCM pin, such as GPIO 17 (physical pin 11), and
add it again from **Admin > GPIO**. Avoid GPIO 2/3, GPIO 14/15, and GPIO 18
while resolving pin conflicts.

> [!NOTE]
> Flask stores its database at
> `/home/kiosk/pi-home-screen/src/instance/home_screen.db`, not at
> `/home/kiosk/pi-home-screen/instance/home_screen.db`.

## Maintenance

```bash
# Follow application logs.
sudo journalctl -u pi-home-screen.service -f

# Restart after configuration or application changes.
sudo systemctl restart pi-home-screen.service

# Update from Git, then restart.
sudo -u kiosk -H bash -c '
  cd /home/kiosk/pi-home-screen
  git pull --ff-only
  /home/kiosk/.local/bin/poetry install --only main
'
sudo systemctl restart pi-home-screen.service
```
