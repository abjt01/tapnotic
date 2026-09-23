import os
import re
import json
import time
import secrets
import webbrowser
import threading
import urllib.parse
import subprocess
import platform
import socket
from pathlib import Path

import qrcode
import requests
from flask import Flask, request, jsonify
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

# ============================================================
# RFID -> Spotify Desktop Controller
# - ESP32 sends POST /rfid to this laptop
# - Laptop controls the native Spotify desktop app
# - The laptop's Spotify device ID is reused; it is looked up again
#   only when it stops working
# - The new track starts directly on the laptop
# - Same track scanned again: no Spotify playback command
# - Browser is used only for Spotify OAuth authorization
# ============================================================

BASE = Path(__file__).resolve().parent
MAP = BASE / "mappings.json"
TOKEN = BASE / "spotify_token.json"
ENV = BASE / ".env"

HOST = "0.0.0.0"
PORT = 5000
CALLBACK = "http://127.0.0.1:5000/callback"

AUTH = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"

SCOPE = (
    "user-read-playback-state "
    "user-modify-playback-state "
    "user-read-currently-playing"
)

# How long we wait for Spotify desktop to appear in the API device list.
DEVICE_WAIT_SECONDS = 10.0
DEVICE_POLL_SECONDS = 0.35

# Number of complete playback attempts for a different RFID track.
PLAY_ATTEMPTS = 3

# How long the "scan to pick your song" QR stays on the laptop screen.
QR_SECONDS = 120


def load_env():
    if not ENV.exists():
        return
    # utf-8-sig: Notepad on Windows may save a BOM at the start.
    for line in ENV.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(
            key.strip(),
            value.strip().strip('"').strip("'")
        )


load_env()

CID = os.getenv("SPOTIFY_CLIENT_ID", "")
SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
REDIRECT = os.getenv("SPOTIFY_REDIRECT_URI", CALLBACK)

# Optional. If set, the app will prefer this exact Spotify desktop
# device name. Leave blank to auto-detect the computer device.
LAPTOP_DEVICE_NAME = os.getenv("SPOTIFY_DEVICE_NAME", "").strip()


# ============================================================
# DEFAULT RFID MAPPINGS
# Existing mappings.json is NEVER overwritten on startup.
# ============================================================

DEFAULT = {
    "DA 16 D7 30": {
        "name": "0001",
        "spotify": "https://open.spotify.com/track/0oUBuOO4g9P4lREqfqR5nq",
    },
    "0A 82 88 30": {
        "name": "0002",
        "spotify": "https://open.spotify.com/track/6Frhkb7giXWjeJAX2dJT88",
    },
    "FA CD E1 30": {
        "name": "0003",
        "spotify": "https://open.spotify.com/track/5kqIPrATaCc2LqxVWzQGbk",
    },
    "8A BE 7D 30": {
        "name": "0004",
        "spotify": "https://open.spotify.com/track/3hRV0jL3vUpRrcy398teAU",
    },
    "9A ED EA 30": {
        "name": "0005",
        "spotify": "https://open.spotify.com/track/2QjOHCTQ1Jl3zawyYOpxh6",
    },
    "0A 4A E6 30": {
        "name": "0006",
        "spotify": "https://open.spotify.com/track/3qhlB30KknSejmIvZZLjOD",
    },
    "0A 87 EF 30": {
        "name": "0007",
        "spotify": "https://open.spotify.com/track/5SftJq4uVpajyYC1Gs0RFF",
    },
    "EA 60 8B 30": {
        "name": "0008",
        "spotify": "https://open.spotify.com/track/0rlLBWFFTQiOWi963SH9bb",
    },
    "EA C6 E1 30": {
        "name": "0009",
        "spotify": "https://open.spotify.com/track/5ivRSlOhVIXN2QMzqgsX0s",
    },
    "6A 1F 73 30": {
        "name": "0010",
        "spotify": "https://open.spotify.com/track/4iFPsNzNV7V9KJgcOX7TEO",
    },
    "2A 1E 09 31": {
        "name": "0011",
        "spotify": "https://open.spotify.com/track/0s76ExpXyMGVBlKLUr683e",
    },
    "B3 66 AF 5B": {
        "name": "0012 / di",
        "spotify": "https://open.spotify.com/track/7eQl3Yqv35ioqUfveKHitE",
    },
    "B7 93 27 1F": {
        "name": "0013 / me",
        "spotify": "https://open.spotify.com/track/3USxtqRwSYz57Ewm6wWRMp",
    },
    "5F 4D 90 2F": {
        "name": "0014 / ujwal",
        "spotify": "",
    },
    "9F 8A 2E 2F": {
        "name": "0015 / soofiya",
        "spotify": "",
    },
    "A4 8E 28 1F": {
        "name": "0016 / adi",
        "spotify": "https://open.spotify.com/track/4k6Uh1HXdhtusDW5y8Gbvy",
    },
    "CD DA 2D AB": {
        "name": "0017 / lucky",
        "spotify": "",
    },
    "0F 74 B3 2E": {
        "name": "0018 / gayan",
        "spotify": "",
    },
    "62 BE 27 1F": {
        "name": "0019 / ayush",
        "spotify": "",
    },
    "17 DC 30 5F": {
        "name": "0020 / tanman",
        "spotify": "https://open.spotify.com/track/3mTpegrOwRn0oJjv4TSbEE",
    },
    "7D B1 7A 85": {
        "name": "0021 / taw",
        "spotify": "",
    },
    "7F 5C 17 2E": {
        "name": "0022 / shiv",
        "spotify": "https://open.spotify.com/track/1lRmQ9D6oNYiuCXdGlKCs0",
    },
}

def write_json(path, data):
    """
    Write to a temp file first, then swap it in, so a crash mid-save
    can never leave a half-written file behind.
    """

    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(tmp, path)


# Shown in the activity log once the window is up.
startup_warning = None

if MAP.exists():
    try:
        mappings = json.loads(MAP.read_text(encoding="utf-8-sig"))
    except Exception:
        # Keep the broken file so the cards in it are not lost when
        # the defaults are saved over it.
        broken = MAP.with_name(
            "mappings.broken-" + time.strftime("%Y%m%d-%H%M%S") + ".json"
        )
        os.replace(MAP, broken)
        mappings = dict(DEFAULT)
        write_json(MAP, mappings)
        startup_warning = (
            "mappings.json could not be read. It was moved to "
            + broken.name
            + " and the default cards were loaded."
        )
else:
    mappings = dict(DEFAULT)
    write_json(MAP, mappings)


# ============================================================
# CARD LINKS
# Every card gets a private key. Its holder opens
# http://<LAPTOP-IP>:5000/card/<key> to pick their own song.
# ============================================================

# Guards mappings and mappings.json. Cards are changed from the GUI and
# from phones hitting the Flask server at the same time.
map_lock = threading.RLock()


def new_key():
    return secrets.token_urlsafe(9)


def ensure_keys():
    changed = False

    for value in mappings.values():
        if not value.get("key"):
            value["key"] = new_key()
            changed = True

    if changed:
        write_json(MAP, mappings)


ensure_keys()


def card_by_key(key):
    for uid, value in mappings.items():
        if value.get("key") == key:
            return uid, value

    return None, None


def next_number():
    """Next free card number, e.g. '0024'."""

    numbers = [
        int(n)
        for n, _ in (split_name(v.get("name", "")) for v in mappings.values())
        if n
    ]
    return str(max(numbers, default=0) + 1).zfill(4)


def register_card(uid):
    """Add a card the reader has never seen, with no song yet."""

    with map_lock:
        mappings[uid] = {
            "name": next_number(),
            "spotify": "",
            "key": new_key(),
        }
        save()

    log(f"New card {uid} registered as {mappings[uid]['name']}")
    ui(refresh_tree)
    return mappings[uid]


def lan_ip():
    """The laptop's address on the Wi-Fi, as phones will see it."""

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No packet is sent; this only picks the outgoing interface.
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def card_link(uid):
    return f"http://{lan_ip()}:{PORT}/card/{mappings[uid]['key']}"


# ============================================================
# RUNTIME STATE
# ============================================================

access = None
refresh = None
expires = 0
state = None
control = True

# Last known laptop device. Cleared as soon as playback on it fails.
cached_device = None
play_lock = threading.Lock()

# Every scan takes a number; only the newest one is allowed to play.
scan_lock = threading.Lock()
latest_scan = 0


if TOKEN.exists():
    try:
        token_data = json.loads(TOKEN.read_text(encoding="utf-8-sig"))
        refresh = token_data.get("refresh")
        expires = float(token_data.get("expires", 0))
    except Exception:
        pass


# ============================================================
# LOGGING
# ============================================================

root = None
tree = None
logbox = None
toggle = None


def log(message):
    print(time.strftime("%H:%M:%S"), message, flush=True)

    if root and logbox:
        root.after(
            0,
            lambda: (
                logbox.insert(
                    "end",
                    time.strftime("%H:%M:%S") + "  " + message + "\n",
                ),
                logbox.see("end"),
            ),
        )


def ui(fn):
    """Run fn on the GUI thread (safe to call from Flask threads)."""
    if root:
        root.after(0, fn)


# ============================================================
# TOKEN / SPOTIFY API
# ============================================================

def save_token():
    if refresh:
        write_json(
            TOKEN,
            {"refresh": refresh, "expires": expires},
        )


def refresh_access():
    global access, refresh, expires

    if not refresh or not CID or not SECRET:
        return False

    try:
        r = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh,
            },
            auth=(CID, SECRET),
            timeout=10,
        )
    except requests.RequestException:
        return False

    if r.status_code != 200:
        return False

    data = r.json()
    access = data["access_token"]
    refresh = data.get("refresh_token", refresh)
    expires = time.time() + data.get("expires_in", 3600) - 60
    save_token()
    return True


def api(method, path, **kwargs):
    global access

    if not access or time.time() >= expires:
        if not refresh_access():
            raise RuntimeError(
                "Spotify is not authorized. Click 'Authorize Spotify'."
            )

    headers = kwargs.pop("headers", {})
    headers["Authorization"] = "Bearer " + access

    try:
        r = requests.request(
            method,
            API + path,
            headers=headers,
            timeout=10,
            **kwargs,
        )
    except requests.RequestException as exc:
        raise RuntimeError("Spotify network error: " + str(exc))

    # Access token expired unexpectedly.
    if r.status_code == 401 and refresh_access():
        headers["Authorization"] = "Bearer " + access
        r = requests.request(
            method,
            API + path,
            headers=headers,
            timeout=10,
            **kwargs,
        )

    return r


# ============================================================
# SPOTIFY AUTH
# ============================================================

def authorize():
    global state

    if not CID or not SECRET:
        raise RuntimeError(
            "SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET are missing from .env"
        )

    state = secrets.token_urlsafe(24)

    query = urllib.parse.urlencode(
        {
            "client_id": CID,
            "response_type": "code",
            "redirect_uri": REDIRECT,
            "scope": SCOPE,
            "state": state,
        }
    )

    webbrowser.open(AUTH + "?" + query)


def exchange(code):
    global access, refresh, expires

    r = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
        },
        auth=(CID, SECRET),
        timeout=10,
    )

    if r.status_code != 200:
        raise RuntimeError(
            f"Spotify token exchange failed: {r.status_code} {r.text}"
        )

    data = r.json()
    access = data["access_token"]
    refresh = data.get("refresh_token")
    expires = time.time() + data.get("expires_in", 3600) - 60
    save_token()


# ============================================================
# SPOTIFY DEVICE DISCOVERY
# ============================================================

def devices():
    r = api("GET", "/me/player/devices")

    if r.status_code != 200:
        raise RuntimeError(
            f"Device list failed: {r.status_code} {r.text}"
        )

    return r.json().get("devices", [])


def open_spotify():
    """Open the native Spotify Windows app."""
    try:
        if platform.system() == "Windows":
            os.startfile("spotify:")
        else:
            subprocess.Popen(["spotify"])
    except Exception:
        pass


def choose_laptop_device(device_list):
    """
    Select the Windows/macOS Spotify desktop device.

    Priority:
      1. Exact SPOTIFY_DEVICE_NAME match, if configured.
      2. Active Computer.
      3. Any Computer.
      4. Active non-restricted device as a last resort.
    """

    usable = [
        d for d in device_list
        if not d.get("is_restricted")
    ]

    if LAPTOP_DEVICE_NAME:
        exact = next(
            (
                d for d in usable
                if d.get("name", "").strip().lower()
                == LAPTOP_DEVICE_NAME.lower()
            ),
            None,
        )
        if exact:
            return exact

    computers = [
        d for d in usable
        if d.get("type") == "Computer"
    ]

    active_computer = next(
        (d for d in computers if d.get("is_active")),
        None,
    )

    if active_computer:
        return active_computer

    if computers:
        return computers[0]

    return next(
        (d for d in usable if d.get("is_active")),
        None,
    )


def discover_laptop_device():
    """
    Ask Spotify for a fresh device list and pick the laptop.
    If the laptop is not visible, open Spotify desktop once and keep
    polling until it shows up or DEVICE_WAIT_SECONDS runs out.
    """

    global cached_device

    deadline = time.monotonic() + DEVICE_WAIT_SECONDS
    last_error = None
    logged = False
    opened = False

    while time.monotonic() < deadline:
        try:
            ds = devices()

            # Log devices once per discovery call.
            if ds and not logged:
                logged = True
                names = ", ".join(
                    f"{d.get('name','?')} [{d.get('type','?')}]"
                    for d in ds
                )
                log("Spotify devices: " + names)

            selected = choose_laptop_device(ds)

            if selected:
                cached_device = selected
                log(
                    f"Selected Spotify device: "
                    f"{selected.get('name', 'Computer')} "
                    f"(id refreshed)"
                )
                return selected

            if not opened:
                opened = True
                log("Laptop not visible to Spotify; opening Spotify...")
                open_spotify()

        except Exception as exc:
            last_error = exc

        time.sleep(DEVICE_POLL_SECONDS)

    if last_error:
        log("Device discovery last error: " + str(last_error))

    return None


# ============================================================
# PLAYBACK
# ============================================================

def track_id_from_url(url):
    url = (url or "").strip()

    if "/track/" in url:
        track_id = url.split("/track/", 1)[1].split("?", 1)[0].strip()
    elif url.startswith("spotify:track:"):
        track_id = url.rsplit(":", 1)[1].strip()
    else:
        raise RuntimeError(
            "Use a Spotify track URL such as "
            "https://open.spotify.com/track/..."
        )

    if not re_full_track_id(track_id):
        raise RuntimeError("Invalid Spotify track URL.")

    return track_id


def re_full_track_id(track_id):
    # Spotify IDs are normally 22-character base62 strings.
    return bool(track_id) and len(track_id) >= 10 and all(
        c.isalnum() or c in "_-" for c in track_id
    )


def transfer_to_device(device_id):
    """
    Move Spotify playback to the laptop without resuming the old song.
    A 204 response means success.
    """

    r = api(
        "PUT",
        "/me/player",
        json={
            "device_ids": [device_id],
            "play": False,
        },
    )

    if r.status_code not in (200, 204):
        raise RuntimeError(
            f"Transfer failed: {r.status_code} {r.text}"
        )


def start_track(device_id, track_id):
    """
    Play the track on the given device. Passing device_id already moves
    playback there, so no separate transfer is needed in the normal case.
    """

    r = api(
        "PUT",
        "/me/player/play",
        params={"device_id": device_id},
        json={
            "uris": [
                "spotify:track:" + track_id
            ]
        },
    )

    if r.status_code not in (200, 204):
        raise RuntimeError(
            f"Play failed: {r.status_code} {r.text}"
        )


def is_playing_track(track_id):
    """
    True only if the laptop is playing this exact track right now.
    A finished, paused or skipped song does not count, so scanning
    the same card again starts it over.
    """

    try:
        r = api("GET", "/me/player")
    except Exception:
        return False

    # 204 = nothing playing.
    if r.status_code != 200 or not r.content:
        return False

    data = r.json()

    device = data.get("device") or {}
    if device.get("type") != "Computer":
        return False

    item = data.get("item") or {}
    ids = {
        item.get("id"),
        (item.get("linked_from") or {}).get("id"),
    }

    return bool(data.get("is_playing")) and track_id in ids


def play_result(device, changed, track_id, skipped=False):
    return {
        "device": (
            device.get("name", "Laptop")
            if device
            else "Laptop"
        ),
        "changed": changed,
        "skipped": skipped,
        "track_id": track_id,
    }


def play(url):
    """
    Switch to a different RFID track.

    Several cards scanned quickly:
       only the last one plays; older scans still waiting are skipped.

    Same track, still playing:
       no Spotify command.

    Different track:
       reuse the known laptop device (look it up if unknown)
       start track on the laptop
       (transfer first only if Spotify says the laptop is inactive)
       if anything goes stale, look the device up again and retry.
    """

    global cached_device, latest_scan

    track_id = track_id_from_url(url)

    with scan_lock:
        latest_scan += 1
        scan = latest_scan

    with play_lock:
        # SAME TRACK and still playing: do nothing.
        if scan == latest_scan and is_playing_track(track_id):
            return play_result(cached_device, False, track_id)

        last_error = None

        for attempt in range(1, PLAY_ATTEMPTS + 1):
            # A newer card was scanned while this one waited: let it win.
            if scan != latest_scan:
                log(f"Skipping track {track_id}; a newer card was scanned")
                return play_result(cached_device, False, track_id, True)

            log(
                f"Playback attempt {attempt}/{PLAY_ATTEMPTS} "
                f"for track {track_id}"
            )

            # Reuse the known laptop; look it up after any failure.
            device = cached_device or discover_laptop_device()

            if not device:
                last_error = (
                    "Spotify desktop device is not visible to Spotify API."
                )
                time.sleep(0.4)
                continue

            device_id = device["id"]

            try:
                try:
                    start_track(device_id, track_id)
                except RuntimeError as exc:
                    # 404 = laptop not active yet. Wake it up silently,
                    # then play.
                    if "Play failed: 404" not in str(exc):
                        raise
                    transfer_to_device(device_id)
                    time.sleep(0.15)
                    start_track(device_id, track_id)

                cached_device = device

                log(
                    f"SUCCESS: {device.get('name', 'Laptop')} "
                    f"-> {track_id}"
                )

                return play_result(device, True, track_id)

            except Exception as exc:
                last_error = exc
                log(
                    f"Attempt {attempt} failed: {exc}. "
                    f"Refreshing Spotify device ID..."
                )

                # Forget stale device information immediately.
                cached_device = None
                time.sleep(0.35)

        raise RuntimeError(
            "Could not switch Spotify playback after "
            f"{PLAY_ATTEMPTS} attempts. Last error: {last_error}"
        )


# ============================================================
# FLASK SERVER
# ============================================================

app = Flask(__name__)


@app.get("/callback")
def callback():
    if request.args.get("state") != state:
        return "<h2>Invalid authorization state.</h2>", 400

    try:
        exchange(request.args["code"])
        log("Spotify authorization completed.")
        return (
            "<h2>Spotify connected.</h2>"
            "<p>You can close this tab.</p>"
        )
    except Exception as exc:
        log("Spotify authorization error: " + str(exc))
        return (
            "<h2>Authorization failed</h2>"
            "<pre>" + str(exc) + "</pre>"
        ), 400


@app.post("/rfid")
def rfid():
    if not control:
        return jsonify(
            ok=False,
            error="RFID control OFF",
        ), 403

    payload = request.get_json(silent=True) or {}

    uid = " ".join(
        str(payload.get("uid", "")).upper().split()
    )

    if not uid:
        return jsonify(
            ok=False,
            error="Missing RFID UID",
        ), 400

    with map_lock:
        item = mappings.get(uid) or register_card(uid)

    # New card, or a card nobody has picked a song for yet:
    # show its QR on the laptop so the holder can claim it.
    if not item.get("spotify"):
        log(f"RFID {uid} -> {item.get('name', uid)} has no song; showing QR")
        ui(lambda: show_qr(uid))
        return jsonify(
            ok=True,
            changed=False,
            claim=True,
            message="No song yet; scan the QR code on the laptop",
        ), 202

    try:
        result = play(item.get("spotify", ""))

        if result["skipped"]:
            message = "Skipped; a newer card was scanned"
        elif result["changed"]:
            log(
                f"RFID {uid} -> "
                f"{item.get('name', uid)} -> "
                f"{result['device']}"
            )
            message = "Song changed"
        else:
            log(
                f"RFID {uid} -> "
                f"{item.get('name', uid)} -> "
                f"same song, no change"
            )
            message = "Same song; no change"

        return jsonify(
            ok=True,
            device=result["device"],
            changed=result["changed"],
            message=message,
        )

    except Exception as exc:
        log(
            f"Playback error for RFID {uid}: {exc}"
        )
        return jsonify(
            ok=False,
            error=str(exc),
        ), 500


# ============================================================
# CARD PAGE (opened on the holder's phone)
# ============================================================

def split_name(name):
    """'0012 / di' -> ('0012', 'di'). Cards without a number keep
    the whole name as the holder."""

    m = re.match(r"\s*(\d+)\s*(?:/\s*(.*))?$", name or "")
    if not m:
        return "", (name or "").strip()
    return m.group(1), (m.group(2) or "").strip()


def join_name(number, holder):
    if number and holder:
        return f"{number} / {holder}"
    return number or holder


def track_summary(t):
    images = (t.get("album") or {}).get("images") or []
    return {
        "id": t.get("id"),
        "title": t.get("name", ""),
        "artists": ", ".join(a.get("name", "") for a in t.get("artists", [])),
        # Spotify lists album art largest first; the smallest is enough.
        "image": images[-1]["url"] if images else "",
    }


def track_title(t):
    return f"{t['title']} — {t['artists']}"


def play_quietly(url):
    try:
        play(url)
    except Exception as exc:
        log("Playback error after card update: " + str(exc))


CARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tapnotic</title>
<style>
  :root {
    --bg: #0e0d12; --card: #18161f; --line: #2a2733; --text: #f1eff6;
    --muted: #9a95a8; --accent: #b28cff; --accent-ink: #160f24; --ok: #6fe0a4;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font: 16px/1.4 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  }
  main { max-width: 480px; margin: 0 auto; padding: 24px 16px 120px; }
  .brand { color: var(--accent); font-weight: 700; letter-spacing: .08em;
           text-transform: uppercase; font-size: 13px; }
  h1 { margin: 4px 0 20px; font-size: 28px; }
  .now { background: var(--card); border: 1px solid var(--line);
         border-radius: 14px; padding: 14px 16px; margin-bottom: 22px; }
  .now small { color: var(--muted); display: block; margin-bottom: 2px; }
  label { display: block; color: var(--muted); font-size: 14px; margin: 0 0 6px; }
  input {
    width: 100%; padding: 13px 14px; margin-bottom: 18px; font: inherit;
    color: var(--text); background: var(--card); border: 1px solid var(--line);
    border-radius: 12px; outline: none;
  }
  input:focus { border-color: var(--accent); }
  #status { color: var(--muted); min-height: 1.4em; margin: -8px 0 8px; font-size: 14px; }
  ul { list-style: none; margin: 0; padding: 0; }
  .track {
    display: flex; gap: 12px; align-items: center; padding: 8px;
    border-radius: 12px; cursor: pointer; border: 1px solid transparent;
  }
  .track:active, .track:focus { background: var(--card); outline: none; }
  .track.on { background: var(--card); border-color: var(--accent); }
  .track img { width: 48px; height: 48px; border-radius: 6px; background: var(--line); flex: none; }
  .track div { min-width: 0; }
  .track b, .track span { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .track span { color: var(--muted); font-size: 14px; }
  .bar {
    position: fixed; left: 0; right: 0; bottom: 0; padding: 12px 16px 20px;
    background: linear-gradient(transparent, var(--bg) 30%);
  }
  button {
    display: block; width: 100%; max-width: 448px; margin: 0 auto; padding: 15px;
    font: inherit; font-weight: 700; border: 0; border-radius: 14px;
    background: var(--accent); color: var(--accent-ink); cursor: pointer;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  button:disabled { opacity: .35; cursor: default; }
  .done { color: var(--ok); }
</style>
</head>
<body>
<main>
  <div class="brand">Tapnotic</div>
  <h1 id="num">Your card</h1>

  <div class="now">
    <small>Current song</small>
    <div id="current">No song yet</div>
  </div>

  <label for="name">Your name</label>
  <input id="name" maxlength="30" autocomplete="off" placeholder="e.g. abhij">

  <label for="q">Pick your song</label>
  <input id="q" type="search" autocomplete="off" placeholder="Search Spotify">
  <div id="status"></div>
  <ul id="results"></ul>
</main>

<div class="bar"><button id="save" disabled>Pick a song</button></div>

<script>
const CARD = __CARD__;
const $ = (s) => document.querySelector(s);
let chosen = null, timer = null, seq = 0;

$("#num").textContent = CARD.number ? "Card " + CARD.number : "Your card";
$("#name").value = CARD.holder;
if (CARD.title) $("#current").textContent = CARD.title;
else if (CARD.spotify) $("#current").textContent = "A song is set";

$("#q").addEventListener("input", () => {
  clearTimeout(timer);
  timer = setTimeout(search, 300);
});

async function search() {
  const q = $("#q").value.trim();
  const mine = ++seq;
  if (!q) { render([]); $("#status").textContent = ""; return; }
  $("#status").textContent = "Searching...";
  try {
    const r = await fetch("/card/" + CARD.key + "/search?q=" + encodeURIComponent(q));
    const d = await r.json();
    if (mine !== seq) return;
    if (!r.ok) throw new Error(d.error || "Search failed");
    $("#status").textContent = d.tracks.length ? "" : "No songs found";
    render(d.tracks);
  } catch (e) {
    if (mine === seq) $("#status").textContent = e.message;
  }
}

function render(tracks) {
  const list = $("#results");
  list.replaceChildren();
  for (const t of tracks) {
    const li = document.createElement("li");
    li.className = "track";
    li.tabIndex = 0;
    const img = document.createElement("img");
    img.alt = "";
    if (t.image) img.src = t.image;
    const text = document.createElement("div");
    const title = document.createElement("b");
    title.textContent = t.title;
    const artists = document.createElement("span");
    artists.textContent = t.artists;
    text.append(title, artists);
    li.append(img, text);
    li.addEventListener("click", () => pick(t, li));
    list.append(li);
  }
}

function pick(t, li) {
  chosen = t;
  document.querySelectorAll(".track.on").forEach((x) => x.classList.remove("on"));
  li.classList.add("on");
  $("#save").disabled = false;
  $("#save").textContent = "Save “" + t.title + "”";
}

$("#save").addEventListener("click", async () => {
  if (!chosen) return;
  const btn = $("#save");
  btn.disabled = true;
  btn.textContent = "Saving...";
  try {
    const r = await fetch("/card/" + CARD.key, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: $("#name").value, track_id: chosen.id }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || "Could not save");
    $("#current").textContent = d.title;
    $("#current").classList.add("done");
    btn.textContent = "Saved — playing on the speaker";
  } catch (e) {
    btn.disabled = false;
    btn.textContent = e.message + " — try again";
  }
});
</script>
</body>
</html>
"""


@app.get("/card/<key>")
def card_page(key):
    uid, value = card_by_key(key)

    if not uid:
        return "<h2>This card link is not valid.</h2>", 404

    # Cards set up before the page existed have no title yet.
    if value.get("spotify") and not value.get("title"):
        try:
            r = api("GET", "/tracks/" + track_id_from_url(value["spotify"]))
            if r.status_code == 200:
                t = track_summary(r.json())
                with map_lock:
                    value["title"] = track_title(t)
                    save()
        except Exception:
            pass

    number, holder = split_name(value.get("name", ""))
    info = {
        "key": key,
        "number": number,
        "holder": holder,
        "title": value.get("title", ""),
        "spotify": value.get("spotify", ""),
    }

    # "</" is escaped so card data can never close the script tag.
    return CARD_HTML.replace(
        "__CARD__",
        json.dumps(info).replace("</", "<\\/"),
    )


@app.get("/card/<key>/search")
def card_search(key):
    uid, _ = card_by_key(key)

    if not uid:
        return jsonify(error="This card link is not valid."), 404

    q = request.args.get("q", "").strip()[:100]

    if not q:
        return jsonify(tracks=[])

    try:
        r = api(
            "GET",
            "/search",
            params={"q": q, "type": "track", "limit": 10},
        )
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 503

    if r.status_code != 200:
        return jsonify(error=f"Spotify search failed ({r.status_code})"), 502

    items = (r.json().get("tracks") or {}).get("items") or []

    return jsonify(tracks=[track_summary(t) for t in items if t])


@app.post("/card/<key>")
def card_save(key):
    uid, _ = card_by_key(key)

    if not uid:
        return jsonify(error="This card link is not valid."), 404

    data = request.get_json(silent=True) or {}
    holder = " ".join(str(data.get("name", "")).split())[:30]
    track_id = str(data.get("track_id", "")).strip()

    if not re_full_track_id(track_id):
        return jsonify(error="Pick a song first"), 400

    # Look the track up so only real Spotify songs are saved.
    try:
        r = api("GET", "/tracks/" + track_id)
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 503

    if r.status_code != 200:
        return jsonify(error="Song not found on Spotify"), 400

    t = track_summary(r.json())
    title = track_title(t)
    url = "https://open.spotify.com/track/" + track_id

    with map_lock:
        uid, value = card_by_key(key)

        if not uid:
            return jsonify(error="This card link is not valid."), 404

        number, old_holder = split_name(value.get("name", ""))
        value["name"] = join_name(number, holder or old_holder) or uid
        value["spotify"] = url
        value["title"] = title
        save()

    log(f"Card {value['name']} set its song: {title}")
    ui(refresh_tree)
    ui(lambda: close_qr(uid))

    threading.Thread(
        target=play_quietly,
        args=(url,),
        daemon=True,
    ).start()

    return jsonify(ok=True, title=title)


def server():
    app.run(
        host=HOST,
        port=PORT,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


# ============================================================
# GUI
# ============================================================

def save():
    with map_lock:
        write_json(MAP, mappings)


def selected():
    selection = tree.selection()

    if not selection:
        return None

    return tree.item(
        selection[0],
        "values",
    )[0]


def refresh_tree():
    for item in tree.get_children():
        tree.delete(item)

    for uid, value in sorted(mappings.items()):
        tree.insert(
            "",
            "end",
            values=(
                uid,
                value.get("name", ""),
                value.get("spotify", "") or "UNASSIGNED",
            ),
        )


def add_card():
    uid = simpledialog.askstring(
        "Add RFID",
        "UID:",
        parent=root,
    )

    if not uid:
        return

    uid = " ".join(uid.upper().split())

    if uid in mappings:
        messagebox.showerror(
            "Exists",
            "That UID already exists.",
            parent=root,
        )
        return

    name = simpledialog.askstring(
        "Card name",
        "Name/number:",
        parent=root,
    ) or uid

    url = simpledialog.askstring(
        "Spotify URL",
        "Spotify track URL (optional):",
        parent=root,
    ) or ""

    mappings[uid] = {
        "name": name.strip() or uid,
        "spotify": url.strip(),
        "key": new_key(),
    }

    save()
    refresh_tree()
    log("Added RFID " + uid)


def edit_card():
    uid = selected()

    if not uid:
        messagebox.showinfo(
            "Edit",
            "Select an RFID card first.",
            parent=root,
        )
        return

    value = mappings[uid]

    name = simpledialog.askstring(
        "Edit card",
        "Name/number:",
        initialvalue=value.get("name", ""),
        parent=root,
    )

    if name is None:
        return

    url = simpledialog.askstring(
        "Edit card",
        "Spotify track URL:",
        initialvalue=value.get("spotify", ""),
        parent=root,
    )

    if url is None:
        return

    # Keep the card's key and anything else stored on it.
    mappings[uid] = {
        **value,
        "name": name.strip() or uid,
        "spotify": url.strip(),
    }

    save()
    refresh_tree()

    log("Updated RFID " + uid)


def delete_card():
    uid = selected()

    if not uid:
        messagebox.showinfo(
            "Delete",
            "Select an RFID card first.",
            parent=root,
        )
        return

    if messagebox.askyesno(
        "Delete",
        f"Delete {uid}?",
        parent=root,
    ):
        mappings.pop(uid, None)
        save()
        refresh_tree()
        log("Deleted RFID " + uid)


qr_windows = {}


def share_card():
    uid = selected()

    if not uid:
        messagebox.showinfo(
            "Show QR",
            "Select an RFID card first.",
            parent=root,
        )
        return

    show_qr(uid)


def qr_matrix(text):
    qr = qrcode.QRCode(border=2)
    qr.add_data(text)
    qr.make(fit=True)
    return qr.get_matrix()


def show_qr(uid):
    """Pop up the card's link as a QR code for the holder to scan."""

    if uid not in mappings:
        return

    win = qr_windows.get(uid)
    if win and win.winfo_exists():
        win.lift()
        return

    link = card_link(uid)
    number, holder = split_name(mappings[uid].get("name", ""))

    win = tk.Toplevel(root)
    win.title("Card " + (number or uid))
    win.configure(padx=24, pady=20)
    win.resizable(False, False)
    win.attributes("-topmost", True)
    qr_windows[uid] = win

    ttk.Label(
        win,
        text=("Card " + number) if number else uid,
        font=("Segoe UI", 18, "bold"),
    ).pack()

    ttk.Label(
        win,
        text=(
            f"Hi {holder}, scan to change your song"
            if holder
            else "Scan to pick your song"
        ),
    ).pack(pady=(2, 12))

    matrix = qr_matrix(link)
    cell = max(4, 300 // len(matrix))
    size = cell * len(matrix)

    canvas = tk.Canvas(
        win,
        width=size,
        height=size,
        bg="white",
        highlightthickness=0,
    )
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                canvas.create_rectangle(
                    x * cell,
                    y * cell,
                    (x + 1) * cell,
                    (y + 1) * cell,
                    fill="black",
                    width=0,
                )
    canvas.pack()

    # Read-only entry so the link can also be copied.
    entry = ttk.Entry(win, width=len(link))
    entry.insert(0, link)
    entry.configure(state="readonly")
    entry.pack(pady=(12, 0))

    ttk.Button(
        win,
        text="Close",
        command=lambda: close_qr(uid),
    ).pack(pady=(12, 0))

    win.after(QR_SECONDS * 1000, lambda: close_qr(uid))


def close_qr(uid):
    win = qr_windows.pop(uid, None)

    if win and win.winfo_exists():
        win.destroy()


def test():
    uid = selected()

    if not uid:
        messagebox.showinfo(
            "Test",
            "Select an RFID card first.",
            parent=root,
        )
        return

    def worker():
        try:
            item = mappings[uid]

            log(
                "TEST: " +
                item.get("name", uid)
            )

            result = play(
                item.get("spotify", "")
            )

            if result["skipped"]:
                log(
                    "TEST: skipped; a newer card was scanned."
                )
            elif result["changed"]:
                log(
                    "TEST SUCCESS: " +
                    result["device"]
                )
            else:
                log(
                    "TEST: same track; no change."
                )

        except Exception as exc:
            log(
                "TEST ERROR: " +
                str(exc)
            )

    threading.Thread(
        target=worker,
        daemon=True,
    ).start()


def test_devices():
    def worker():
        try:
            log("Refreshing Spotify device list...")
            ds = devices()

            if not ds:
                log("Spotify returned NO devices.")
                return

            for d in ds:
                log(
                    f"DEVICE: {d.get('name')} | "
                    f"type={d.get('type')} | "
                    f"active={d.get('is_active')} | "
                    f"restricted={d.get('is_restricted')}"
                )

            selected_device = choose_laptop_device(ds)

            if selected_device:
                log(
                    "Selected: " +
                    selected_device.get(
                        "name",
                        "Unknown"
                    )
                )
            else:
                log(
                    "No Spotify desktop computer found."
                )

        except Exception as exc:
            log(
                "DEVICE TEST ERROR: " +
                str(exc)
            )

    threading.Thread(
        target=worker,
        daemon=True,
    ).start()


def auth_click():
    try:
        authorize()
        log(
            "Spotify authorization opened in browser."
        )
    except Exception as exc:
        messagebox.showerror(
            "Spotify",
            str(exc),
            parent=root,
        )


def toggle_click():
    global control

    control = bool(toggle.get())

    log(
        "RFID control " +
        ("ON" if control else "OFF")
    )


def build():
    global root, tree, logbox, toggle

    root = tk.Tk()
    root.title(
        "RFID -> Spotify Desktop Controller"
    )
    root.geometry(
        "1180x720"
    )

    top = ttk.Frame(
        root,
        padding=12,
    )
    top.pack(fill="x")

    ttk.Label(
        top,
        text="RFID -> Spotify",
        font=("Segoe UI", 22, "bold"),
    ).pack(side="left")

    toggle = tk.BooleanVar(
        value=True
    )

    ttk.Checkbutton(
        top,
        text="RFID CONTROL",
        variable=toggle,
        command=toggle_click,
    ).pack(side="right")

    buttons = ttk.Frame(
        root,
        padding=(12, 0, 12, 8),
    )
    buttons.pack(fill="x")

    button_list = [
        ("Authorize Spotify", auth_click),
        ("Open Spotify", open_spotify),
        ("Test Devices", test_devices),
        ("Test Selected", test),
        ("Show QR", share_card),
        ("+ Add Card", add_card),
        ("Edit", edit_card),
        ("Delete", delete_card),
    ]

    for text, command in button_list:
        ttk.Button(
            buttons,
            text=text,
            command=command,
        ).pack(
            side="left",
            padx=4,
        )

    frame = ttk.Frame(
        root,
        padding=12,
    )
    frame.pack(
        fill="both",
        expand=True,
    )

    tree = ttk.Treeview(
        frame,
        columns=(
            "UID",
            "Name",
            "Spotify URL",
        ),
        show="headings",
    )

    for column, width in [
        ("UID", 180),
        ("Name", 210),
        ("Spotify URL", 700),
    ]:
        tree.heading(
            column,
            text=column,
        )
        tree.column(
            column,
            width=width,
        )

    tree.pack(
        side="left",
        fill="both",
        expand=True,
    )

    scrollbar = ttk.Scrollbar(
        frame,
        orient="vertical",
        command=tree.yview,
    )
    scrollbar.pack(
        side="right",
        fill="y",
    )

    tree.configure(
        yscrollcommand=scrollbar.set
    )

    activity = ttk.LabelFrame(
        root,
        text="Activity",
        padding=8,
    )
    activity.pack(
        fill="x",
        padx=12,
        pady=(0, 12),
    )

    logbox = tk.Text(
        activity,
        height=9,
    )
    logbox.pack(
        fill="x"
    )

    refresh_tree()

    log(
        "RFID -> Spotify desktop controller started."
    )
    log(
        "RFID endpoint: "
        f"http://<LAPTOP-IP>:{PORT}/rfid"
    )
    log(
        "Browser is used only for Spotify authorization."
    )
    log(
        "Playback uses the native Spotify desktop app."
    )
    log(
        "Different RFID = immediate switch on the laptop."
    )
    log(
        "Same RFID/song while playing = no Spotify playback command."
    )

    if startup_warning:
        log("WARNING: " + startup_warning)

    if LAPTOP_DEVICE_NAME:
        log(
            "Preferred Spotify device name: "
            + LAPTOP_DEVICE_NAME
        )

    return root


if __name__ == "__main__":
    threading.Thread(
        target=server,
        daemon=True,
    ).start()

    time.sleep(0.5)

    build()

    root.mainloop()
