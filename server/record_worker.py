#!/usr/bin/env python3
"""Recording worker, started by recorder.py. Same pipeline as ~/RobotX/script/record_video.py:

  camera (V4L2) -> optional undistortion with the vision_video calibration -> file

but the video is written as H.264 inside an MP4 (a few MB per minute) instead of MJPG/AVI, and
JPEG preview frames go to stdout so the web camera window keeps showing the picture.
Frames mode saves a JPEG every N seconds instead of a video.

stdout = preview JPEGs only. Everything human-readable goes to stderr.
"""
import argparse
import signal
import sys
import time
from pathlib import Path

import cv2
import numpy as np

# vision_video.yaml camera_matrix / distortion_coeffs were calibrated at this size (same as record_video.py)
CALIB_SIZE = (640, 480)
FALLBACK_K = [[504.99132615, 0.0, 318.4012728], [0.0, 506.13168687, 243.99035432], [0.0, 0.0, 1.0]]
FALLBACK_D = [0.07771398, -0.18711237, -0.00182709, 0.00026326, -0.06212367]
QUANTIZER = {"high": 20, "balanced": 24, "small": 28}   # x264 constant quality (lower = bigger, better)


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def load_calibration(path):
    try:
        import yaml
        p = yaml.safe_load(open(path))["vision_video_node"]["ros__parameters"]
        return (np.array(p["camera_matrix"], np.float64).reshape(3, 3), np.array(p["distortion_coeffs"], np.float64),
                f"vision_video.yaml")
    except Exception as e:  # noqa: BLE001
        log(f"[WARN] calibration file not usable ({e}); using the values from record_video.py")
        return np.array(FALLBACK_K, np.float64), np.array(FALLBACK_D, np.float64), "record_video.py constants"


def open_camera(a):
    cap = cv2.VideoCapture(a.device, cv2.CAP_V4L2)
    if not cap.isOpened():
        log(f"[ERROR] Cannot open camera: {a.device}")
        sys.exit(1)
    if a.fourcc:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*a.fourcc))
    if a.width and a.height:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, a.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, a.height)
    if a.fps:
        cap.set(cv2.CAP_PROP_FPS, a.fps)
    return cap


def synthetic_source(a):
    """Dev/test only: a moving ball + noise instead of a camera (--synthetic)."""
    rng = np.random.default_rng(1)
    t = [0]
    class Cap:
        def isOpened(self): return True
        def get(self, prop): return {cv2.CAP_PROP_FRAME_WIDTH: a.width, cv2.CAP_PROP_FRAME_HEIGHT: a.height, cv2.CAP_PROP_FPS: a.fps}.get(prop, 0)
        def read(self):
            time.sleep(1.0 / a.fps)
            f = np.full((a.height, a.width, 3), (90, 100, 110), np.uint8)
            f = cv2.add(f, rng.integers(0, 12, f.shape, dtype=np.uint8))
            t[0] += 1
            cv2.circle(f, (60 + (t[0] * 7) % (a.width - 120), a.height // 2), 40, (40, 200, 240), -1)
            return True, f
        def release(self): pass
    return Cap()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="/dev/video0")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--stamp", required=True, help="timestamp used in the file name")
    ap.add_argument("--kind", choices=["video", "frames"], default="video")
    ap.add_argument("--fourcc", default="MJPG")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--interval", type=float, default=1.0, help="frames mode: seconds between stills")
    ap.add_argument("--quality", choices=list(QUANTIZER), default="balanced")
    ap.add_argument("--undistort", type=int, default=1)
    ap.add_argument("--calib", default="")
    ap.add_argument("--synthetic", action="store_true")
    a = ap.parse_args()

    cap = synthetic_source(a) if a.synthetic else open_camera(a)
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = int(round(cap.get(cv2.CAP_PROP_FPS) or a.fps or 30))
    log(f"[INFO] Device       : {a.device}  ({w}x{h} @ {fps} fps, {a.fourcc})")

    # undistortion maps, computed once (alpha=0: no black borders) - exactly like record_video.py
    map1 = map2 = None
    if a.undistort and (w, h) == CALIB_SIZE:
        K, D, src = load_calibration(a.calib)
        new_K, _ = cv2.getOptimalNewCameraMatrix(K, D, (w, h), alpha=0, newImgSize=(w, h))
        map1, map2 = cv2.initUndistortRectifyMap(K, D, None, new_K, (w, h), cv2.CV_16SC2)
        log(f"[INFO] Undistort    : ON  (calibration from {src})")
    elif a.undistort:
        log(f"[WARN] Undistort    : OFF - the calibration is for {CALIB_SIZE[0]}x{CALIB_SIZE[1]}, this mode is {w}x{h}")
    else:
        log("[INFO] Undistort    : OFF  (raw frames)")

    # x264 wants even sizes and 4-byte aligned rows
    ow, oh = w - w % 4, h - h % 2
    out_dir = Path(a.out_dir)
    writer = None
    if a.kind == "video":
        out = out_dir / f"recording_{a.stamp}.mp4"
        pipe = (f"appsrc is-live=true do-timestamp=true format=time ! "
                f"video/x-raw,format=BGR,width={ow},height={oh},framerate={fps}/1 ! videoconvert ! "
                f"x264enc speed-preset=veryfast pass=qual quantizer={QUANTIZER[a.quality]} key-int-max={fps * 2} ! "
                f"h264parse ! mp4mux fragment-duration=2000 ! filesink location={out}")
        writer = cv2.VideoWriter(pipe, cv2.CAP_GSTREAMER, 0, float(fps), (ow, oh), True)
        if not writer.isOpened():
            log("[ERROR] Cannot open the MP4 writer (OpenCV needs GStreamer with x264enc + mp4mux).")
            sys.exit(1)
        log(f"[INFO] Output       : {out}  (H.264, {a.quality})")
    else:
        log(f"[INFO] Output       : {out_dir}/frame_XXXXXX.jpg every {a.interval}s")

    running = [True]
    def stop(*_): running[0] = False
    signal.signal(signal.SIGINT, stop)       # the API sends SIGINT (also when it dies) -> finish the file cleanly
    signal.signal(signal.SIGTERM, stop)

    for _ in range(0 if a.synthetic else 5):   # let auto-exposure settle, skip the camera's first (sometimes blank) frames
        cap.read()
    frames = saved = dropped = 0
    last_prev = last_still = 0.0
    log("[INFO] Recording ...")
    while running[0]:
        ok, frame = cap.read()
        if not ok or frame is None:
            dropped += 1
            if dropped > 30:
                log("[ERROR] Too many dropped frames - camera lost.")
                break
            time.sleep(0.01)
            continue
        dropped = 0
        if map1 is not None:
            frame = cv2.remap(frame, map1, map2, interpolation=cv2.INTER_LINEAR)
        if (ow, oh) != (w, h):
            frame = frame[:oh, :ow]
        now = time.time()
        if writer is not None:
            writer.write(frame)
            frames += 1
        elif now - last_still >= a.interval:
            cv2.imwrite(str(out_dir / f"frame_{saved:06d}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
            saved += 1
            last_still = now
        if now - last_prev >= 0.1:                      # ~10 fps preview for the web GUI
            last_prev = now
            prev = frame if ow <= 640 else cv2.resize(frame, (640, int(oh * 640 / ow)))
            okp, buf = cv2.imencode(".jpg", prev, [cv2.IMWRITE_JPEG_QUALITY, 60])
            if okp:
                try:
                    sys.stdout.buffer.write(buf.tobytes())
                    sys.stdout.buffer.flush()
                except BrokenPipeError:
                    break
    cap.release()
    if writer is not None:
        writer.release()                                # EOS -> closes the MP4
    log(f"[INFO] Done: {frames or saved} {'frames' if frames else 'stills'}")


if __name__ == "__main__":
    main()
