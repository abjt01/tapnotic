RFID -> Spotify Desktop Controller (fixed)

Replace your existing app.py with this app.py. Keep your existing .env and mappings.json.

Main fixes:
- Caches the laptop Spotify device ID for fast RFID switching.
- Does not rediscover devices on every scan.
- If a different RFID track is scanned, transfers playback to the laptop and starts the new track.
- If the same track is already playing, it does nothing.
- If the cached device ID becomes stale, refreshes devices once and retries.
- Browser is used only for Spotify authorization.
- Spotify desktop app is opened when needed.

Run:
  py app.py

Do not share your .env file or Spotify client secret.
