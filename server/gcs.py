"""Ground-station (GCS) profiles for MAVROS: who/where MAVLink is forwarded to (gcs_url)."""
import json
import re
import uuid
from pathlib import Path

FILE = Path(__file__).parent / "gcs_profiles.json"
HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.\-]{0,251}[A-Za-z0-9])?$")   # ip or hostname - ends up in a shell command


def _load():
    try:
        return json.loads(FILE.read_text())
    except (OSError, ValueError):
        return {"profiles": [], "last": None}


def _save(d):
    FILE.write_text(json.dumps(d, indent=2))


def validate(name, ip, port):
    name = (name or "").strip()
    ip = (ip or "").strip()
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise ValueError("port must be a number")
    if not name or len(name) > 60:
        raise ValueError("name is required (max 60 characters)")
    if not HOST_RE.match(ip):
        raise ValueError("ip must be an IP address or hostname")
    if not 1 <= port <= 65535:
        raise ValueError("port must be 1-65535")
    return name, ip, port


def listing():
    return _load()


def get(pid):
    return next((p for p in _load()["profiles"] if p["id"] == pid), None)


def add(name, ip, port=14550):
    name, ip, port = validate(name, ip, port)
    d = _load()
    p = {"id": uuid.uuid4().hex[:8], "name": name, "ip": ip, "port": port}
    d["profiles"].append(p)
    _save(d)
    return p


def update(pid, name, ip, port=14550):
    name, ip, port = validate(name, ip, port)
    d = _load()
    for p in d["profiles"]:
        if p["id"] == pid:
            p.update(name=name, ip=ip, port=port)
            _save(d)
            return p
    return None


def remove(pid):
    d = _load()
    n = len(d["profiles"])
    d["profiles"] = [p for p in d["profiles"] if p["id"] != pid]
    if d.get("last") == pid:
        d["last"] = None
    _save(d)
    return len(d["profiles"]) < n


def set_last(pid):
    d = _load()
    d["last"] = pid
    _save(d)


def gcs_url(p):
    name, ip, port = validate(p["name"], p["ip"], p["port"])   # re-check: this goes into a shell command
    return f"udp://@{ip}:{port}"
