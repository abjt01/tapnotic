RFID -> Spotify Desktop Controller

1. Keep mappings.json and spotify_token.json from your existing app if you already have them.
2. Put app.py, requirements.txt, .env and mappings.json in the same folder.
3. Install:
   py -m pip install -r requirements.txt
4. Run:
   py app.py
   (or double-click run_app.bat, which installs requirements if needed)
5. Click Authorize Spotify once if needed.
6. Keep Spotify desktop installed and signed in.
7. Click Test Devices. The laptop should appear as type=Computer.
8. ESP32 should POST JSON like {"uid":"9A ED EA 30"} to:
   http://LAPTOP_IP:5000/rfid
   Replies: 200 = played / same song, 202 = card has no song yet
   (QR shown on the laptop), 403 = RFID control off.

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
- tap a new card (or one with no song yet) and it is registered
  automatically; a QR code for its page pops up on the laptop
- every card has a private page at http://LAPTOP_IP:5000/card/<key>
- the holder opens it on their phone (same Wi-Fi), types their name,
  searches Spotify and saves; the song plays on the speaker right away
- for cards set up before this, select the card and click Show QR
- the link keeps working, so they can bookmark it and change the song
  anytime

Windows setup (do once):
- Keep the folder outside OneDrive, e.g. C:\tapnotic. OneDrive syncs the
  Desktop by default and can briefly lock mappings.json (saves are
  retried, but it is better avoided).
- Allow Python through Windows Firewall when asked, and make sure the
  Wi-Fi is set to "Private network" (Settings > Network & internet >
  Wi-Fi > your network). On "Public", phones and the ESP32 are blocked.
- Tapnotic keeps Windows awake while it is open, but closing the lid can
  still sleep the laptop: Control Panel > Power Options > "Choose what
  closing the lid does" > Do nothing (when plugged in).
- Give the laptop a fixed IP in your router (DHCP reservation), so the
  ESP32 address and bookmarked card links keep working.
- If card QR codes show the wrong IP (VPN, Hyper-V, VirtualBox), set
  TAPNOTIC_HOST in .env to the laptop's Wi-Fi IP.
