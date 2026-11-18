# Reaction Studio — viral clips × Vice City gameplay

Pipeline: **fetch** viral Instagram reels/live replays → **auto-cut highlights** (loudest moments) →
either **play them live** next to your Vice City session in OBS, or **compose** finished 9:16 reels
(clip on top, your gameplay below, round facecam on the seam, creator credit).

## Install (once)
```bash
pip install -U yt-dlp            # downloader
# ffmpeg: Windows `winget install Gyan.FFmpeg` · macOS `brew install ffmpeg`
```

## 1. Collect clips
Paste reel / live-replay links into `urls.txt` (one per line), then:
```bash
python studio.py fetch --cookies-from-browser chrome   # uses your logged-in IG session
```
Instagram blocks anonymous downloads, so the cookies flag is usually required. Downloads are
throttled (3s between requests) to avoid tripping rate limits. Finding *which* clips are viral is
on you: Reels tab, live-replay highlights, or meme pages.

## 2. Auto-cut highlights
```bash
python studio.py highlights --count 3 --length 20 --preroll 3
```
For each video it scores every second by EBU R128 loudness (screaming, crowd noise, music drops)
and cuts the top non-overlapping windows to `clips/`, keeping 3s of build-up before the peak.

## 3a. Live mode: play Vice City + react on stream/recording
```bash
python studio.py playlist           # writes playlist.json, with creator credits
python -m http.server 8000          # serve this folder
```
OBS scene (1920×1080):
| Source | Type | Placement |
|---|---|---|
| Vice City | Game Capture | full canvas |
| Clips | Browser Source → `http://localhost:8000/player.html?gap=1500` | right third, ~640×1080 |
| Facecam | Video Capture Device | bottom-left corner, add a circle mask |
| Mic | Audio Input | — |

Tick "Control audio via OBS" on the Browser Source so you can duck the clip under your voice.
Hotkeys (Interact with the Browser Source): `Space` pause · `N`/`→` next · `P`/`←` back ·
`R` replay · `M` mute · `S` shuffle. `?loop=0` stops after the last clip.

Record with OBS (`Settings → Output → Recording`, MKV, then *Remux to MP4*).

## 3b. Post mode: build vertical reels from separate recordings
```bash
python studio.py compose --clip clips/creator_xyz_hl1.mp4 \
  --gameplay vicecity.mp4 --game-start 120 \
  --facecam cam.mp4 --cam-start 0 \
  --credit "@creator_xyz" --out reel_01.mp4
```
Options: `--split 0.55` (clip's share of height), `--game-vol 0.25`, `--cam-vol 1.2`.
Output: 1080×1920, 30fps, H.264/AAC, length of the clip.

## Ground rules
- These clips belong to their creators. Always show the credit (the playlist and `--credit` do
  this), add real commentary/reaction (that's what makes it transformative), and use short
  excerpts rather than whole streams. Remove anything a creator asks you to take down.
- Downloading from Instagram goes against its Terms of Use. Keep volumes low and use your own account.
- Vice City footage you record yourself is fine to post; Rockstar allows gameplay videos that aren't
  just raw cutscene dumps.
