#!/usr/bin/env python3
"""Reaction Studio: viral clip -> highlights -> Vice City reaction setup.

Subcommands
  fetch      download reels/live replays from a URL list (yt-dlp)
  highlights auto-cut the loudest moments of each video into short clips
  playlist   write playlist.json for player.html (live OBS playback)
  compose    stack clip + your gameplay (+ facecam) into a 1080x1920 reel
"""
import argparse, json, re, shutil, subprocess, sys
from pathlib import Path

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm"}


def need(tool):
    if not shutil.which(tool):
        sys.exit(f"'{tool}' not found on PATH. Install it first (see README).")


def run(cmd):
    print("$", " ".join(map(str, cmd)))
    subprocess.run(cmd, check=True)


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def videos(folder):
    return sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in VIDEO_EXT)


# ---------------------------------------------------------------- fetch
def cmd_fetch(a):
    need("yt-dlp")
    urls = [u.strip() for u in Path(a.urls).read_text().splitlines()
            if u.strip() and not u.startswith("#")]
    Path(a.out).mkdir(parents=True, exist_ok=True)
    cmd = ["yt-dlp", "-f", "mp4/bestvideo*+bestaudio/best", "--merge-output-format", "mp4",
           "-o", f"{a.out}/%(uploader)s_%(id)s.%(ext)s",
           "--write-info-json", "--no-overwrites", "--sleep-interval", "3"]
    if a.cookies_from_browser:
        cmd += ["--cookies-from-browser", a.cookies_from_browser]
    run(cmd + urls)


# ---------------------------------------------------------------- highlights
def loudness_curve(path):
    """Per-second momentary loudness (LUFS) via ffmpeg ebur128 metadata."""
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn",
                        "-af", "ebur128=metadata=1,ametadata=print:key=lavfi.r128.M",
                        "-f", "null", "-"], capture_output=True, text=True)
    per_sec, t = {}, None
    for line in p.stderr.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            t = float(m.group(1)); continue
        m = re.search(r"lavfi\.r128\.M=(-?[\d.]+)", line)
        if m and t is not None:
            s = int(t)
            per_sec[s] = max(per_sec.get(s, -120.0), float(m.group(1)))
    return per_sec


def pick_peaks(curve, total, n, length):
    """Highest-scoring non-overlapping windows of `length` seconds."""
    if not curve:  # silent / no audio: evenly spaced
        step = max(total / (n + 1), 0)
        return [max(0, step * (i + 1) - length / 2) for i in range(n)]
    secs = range(0, max(1, int(total - length) + 1))
    score = {s: sum(curve.get(s + k, -120) for k in range(int(length))) for s in secs}
    chosen = []
    for s in sorted(score, key=score.get, reverse=True):
        if all(abs(s - c) >= length for c in chosen):
            chosen.append(s)
        if len(chosen) == n:
            break
    return sorted(chosen)


def cmd_highlights(a):
    need("ffmpeg")
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    for src in videos(a.src):
        total = duration(src)
        length = min(a.length, total)
        starts = pick_peaks(loudness_curve(src), total, a.count, length)
        for i, st in enumerate(starts, 1):
            dst = out / f"{src.stem}_hl{i}.mp4"
            # pre-roll so the build-up is kept before the peak
            ss = max(0, st - a.preroll)
            run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{ss:.2f}",
                 "-i", str(src), "-t", f"{length:.2f}", "-c:v", "libx264", "-preset", "veryfast",
                 "-crf", "20", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(dst)])
    print(f"Highlights written to {out}/")


# ---------------------------------------------------------------- playlist
def cmd_playlist(a):
    folder = Path(a.clips)
    items = []
    for v in videos(folder):
        info = folder / (v.stem.split("_hl")[0] + ".info.json")
        credit = ""
        for cand in (info, Path(a.raw) / info.name if a.raw else None):
            if cand and cand.exists():
                d = json.loads(cand.read_text())
                credit = "@" + (d.get("uploader_id") or d.get("uploader") or "")
                break
        items.append({"src": f"{folder.name}/{v.name}", "credit": credit})
    Path(a.out).write_text(json.dumps(items, indent=2))
    print(f"{len(items)} clips -> {a.out}")


# ---------------------------------------------------------------- compose
def cmd_compose(a):
    need("ffmpeg")
    W, H = 1080, 1920
    top_h = int(H * a.split)
    bot_h = H - top_h
    clip_len = duration(a.clip)
    inputs = ["-i", a.clip, "-ss", str(a.game_start), "-i", a.gameplay]
    f = [
        f"[0:v]scale={W}:{top_h}:force_original_aspect_ratio=increase,crop={W}:{top_h},setsar=1[top]",
        f"[1:v]scale={W}:{bot_h}:force_original_aspect_ratio=increase,crop={W}:{bot_h},setsar=1[bot]",
        "[top][bot]vstack=inputs=2[stk]",
    ]
    last = "stk"
    if a.facecam:
        inputs += ["-ss", str(a.cam_start), "-i", a.facecam]
        cw = int(W * 0.32) // 2 * 2
        f += [f"[2:v]crop='min(iw,ih)':'min(iw,ih)',scale={cw}:{cw},format=yuva420p,"
              f"geq=lum='p(X,Y)':a='if(lt(hypot(X-{cw}/2,Y-{cw}/2),{cw}/2-2),255,0)'[cam]",
              f"[{last}][cam]overlay=W-w-30:{top_h}-h/2[withcam]"]
        last = "withcam"
    if a.credit:
        txt = a.credit.replace(":", r"\:").replace("'", "")
        f.append(f"[{last}]drawtext=text='{txt}':x=30:y={top_h}-60:fontsize=38:fontcolor=white:"
                 f"box=1:boxcolor=black@0.55:boxborderw=12[txt]")
        last = "txt"
    # audio: clip + gameplay (ducked) + facecam mic
    a_in = ["[0:a]volume=1.0[a0]", f"[1:a]volume={a.game_vol}[a1]"]
    mix = "[a0][a1]"
    n = 2
    if a.facecam:
        a_in.append(f"[2:a]volume={a.cam_vol}[a2]"); mix += "[a2]"; n += 1
    f += a_in + [f"{mix}amix=inputs={n}:duration=first:normalize=0[aout]"]
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs,
         "-filter_complex", ";".join(f), "-map", f"[{last}]", "-map", "[aout]",
         "-t", f"{clip_len:.2f}", "-r", "30", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", a.out])
    print(f"Reel -> {a.out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)

    p = sp.add_parser("fetch"); p.set_defaults(fn=cmd_fetch)
    p.add_argument("--urls", default="urls.txt"); p.add_argument("--out", default="raw")
    p.add_argument("--cookies-from-browser", help="chrome|firefox|edge — needed for most Instagram links")

    p = sp.add_parser("highlights"); p.set_defaults(fn=cmd_highlights)
    p.add_argument("--src", default="raw"); p.add_argument("--out", default="clips")
    p.add_argument("--count", type=int, default=3, help="clips per video")
    p.add_argument("--length", type=float, default=20, help="seconds per clip")
    p.add_argument("--preroll", type=float, default=3, help="seconds kept before the peak")

    p = sp.add_parser("playlist"); p.set_defaults(fn=cmd_playlist)
    p.add_argument("--clips", default="clips"); p.add_argument("--raw", default="raw")
    p.add_argument("--out", default="playlist.json")

    p = sp.add_parser("compose"); p.set_defaults(fn=cmd_compose)
    p.add_argument("--clip", required=True); p.add_argument("--gameplay", required=True)
    p.add_argument("--facecam"); p.add_argument("--out", default="reel.mp4")
    p.add_argument("--game-start", type=float, default=0); p.add_argument("--cam-start", type=float, default=0)
    p.add_argument("--split", type=float, default=0.5, help="share of height for the clip (0-1)")
    p.add_argument("--game-vol", type=float, default=0.25); p.add_argument("--cam-vol", type=float, default=1.2)
    p.add_argument("--credit", help="on-screen credit, e.g. '@creator'")

    a = ap.parse_args(); a.fn(a)


if __name__ == "__main__":
    main()
