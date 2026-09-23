RFID -> Spotify Desktop Controller

1. Keep mappings.json and spotify_token.json from your existing app if you already have them.
2. Put app.py, requirements.txt, .env and mappings.json in the same folder.
3. Install:
   py -m pip install -r requirements.txt
4. Run:
   py app.py
5. Click Authorize Spotify once if needed.
6. Keep Spotify desktop installed and signed in.
7. Click Test Devices. The laptop should appear as type=Computer.
8. ESP32 should POST JSON like {"uid":"9A ED EA 30"} to:
   http://LAPTOP_IP:5000/rfid

This version:
- remembers the laptop's Spotify device, so switching is fast
- starts the track directly on the laptop (no blip of the previous song)
- looks the device up again and retries if it goes stale
- opens Spotify desktop only when the laptop isn't visible to Spotify
- several cards scanned quickly: only the last one plays
- same track scanned again does nothing while it is still playing
- a finished or paused song starts over when its card is scanned
- uses Spotify desktop for playback; browser is only OAuth
- keeps Add/Edit/Delete card management
- does not overwrite an existing mappings.json
- saves mappings.json safely; if it ever gets corrupted it is kept as
  mappings.broken-<date>.json instead of being replaced

Card holders pick their own song:
- every card has a private page at http://LAPTOP_IP:5000/card/<key>
- the holder opens it on their phone (same Wi-Fi), types their name,
  searches Spotify and saves; the song plays on the speaker right away
- the link keeps working, so they can bookmark it and change the song
  anytime
