"""UDP/RTP H.264 -> MJPEG relay.

The vision nodes (vision_geo, vision_video) send H.264 over RTP to udp://<stream_host>:5000.
Browsers cannot read that, so a gst-launch child process listens on that port, decodes it and
writes JPEG frames to stdout. We split the frames and serve them at GET /video
(multipart/x-mixed-replace), which a plain <img> tag can display.

The relay listens all the time; no frames simply means "no signal". Point the vision node's
stream_host at this machine (services.yaml does that with -p stream_host:=127.0.0.1).
"""
import asyncio
import ctypes
import os
import shlex
import signal
import time
from collections import deque

PORT = int(os.environ.get("VIDEO_PORT", 5000))
WIDTH = int(os.environ.get("VIDEO_WIDTH", 0))     # 0 = keep the size the vision node sends
HEIGHT = int(os.environ.get("VIDEO_HEIGHT", 0))
FPS = int(os.environ.get("VIDEO_FPS", 30))        # upper limit; the vision node's stream_fps still applies
QUALITY = int(os.environ.get("VIDEO_QUALITY", 70))
LIVE_AFTER_S = 2.5          # no frame for this long -> "no signal"
SOI, EOI = b"\xff\xd8", b"\xff\xd9"
BOUNDARY = "frame"

_SIZE = f",width={WIDTH},height={HEIGHT}" if WIDTH and HEIGHT else ""
PIPELINE = (
    f'gst-launch-1.0 -q udpsrc port={PORT} '
    f'caps="application/x-rtp,media=video,clock-rate=90000,encoding-name=H264,payload=96" '
    f'! rtph264depay ! h264parse ! avdec_h264 ! videoconvert ! videoscale ! videorate '
    f'! video/x-raw{_SIZE},framerate={FPS}/1 '
    f'! jpegenc quality={QUALITY} ! fdsink fd=1 sync=false'
)


def split_jpegs(buf):
    """Cut complete JPEG images out of a byte stream. Returns (frames, leftover)."""
    frames = []
    while True:
        start = buf.find(SOI)
        if start < 0:
            return frames, b""
        end = buf.find(EOI, start + 2)
        if end < 0:
            return frames, buf[start:]
        frames.append(buf[start:end + 2])
        buf = buf[end + 2:]


def jpeg_size(jpeg):
    """(width, height) from the JPEG start-of-frame marker, or None."""
    i = 2
    while i + 9 < len(jpeg):
        if jpeg[i] != 0xFF:
            return None
        marker = jpeg[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            return (jpeg[i + 7] << 8 | jpeg[i + 8], jpeg[i + 5] << 8 | jpeg[i + 6])
        i += 2 + (jpeg[i + 2] << 8 | jpeg[i + 3])
    return None


def _die_with_parent():
    """Child gets SIGTERM if the API dies (even by kill -9) so it never keeps the UDP port bound."""
    ctypes.CDLL("libc.so.6").prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG


class VideoRelay:
    def __init__(self):
        self.frame = None
        self.seq = 0
        self.last_frame_at = 0.0
        self.size = None
        self._stamps = deque(maxlen=60)
        self._cond = None
        self._proc = None
        self._task = None
        self._stopping = False
        self.log = deque(maxlen=30)

    # ---- lifecycle -------------------------------------------------------------------
    def start(self):
        self._cond = asyncio.Condition()
        self._task = asyncio.create_task(self._supervise())

    async def stop(self):
        self._stopping = True
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
        if self._task:
            self._task.cancel()

    async def _supervise(self):
        while not self._stopping:
            try:
                await self._run_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - keep the relay alive
                self.log.append(f"relay error: {e!r}")
            await asyncio.sleep(2)

    async def _run_once(self):
        self._proc = await asyncio.create_subprocess_exec(
            *shlex.split(PIPELINE), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            preexec_fn=_die_with_parent)
        self.log.append(f"gst started pid {self._proc.pid} on udp:{PORT}")
        asyncio.create_task(self._drain_stderr(self._proc))
        buf = b""
        while True:
            chunk = await self._proc.stdout.read(65536)
            if not chunk:
                break
            frames, buf = split_jpegs(buf + chunk)
            for f in frames:
                await self.publish(f)
        code = await self._proc.wait()
        self.log.append(f"gst exited ({code})")

    async def _drain_stderr(self, proc):
        async for line in proc.stderr:
            self.log.append(line.decode(errors="replace").rstrip())

    async def publish(self, jpeg):
        now = time.monotonic()
        self.frame = jpeg
        if self.seq == 0 or self.seq % 150 == 0:
            self.size = jpeg_size(jpeg) or self.size
        self.seq += 1
        self.last_frame_at = now
        self._stamps.append(now)
        async with self._cond:
            self._cond.notify_all()

    # ---- consumers ---------------------------------------------------------------------
    def stats(self):
        now = time.monotonic()
        live = self.frame is not None and now - self.last_frame_at < LIVE_AFTER_S
        recent = [t for t in self._stamps if now - t < 2.0]
        fps = round((len(recent) - 1) / (recent[-1] - recent[0]), 1) if len(recent) > 2 else 0.0
        return {"live": live, "fps": fps if live else 0.0, "width": self.size[0] if self.size else None,
                "height": self.size[1] if self.size else None,
                "age": round(now - self.last_frame_at, 2) if self.frame else None}

    async def stream(self):
        """Async generator of multipart/x-mixed-replace parts for one HTTP client."""
        seen = 0
        while True:
            async with self._cond:
                if self.seq == seen:
                    try:
                        await asyncio.wait_for(self._cond.wait(), 5)
                    except asyncio.TimeoutError:
                        continue
            frame, seen = self.frame, self.seq
            if frame is None:
                continue
            yield (f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(frame)}\r\n\r\n"
                   ).encode() + frame + b"\r\n"
