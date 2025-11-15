# 🎵 Spotify + Last.fm Auto-Skipper

A small Windows tray app that automatically skips songs on Spotify that you've already listened to recently — based on your Last.fm scrobble history.

---

## 💡 What it does

* Checks which song is currently playing on your Spotify account
* Asks **Last.fm** when that same song was last scrobbled
* If it was played within a configurable number of days (default: 60), it automatically **skips it** on Spotify
* Runs quietly in the background with a **system tray icon**
* Logs all activity to daily log files

---

## ⚙️ Configuration

Create a file named `config.ini` in the same folder as the `.exe` (or `.py`) file, with the following content:

```ini
[LastFM]
username = YOUR_LASTFM_USERNAME
api_key = YOUR_LASTFM_API_KEY

[Spotify]
client_id = YOUR_SPOTIFY_CLIENT_ID
client_secret = YOUR_SPOTIFY_CLIENT_SECRET
refresh_token = YOUR_SPOTIFY_REFRESH_TOKEN

[Settings]
skip_window_days = 60
poll_interval_seconds = 120
```

You can use `config.ini.template` by removing `.template` from the file name to leave it as just `config.ini`.

The template file holds advice how to gather the required data.

### Notes

* `skip_window_days` → how many days back to check your scrobbles
* `poll_interval_seconds` → how often to check what’s currently playing
* The app reads this config **only at startup**, so restart the app after changes.

---

## 🚀 Running the app

### Option 1: Run as Python script

```
python spotify_skip_recently_played_song.py
```

### Option 2: Build as EXE

You can compile it into a self-contained Windows `.exe` using [PyInstaller](https://pyinstaller.org/):

```
pyinstaller --noconsole --onefile spotify_skip_recently_played_song.py
```

Then place your `config.ini` next to the generated `.exe`.

---

## 🪟 System tray controls

When the app is running:

* 🟢 Green Spotify-like icon appears in your tray
* Right-click →

  * **⏯️ Pause Skipping** → pauses ALL skipping (toggle to resume)
  * **🎵 Skip This Song Later** → pauses skipping for the current song only (automatically resumes when next song plays)
  * **📁 Open Logs** → opens the log folder
  * **❌ Exit** → stops the app

---

## 🗾 Logs

Logs are stored in a `logs` subfolder next to the `.exe`, for example:

```
C:\Users\<yourname>\Tools\Spotify skip recently scrobbled song\logs\2025-10-24.txt
```

Each line includes a timestamp for easy tracking.

---

## 🚱 Preventing multiple instances

The app uses a Windows mutex (`SpotifyAutoSkipperMutex`) to ensure that only one instance runs at a time.

If you try to start it again, it will show a small info popup and immediately exit.

---

## 🧠 Tech details

* **Spotify API** → used for current track detection + skip command
* **Last.fm API** → used for fetching last scrobble time
* **Token refresh** → handled automatically using your permanent `refresh_token`
* **Built with** → `requests`, `pystray`, `Pillow`, `ctypes`, `configparser`

---

## 👨‍💻 Credits

Created by [**Vatroslav Mileusnić**](https://www.linkedin.com/in/vatroslavmileusnic)

Code + comments co-written with ChatGPT 5