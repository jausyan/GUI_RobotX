"""Dataset recorder. Runs record_worker.py (the same pipeline as ~/RobotX/script/record_video.py:
camera -> optional undistortion with the vision_video calibration), which writes an H.264 MP4 - or JPEG
stills every N seconds - using the saved camera mode (resolution / fps / format). Its preview goes to the
same web camera window.

The camera can only be opened by one program, so the vision nodes must be stopped first."""
import asyncio
import ctypes
import json
import os
import re
import shutil
import signal
import sys
import time
import zipfile
from pathlib import Path

import camera
from video import split_jpegs

BASE = Path(os.environ.get("RECORDINGS_DIR", Path(__file__).parent.parent / "recordings"))
ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,80}$")


def _die_with_parent():
    """If the API dies (even kill -9) the worker gets SIGINT, which makes it close the MP4 properly."""
    ctypes.CDLL("libc.so.6").prctl(1, signal.SIGINT)


WORKER = Path(__file__).with_name("record_worker.py")
CALIB = Path(os.environ.get("VISION_VIDEO_CONFIG", "~/RobotX/install/vision_video/share/vision_video/config/vision_video.yaml")).expanduser()


def build_command(mode, kind, out_dir, stamp, interval, quality, undistort):
    cmd = [sys.executable, str(WORKER), "--device", camera.DEVICE, "--out-dir", str(out_dir), "--stamp", stamp,
           "--kind", kind, "--fourcc", mode["fourcc"], "--width", str(mode["width"]), "--height", str(mode["height"]),
           "--fps", str(mode["fps"]), "--interval", str(interval), "--quality", quality,
           "--undistort", "1" if undistort else "0", "--calib", str(CALIB)]
    if os.environ.get("RECORDER_SYNTHETIC"):          # tests only: no camera needed
        cmd.append("--synthetic")
    return cmd


class Recorder:
    def __init__(self, relay):
        self.relay = relay
        self.proc = None
        self.session = None   # {"id","kind","dir","started","mode","interval"}
        self.error = None
        self.warning = None
        self.log = []

    # ---- control -------------------------------------------------------------------------
    def busy_users(self):
        return camera.camera_users()

    async def start(self, kind, name, interval=1.0, quality="balanced", undistort=True):
        if self.proc and self.proc.returncode is None:
            raise RuntimeError("already recording")
        if kind not in ("video", "frames"):
            raise ValueError("kind must be 'video' or 'frames'")
        if quality not in ("high", "balanced", "small"):
            raise ValueError("quality must be high, balanced or small")
        name = re.sub(r"[^A-Za-z0-9_\-]", "_", (name or "").strip())[:40] or "dataset"
        users = self.busy_users()
        if users and not os.environ.get("RECORDER_SYNTHETIC"):
            raise RuntimeError(f"camera is in use by: {', '.join(users)} - stop it first (e.g. the Vision service)")
        mode = camera.get_mode()
        stamp = time.strftime("%Y%m%d_%H%M%S")
        sid = f"{name}-{stamp}"
        out = BASE / sid
        out.mkdir(parents=True, exist_ok=False)
        controls = {c["name"]: c["value"] for c in camera.list_controls()}
        meta = {"id": sid, "kind": kind, "started": time.time(), "mode": mode, "controls": controls,
                "interval_s": interval if kind == "frames" else None, "quality": quality if kind == "video" else None,
                "undistort_requested": bool(undistort), "format": "mp4 (H.264)" if kind == "video" else "jpeg"}
        (out / "meta.json").write_text(json.dumps(meta, indent=2))
        self.error, self.warning, self.log = None, None, []
        self.proc = await asyncio.create_subprocess_exec(
            *build_command(mode, kind, out, stamp, interval, quality, undistort),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, preexec_fn=_die_with_parent)
        self.session = {"id": sid, "kind": kind, "dir": out, "started": time.time(), "mode": mode, "interval": interval}
        asyncio.create_task(self._pump_preview(self.proc))
        asyncio.create_task(self._pump_stderr(self.proc))
        await asyncio.sleep(2.5)           # catch "device busy" / bad mode right away
        if self.proc.returncode is not None:
            err = self.error or " ".join(self.log[-3:]) or f"worker exited ({self.proc.returncode})"
            shutil.rmtree(out, ignore_errors=True)
            self.session = None
            raise RuntimeError(f"could not start recording: {err}")
        return self.status()

    async def stop(self):
        proc, sess = self.proc, self.session
        if proc and proc.returncode is None:
            proc.send_signal(signal.SIGINT)    # gst-launch -e: finish the file cleanly (EOS)
            try:
                await asyncio.wait_for(proc.wait(), 20)
            except asyncio.TimeoutError:
                proc.terminate()
                await proc.wait()
        if sess:
            self._finish_meta(sess)
        self.session = None
        return self.status()

    # ---- background readers ---------------------------------------------------------------
    async def _pump_preview(self, proc):
        buf = b""
        while True:
            chunk = await proc.stdout.read(65536)
            if not chunk:
                break
            frames, buf = split_jpegs(buf + chunk)
            for f in frames:
                await self.relay.publish(f)

    async def _pump_stderr(self, proc):
        async for line in proc.stderr:
            self.log.append(line.decode(errors="replace").rstrip())
            self.log = self.log[-20:]
            if "[error]" in self.log[-1].lower() or "busy" in self.log[-1].lower():
                self.error = self.log[-1][:160]
            if "[warn]" in self.log[-1].lower():
                self.warning = self.log[-1][7:].strip()[:160]

    def _finish_meta(self, sess):
        try:
            mp = sess["dir"] / "meta.json"
            meta = json.loads(mp.read_text())
            meta["ended"] = time.time()
            meta["duration_s"] = round(meta["ended"] - meta["started"], 1)
            meta["frames"] = len(list(sess["dir"].glob("frame_*.jpg"))) if sess["kind"] == "frames" else None
            mp.write_text(json.dumps(meta, indent=2))
        except (OSError, ValueError):
            pass

    # ---- status / library ------------------------------------------------------------------
    def status(self):
        rec = bool(self.proc and self.proc.returncode is None and self.session)
        if not rec:
            return {"recording": False, "error": self.error}
        s = self.session
        d = s["dir"]
        size = sum(f.stat().st_size for f in d.iterdir() if f.is_file())
        frames = len(list(d.glob("frame_*.jpg"))) if s["kind"] == "frames" else None
        return {"recording": True, "id": s["id"], "kind": s["kind"], "elapsed": round(time.time() - s["started"], 1),
                "size": size, "frames": frames, "mode": s["mode"], "warning": self.warning}

    @staticmethod
    def library():
        out = []
        for d in sorted(BASE.glob("*"), reverse=True) if BASE.exists() else []:
            if not d.is_dir():
                continue
            try:
                meta = json.loads((d / "meta.json").read_text())
            except (OSError, ValueError):
                meta = {}
            size = sum(f.stat().st_size for f in d.iterdir() if f.is_file())
            kind = meta.get("kind") or ("video" if Recorder.video_file(d) else "frames")
            out.append({"id": d.name, "kind": kind, "size": size, "mode": meta.get("mode"),
                        "duration_s": meta.get("duration_s"), "started": meta.get("started"),
                        "frames": len(list(d.glob("frame_*.jpg"))) if kind == "frames" else None})
        return out

    @staticmethod
    def video_file(d):
        return next(iter(sorted(d.glob("*.mp4")) + sorted(d.glob("*.mkv"))), None)

    @staticmethod
    def path_of(sid):
        if not ID_RE.match(sid):
            return None
        d = BASE / sid
        return d if d.is_dir() and d.resolve().parent == BASE.resolve() else None

    @staticmethod
    def make_zip(d):
        tmp = BASE / f".{d.name}.zip"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
            for f in sorted(d.iterdir()):
                if f.is_file():
                    z.write(f, f"{d.name}/{f.name}")
        return tmp
