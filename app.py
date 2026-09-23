import os
import json
import time
import secrets
import webbrowser
import threading
import urllib.parse
import subprocess
import platform
from pathlib import Path

import requests
from flask import Flask, request, jsonify
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

# ============================================================
# RFID -> Spotify Desktop Controller
# - ESP32 sends POST /rfid to this laptop
# - Laptop controls the native Spotify desktop app
# - Every DIFFERENT RFID card refreshes Spotify devices
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


def load_env():
    if not ENV.exists():
        return
    for line in ENV.read_text(encoding="utf-8").splitlines():
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

if MAP.exists():
    try:
        mappings = json.loads(MAP.read_text(encoding="utf-8"))
    except Exception:
        mappings = dict(DEFAULT)
else:
    mappings = dict(DEFAULT)
    MAP.write_text(
        json.dumps(mappings, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ============================================================
# RUNTIME STATE
# ============================================================

access = None
refresh = None
expires = 0
state = None
control = True

# Only informational cache. We DO NOT trust this cache for playback.
cached_device = None
play_lock = threading.Lock()


if TOKEN.exists():
    try:
        token_data = json.loads(TOKEN.read_text(encoding="utf-8"))
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


# ============================================================
# TOKEN / SPOTIFY API
# ============================================================

def save_token():
    if refresh:
        TOKEN.write_text(
            json.dumps(
                {"refresh": refresh, "expires": expires},
                indent=2,
            ),
            encoding="utf-8",
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
    IMPORTANT:
    Always asks Spotify for a fresh device list.
    This prevents stale device IDs from causing:
      'Spotify laptop device disappeared'
    """

    global cached_device

    deadline = time.monotonic() + DEVICE_WAIT_SECONDS
    last_error = None

    while time.monotonic() < deadline:
        try:
            ds = devices()

            # Log devices once per discovery call.
            if ds:
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


def play(url):
    """
    Switch to a different RFID track.

    Same track, still playing:
       no Spotify command.

    Different track:
       open Spotify
       fresh device discovery
       start track on the laptop
       (transfer first only if Spotify says the laptop is inactive)
       if anything goes stale, refresh the device and retry.
    """

    global cached_device

    track_id = track_id_from_url(url)

    with play_lock:
        # SAME TRACK and still playing: do nothing.
        if is_playing_track(track_id):
            return {
                "device": (
                    cached_device.get("name", "Laptop")
                    if cached_device
                    else "Laptop"
                ),
                "changed": False,
                "track_id": track_id,
            }

        open_spotify()

        last_error = None

        for attempt in range(1, PLAY_ATTEMPTS + 1):
            log(
                f"Playback attempt {attempt}/{PLAY_ATTEMPTS} "
                f"for track {track_id}"
            )

            # NEVER trust the old device ID.
            device = discover_laptop_device()

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

                return {
                    "device": device.get("name", "Laptop"),
                    "changed": True,
                    "track_id": track_id,
                }

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
            f"{PLAY_ATTEMPTS} fresh attempts. Last error: {last_error}"
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

    item = mappings.get(uid)

    if not item:
        log("Unknown RFID: " + uid)
        return jsonify(
            ok=False,
            error="Unknown RFID",
            uid=uid,
        ), 404

    try:
        result = play(item.get("spotify", ""))

        if result["changed"]:
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
    MAP.write_text(
        json.dumps(
            mappings,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


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

    mappings[uid] = {
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

            if result["changed"]:
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
        "Different RFID = fresh device discovery + immediate switch."
    )
    log(
        "Same RFID/song while playing = no Spotify playback command."
    )

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
