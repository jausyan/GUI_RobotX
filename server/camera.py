"""Camera image controls (v4l2) and capture modes - the GUI version of ~/RobotX/script/camera_setup.sh."""
import json
import os
import re
import subprocess
import time
from pathlib import Path

DEVICE = os.environ.get("CAMERA_DEVICE", "/dev/video0")
SAVED = Path(os.environ.get("CAMERA_SETTINGS", Path(__file__).parent / "camera_settings.json"))

# order matters (same as camera_setup.sh): switch an AUTO mode off BEFORE setting its manual value
APPLY_ORDER = ["focus_automatic_continuous", "focus_absolute", "auto_exposure", "exposure_dynamic_framerate",
               "exposure_time_absolute", "white_balance_automatic", "white_balance_temperature", "gain",
               "power_line_frequency", "backlight_compensation", "brightness", "contrast", "saturation",
               "sharpness", "zoom_absolute", "pan_absolute", "tilt_absolute"]
NAME_RE = re.compile(r"^[a-z0-9_]+$")


def _v4l2(*args, timeout=6):
    r = subprocess.run(["v4l2-ctl", "-d", DEVICE, *args], capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr)


def camera_users(device=DEVICE):
    """Names of processes that hold the camera open (a recording needs it free)."""
    out = []
    for p in Path("/proc").glob("[0-9]*"):
        try:
            if any(str(f.resolve()) == device for f in (p / "fd").iterdir() if f.is_symlink()):
                out.append((p / "comm").read_text().strip())
        except (OSError, PermissionError):
            continue
    return sorted(set(out))


def list_controls():
    rc, text = _v4l2("--list-ctrls-menus")
    if rc != 0:
        return []
    ctrls, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^\s*(\w+)\s+0x[0-9a-f]+\s+\((\w+)\)\s*:\s*(.*)$", line)
        if m:
            name, typ, rest = m.groups()
            kv = dict(re.findall(r"(\w+)=(-?\d+)", rest))
            cur = {"name": name, "type": typ, "min": int(kv.get("min", 0)), "max": int(kv.get("max", 1)),
                   "step": int(kv.get("step", 1)), "default": int(kv.get("default", 0)),
                   "value": int(kv.get("value", 0)), "inactive": "inactive" in rest, "menu": []}
            if typ == "bool":
                cur["min"], cur["max"] = 0, 1
            ctrls.append(cur)
            continue
        m = re.match(r"^\s+(\d+):\s+(.+)$", line)
        if m and cur is not None and cur["type"] == "menu":
            cur["menu"].append({"value": int(m.group(1)), "label": m.group(2).strip()})
    return ctrls


def list_modes():
    rc, text = _v4l2("--list-formats-ext")
    modes, fmt, size = {}, None, None
    for line in text.splitlines():
        m = re.search(r"\[\d+\]: '(\w{4})'", line)
        if m:
            fmt = m.group(1)
            modes[fmt] = {}
            continue
        m = re.search(r"Size: Discrete (\d+)x(\d+)", line)
        if m and fmt:
            size = (int(m.group(1)), int(m.group(2)))
            modes[fmt][size] = []
            continue
        m = re.search(r"\(([\d.]+) fps\)", line)
        if m and fmt and size:
            modes[fmt][size].append(round(float(m.group(1)), 1))
    return [{"fourcc": f, "sizes": [{"width": w, "height": h, "fps": fps} for (w, h), fps in s.items()]}
            for f, s in modes.items()]


def apply_controls(values):
    """values: {control_name: int}. Returns [{name, value, ok, error}] (a control the camera lacks is skipped)."""
    have = {c["name"]: c for c in list_controls()}
    names = [n for n in APPLY_ORDER if n in values] + [n for n in values if n not in APPLY_ORDER]
    results = []
    for n in names:
        if not NAME_RE.match(n) or n not in have:
            results.append({"name": n, "ok": False, "error": "not on this camera"})
            continue
        c = have[n]
        v = max(c["min"], min(c["max"], int(values[n])))
        rc, out = _v4l2(f"--set-ctrl={n}={v}")
        results.append({"name": n, "value": v, "ok": rc == 0, "error": None if rc == 0 else out.strip()[:120]})
    return results


def preset_script(ctrls=None):
    """The values camera_setup.sh uses (daylight, ~20 m, downward camera). Gain is a % of the camera's range."""
    ctrls = {c["name"]: c for c in (ctrls or list_controls())}
    g = ctrls.get("gain")
    gain = g["min"] + (g["max"] - g["min"]) * 25 // 100 if g else 0
    return {"focus_automatic_continuous": 0, "focus_absolute": 0, "auto_exposure": 3,
            "exposure_dynamic_framerate": 0, "exposure_time_absolute": 60, "gain": gain,
            "white_balance_automatic": 0, "white_balance_temperature": 5000, "power_line_frequency": 1,
            "backlight_compensation": 0}


def preset_defaults(ctrls=None):
    return {c["name"]: c["default"] for c in (ctrls or list_controls())}


def load_saved():
    try:
        return json.loads(SAVED.read_text())
    except (OSError, ValueError):
        return {}


def save(**parts):
    data = load_saved()
    data.update(parts)
    SAVED.write_text(json.dumps(data, indent=2))
    return data


def get_mode():
    return load_saved().get("mode") or {"fourcc": "MJPG", "width": 640, "height": 480, "fps": 30}


# ---- saved config: persisted on the robot, re-applied when the API starts and before a vision node starts ----
def save_current():
    """Remember what the camera is set to right now (image controls)."""
    ctrls = {c["name"]: c["value"] for c in list_controls() if c["name"] in APPLY_ORDER}
    return save(controls=ctrls, saved_at=time.time())


def saved_controls():
    return load_saved().get("controls") or {}


def restore_saved():
    values = saved_controls()
    return apply_controls(values) if values else []


def saved_info(ctrls=None):
    """What is saved, and which controls currently differ on the camera (inactive ones are ignored)."""
    saved = saved_controls()
    ctrls = {c["name"]: c for c in (ctrls or list_controls())}
    differs = [n for n, v in saved.items() if n in ctrls and not ctrls[n]["inactive"] and ctrls[n]["value"] != v]
    return {"saved_at": load_saved().get("saved_at"), "controls": saved, "differs": differs}
