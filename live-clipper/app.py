#!/usr/bin/env python3
"""Live Clipper: a web command console for clipping YouTube live streams and VODs.

Run:  python app.py            -> http://localhost:8080
Env:  PORT, CLIPPER_PASSCODE (required to clip when set), YTDLP (yt-dlp binary),
      COOKIES_FROM_BROWSER (chrome|firefox|edge; helps when YouTube asks to sign in)
Needs yt-dlp and ffmpeg on PATH.
"""
import json, math, os, re, shlex, subprocess, threading, time, urllib.parse, urllib.request, uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLIPS = ROOT / "clips"; CLIPS.mkdir(exist_ok=True)
YTDLP = os.environ.get("YTDLP", "yt-dlp")
PASS = os.environ.get("CLIPPER_PASSCODE", "")
COOKIES = os.environ.get("COOKIES_FROM_BROWSER", "")
JOBS, LOCK = {}, threading.Lock()
YT = re.compile(r"^https?://(www\.|m\.)?(youtube\.com|youtu\.be)/")


def ytdlp(*args):
    cmd = shlex.split(YTDLP) + (["--cookies-from-browser", COOKIES] if COOKIES else []) + list(args)
    return cmd


def peaks(heatmap, n=5, gap=20):
    """Top 'most replayed' moments, non-overlapping."""
    out = []
    for h in sorted(heatmap or [], key=lambda h: h["value"], reverse=True):
        mid = (h["start_time"] + h["end_time"]) / 2
        if all(abs(mid - p["t"]) > gap for p in out):
            out.append({"t": round(mid, 1), "score": round(h["value"], 3)})
        if len(out) == n:
            break
    return sorted(out, key=lambda p: p["t"])


def info(url):
    p = subprocess.run(ytdlp("-J", "--no-warnings", "--skip-download", url),
                       capture_output=True, text=True, timeout=90)
    if p.returncode:
        raise RuntimeError(p.stderr.strip().splitlines()[-1] if p.stderr.strip() else "yt-dlp failed")
    d = json.loads(p.stdout)
    return {"id": d.get("id"), "title": d.get("title"), "channel": d.get("channel") or d.get("uploader"),
            "is_live": bool(d.get("is_live")), "duration": d.get("duration"),
            "peaks": peaks(d.get("heatmap"))}


# ------------------------------------------------------------------ jobs
def log(job, msg):
    with LOCK:
        job["log"].append(msg); job["log"] = job["log"][-40:]


def run(job, cmd):
    log(job, "$ " + " ".join(cmd)[:300])
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in p.stdout:
        line = line.strip()
        if line:
            log(job, line[-200:])
    if p.wait():
        raise RuntimeError(f"{Path(cmd[0]).name} exited with {p.returncode}")


def target_duration(m3u8):
    try:
        with urllib.request.urlopen(m3u8, timeout=20) as r:
            text = r.read().decode("utf-8", "ignore")
        if "#EXT-X-STREAM-INF" in text:  # master playlist -> first variant
            variant = next(l for l in text.splitlines() if l and not l.startswith("#"))
            return target_duration(urllib.parse.urljoin(m3u8, variant))
        m = re.search(r"#EXT-X-TARGETDURATION:(\d+)", text)
        return max(1, int(m.group(1))) if m else 2
    except Exception:
        return 2


def clip_live_tail(job, url, seconds, behind, out):
    """Grab the last `seconds` of a live stream (ending `behind` seconds before the live edge)."""
    p = subprocess.run(ytdlp("-g", "-f", "b[protocol^=m3u8]/bv*[protocol^=m3u8]+ba/b", url),
                       capture_output=True, text=True, timeout=90)
    urls = [u for u in p.stdout.split() if u.startswith("http")]
    if not urls:
        raise RuntimeError("Could not get the live stream URL: " + p.stderr.strip()[-200:])
    td = target_duration(urls[0])
    idx = math.ceil((seconds + behind) / td) + 1
    log(job, f"segment length {td}s, starting {idx} segments behind the live edge")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", "-live_start_index", f"-{idx}", "-i", urls[0]]
    if len(urls) > 1:
        cmd += ["-live_start_index", f"-{idx}", "-i", urls[1], "-map", "0:v:0", "-map", "1:a:0"]
    run(job, cmd + ["-t", str(seconds), "-c", "copy", "-movflags", "+faststart", str(out)])


def clip_range(job, url, start, end, live, out):
    tmpl = str(out.with_suffix("")) + ".%(ext)s"
    cmd = ytdlp("--no-warnings", "--newline", "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
                "--download-sections", f"*{start}-{end}", "--force-keyframes-at-cuts",
                "--merge-output-format", "mp4", "-o", tmpl, url)
    if live:
        cmd.insert(-1, "--live-from-start")
    run(job, cmd)
    got = sorted(out.parent.glob(out.stem + ".*"), key=lambda p: p.stat().st_mtime)
    if not got:
        raise RuntimeError("No file was produced")
    if got[-1] != out:
        got[-1].rename(out)


def make_vertical(job, src):
    dst = src.with_name(src.stem + "_9x16.mp4")
    vf = ("[0:v]split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
          "boxblur=30:5,eq=brightness=-0.12[bg];[b]scale=1080:-2[fg];[bg][fg]overlay=0:(H-h)/2")
    run(job, ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", "-i", str(src), "-filter_complex", vf,
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
              "-movflags", "+faststart", str(dst)])
    return dst


def worker(job, req):
    try:
        job["status"] = "running"
        out = CLIPS / f"{job['id']}.mp4"
        if req["mode"] == "last":
            clip_live_tail(job, req["url"], req["seconds"], req.get("behind", 0), out)
        else:
            clip_range(job, req["url"], req["start"], req["end"], req.get("live", False), out)
        job["files"] = [out.name]
        if req.get("vertical"):
            job["files"].append(make_vertical(job, out).name)
        job["status"] = "done"
    except Exception as e:
        job["status"] = "error"; log(job, f"ERROR: {e}")


def new_job(req):
    if not YT.match(req.get("url", "")) and not os.environ.get("CLIPPER_ALLOW_ANY_URL"):
        raise ValueError("Only YouTube links are supported")
    if req["mode"] == "last":
        req["seconds"] = max(3, min(float(req.get("seconds", 30)), 600))
        req["behind"] = max(0, float(req.get("behind", 0)))
        label = f"last {req['seconds']:.0f}s" + (f" ({req['behind']:.0f}s behind live)" if req["behind"] else "")
    else:
        req["start"], req["end"] = float(req["start"]), float(req["end"])
        if not 0 <= req["start"] < req["end"] or req["end"] - req["start"] > 600:
            raise ValueError("Clip must have start < end and be at most 10 minutes")
        label = f"{req['start']:.1f}s to {req['end']:.1f}s"
    job = {"id": time.strftime("%H%M%S") + "_" + uuid.uuid4().hex[:5], "label": label,
           "title": req.get("title", ""), "status": "queued", "log": [], "files": [], "created": time.time()}
    with LOCK:
        JOBS[job["id"]] = job
    threading.Thread(target=worker, args=(job, req), daemon=True).start()
    return job


# ------------------------------------------------------------------ http
class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def log_message(self, *a):
        pass

    def authed(self):
        return not PASS or self.headers.get("X-Passcode") == PASS

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            return self._send(200, (ROOT / "static/index.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/api/config":
            return self._send(200, {"passcode_required": bool(PASS)})
        if path == "/api/jobs":
            if not self.authed():
                return self._send(401, {"error": "Wrong passcode"})
            with LOCK:
                jobs = sorted(JOBS.values(), key=lambda j: -j["created"])
                return self._send(200, [dict(j, log=j["log"][-6:]) for j in jobs])
        if path.startswith("/clips/"):
            f = CLIPS / Path(path).name
            if f.exists() and f.suffix == ".mp4":
                self.send_response(200); self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(f.stat().st_size))
                self.send_header("Content-Disposition", f'inline; filename="{f.name}"'); self.end_headers()
                with f.open("rb") as fh:
                    while chunk := fh.read(1 << 16):
                        self.wfile.write(chunk)
                return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self.authed():
            return self._send(401, {"error": "Wrong passcode"})
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or "{}")
            if self.path == "/api/info":
                if not YT.match(req.get("url", "")) and not os.environ.get("CLIPPER_ALLOW_ANY_URL"):
                    raise ValueError("Only YouTube links are supported")
                return self._send(200, info(req["url"]))
            if self.path == "/api/clip":
                return self._send(200, new_job(req))
        except Exception as e:
            return self._send(400, {"error": str(e)})
        self._send(404, {"error": "not found"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Live Clipper on http://localhost:{port}" + ("  (passcode on)" if PASS else ""))
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
