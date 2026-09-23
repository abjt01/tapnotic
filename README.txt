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
- always refreshes Spotify device discovery for a different RFID track
- transfers playback to the laptop before starting the track
- retries with fresh device IDs
- same track scanned again does nothing while it is still playing
- a finished or paused song starts over when its card is scanned
- uses Spotify desktop for playback; browser is only OAuth
- keeps Add/Edit/Delete card management
- does not overwrite an existing mappings.json
