# Live Clipper

A website with a command bar for clipping YouTube **live streams** (and finished videos) while you watch.

```
load https://www.youtube.com/watch?v=...   (or just paste the link)
clip 30            last 30 s (on a live stream: up to the live edge, or wherever you've rewound to)
clip 1:20-1:50     exact range (finished videos, and live DVR)
in / out / clip    mark in, mark out, clip between the marks
peaks / peak 2     YouTube "most replayed" moments, clip ±15 s around one
vertical on        also export 9:16 (blurred background) for Reels/Shorts
seek 12:30 · pass <code> · clear · help
```
Hotkeys: `I` in · `O` out · `C` clip marks · `L` last 30 s · `V` toggle 9:16 · `/` command bar.
Clips appear on the right with a preview and download links. Files are saved in `clips/`.

## Run it on your PC (recommended)
YouTube blocks most cloud servers, so run it at home:

1. Install Python 3.10+ and ffmpeg (`winget install Gyan.FFmpeg` / `brew install ffmpeg`).
2. Windows: double-click `start-windows.bat`. Mac/Linux: `pip install -U yt-dlp && python3 app.py`.
3. Open http://localhost:8080.

If YouTube says "sign in to confirm you're not a bot", set `COOKIES_FROM_BROWSER=chrome` (or firefox/edge) before starting.

## Make it a live public website
Keep it running on your PC and put a public link in front of it:
```
set CLIPPER_PASSCODE=pick-something      (mac/linux: export CLIPPER_PASSCODE=...)
python app.py
cloudflared tunnel --url http://localhost:8080   (winget install Cloudflare.cloudflared)
```
cloudflared prints an `https://….trycloudflare.com` URL you can open from your phone or share with an editor.
**Always set a passcode before exposing it**, or anyone with the link can use your machine to download.

## How it clips
- **Live, "last N seconds":** gets the stream's HLS URL with `yt-dlp -g`, then `ffmpeg -live_start_index -K`
  pulls exactly the segments behind the live edge (no re-encode, ready in seconds).
- **Ranges:** `yt-dlp --download-sections` (+ `--live-from-start` for live DVR), cut on keyframes.
- **Viral moments:** YouTube's "most replayed" heatmap from `yt-dlp -J` (finished videos only).

Clips belong to the streamer. Credit them, keep excerpts short and add your own commentary before reposting.
