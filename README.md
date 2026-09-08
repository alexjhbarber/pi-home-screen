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


Install OS packages (run as pi or root)
sudo apt update
sudo apt install -y python3 python3-venv python3-pip chromium-browser xserver-xorg x11-xserver-utils unclutter xdotool

The user account creation command you showed will create a new kiosk user but it doesn’t finish setup (password, groups, home files, etc.). Run these next steps to finish preparing the kiosk account for the Pi kiosk:

1. Set a password for the kiosk user
sudo passwd kiosk
2. Add kiosk to useful groups (GPIO, video, audio, input, plugdev)
sudo usermod -aG gpio,video,audio,input,plugdev kiosk

(If you plan to run the web service as that user, also add any service-specific groups; avoid adding to sudo unless you need it.)

3. Give the kiosk user ownership of the app directory (adjust path if you put repo elsewhere)
sudo mkdir -p /home/kiosk/pi-home-screen
sudo chown -R kiosk:kiosk /home/kiosk/pi-home-screen
4. Create the LXDE autostart so Chromium will open in kiosk mode (run as root, then fix ownership)
sudo -u kiosk mkdir -p /home/kiosk/.config/lxsession/LXDE-pi
sudo tee /home/kiosk/.config/lxsession/LXDE-pi/autostart > /dev/null <<'EOF'
@xset -dpms
@xset s off
@xset s noblank
@unclutter --timeout 0.5 --start-hidden
@bash -c "sleep 3; /usr/bin/chromium-browser --noerrdialogs --disable-infobars --kiosk --incognito http://127.0.0.1:5001/"
EOF
sudo chown -R kiosk:kiosk /home/kiosk/.config
5. If you want the kiosk user to auto-login in lightdm (Desktop Raspbian), edit or create:
sudo mkdir -p /etc/lightdm/lightdm.conf.d
sudo tee /etc/lightdm/lightdm.conf.d/50-kiosk.conf > /dev/null <<'EOF'
[Seat:*]
autologin-user=kiosk
autologin-user-timeout=0
EOF
6. Test the desktop login and kiosk launch

• Reboot the Pi: sudo reboot
• The kiosk user should auto-login and Chromium should open the local site.

7. (Optional) If you’ll run the Flask app under the kiosk user with a virtualenv, set that up as the kiosk user:
sudo -u kiosk bash -c '
cd /home/kiosk/pi-home-screen
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
'
8. Troubleshooting tips

• If Chromium won’t start, login manually as kiosk (tty or SSH) and run the autostart command to capture errors.
• If GPIO access fails, ensure the kiosk user is in the gpio group and the lgpio library is installed (sudo apt install python3-lgpio).
• If the web app isn’t running, enable the systemd service you created earlier and check logs: sudo journalctl -u pi-home-screen -b

If you want I can:

• Create those autostart and lightdm files for you in the project directory so you can copy them to the Pi, or
• Write a step-by-step script that performs all of the above on the Pi (I’ll include safety checks). Which would you prefer?
