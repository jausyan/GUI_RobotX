"""Start/stop whitelisted services as child processes and keep their logs."""
import asyncio
import os
import signal
import time
from collections import deque
from pathlib import Path

import yaml


class Service:
    def __init__(self, name, cfg, ros_setup, domain_id):
        self.name = name
        self.label = cfg.get("label", name)
        self.cmd = cfg["cmd"]
        self.source = cfg.get("source")
        self.uses_camera = bool(cfg.get("camera"))   # the saved camera config is applied before it starts
        self.needs = cfg.get("needs")      # e.g. "gcs": the GUI must supply a GCS profile to start
        self.detail = None                 # what it was started with, shown in the GUI
        self.ros_setup = ros_setup
        self.domain_id = domain_id
        self.proc = None
        self.started_at = None
        self.exit_code = None
        self.stopping = False
        self.logs = deque(maxlen=500)
        self.subscribers = set()  # asyncio.Queue per log websocket

    @property
    def state(self):
        if self.proc is None:
            return "stopped"
        if self.proc.returncode is None:
            return "stopping" if self.stopping else "running"
        return "stopped" if self.stopping or self.exit_code == 0 else "crashed"

    def info(self):
        running = self.proc is not None and self.proc.returncode is None
        return {
            "name": self.name,
            "label": self.label,
            "state": self.state,
            "pid": self.proc.pid if running else None,
            "uptime": round(time.time() - self.started_at, 1) if running else None,
            "exit_code": self.exit_code,
            "needs": self.needs,
            "detail": self.detail if running else None,
        }

    def _emit(self, line):
        self.logs.append(line)
        for q in list(self.subscribers):
            q.put_nowait(line)

    async def start(self, fmt=None, detail=None):
        if self.state in ("running", "stopping"):
            return
        cmd = self.cmd.format(**fmt) if fmt else self.cmd
        self.detail = detail
        parts = [f"source {self.ros_setup}"]
        if self.source:
            parts.append(f"source {os.path.expanduser(self.source)}")
        parts.append(f"exec {cmd}")
        env = {**os.environ, "ROS_DOMAIN_ID": str(self.domain_id), "PYTHONUNBUFFERED": "1"}
        self.stopping = False
        self.exit_code = None
        self.proc = await asyncio.create_subprocess_exec(
            "bash", "-c", "; ".join(parts),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            env=env, start_new_session=True,  # own process group -> clean kill
        )
        self.started_at = time.time()
        self._emit(f"[gui] started pid {self.proc.pid}")
        asyncio.create_task(self._pump())

    async def _pump(self):
        proc = self.proc
        async for raw in proc.stdout:
            self._emit(raw.decode(errors="replace").rstrip())
        self.exit_code = await proc.wait()
        self._emit(f"[gui] exited with code {self.exit_code}")

    async def stop(self):
        proc = self.proc
        if proc is None or proc.returncode is not None:
            return
        self.stopping = True
        pgid = os.getpgid(proc.pid)
        for sig, wait in ((signal.SIGINT, 5), (signal.SIGTERM, 3), (signal.SIGKILL, 2)):
            try:
                os.killpg(pgid, sig)
            except ProcessLookupError:
                return
            try:
                await asyncio.wait_for(proc.wait(), wait)
                return
            except asyncio.TimeoutError:
                continue


class ProcessManager:
    def __init__(self, config_path: Path):
        cfg = yaml.safe_load(config_path.read_text())
        self.services = {
            name: Service(name, c, cfg["ros_setup"], cfg.get("ros_domain_id", 0))
            for name, c in cfg["services"].items()
        }

    def get(self, name):
        return self.services.get(name)

    def list(self):
        return [s.info() for s in self.services.values()]

    async def stop_all(self):
        await asyncio.gather(*(s.stop() for s in self.services.values()))
