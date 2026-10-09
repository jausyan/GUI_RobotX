"""RobotX mission-control API. Run: ./run_server.sh"""
import asyncio
import os
import socket
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from process_manager import ProcessManager
from telemetry import Telemetry
from video import BOUNDARY, VideoRelay

HERE = Path(__file__).parent
pm = ProcessManager(Path(os.environ.get("SERVICES_FILE", HERE / "services.yaml")))
telem = Telemetry()
relay = VideoRelay()


@asynccontextmanager
async def lifespan(app):
    relay.start()
    yield
    await relay.stop()
    await pm.stop_all()  # don't orphan child nodes when the API exits


app = FastAPI(title="RobotX API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return {"app": "robotx-api", "version": "0.1.0", "name": socket.gethostname(), "ros": telem.ros_ok}


@app.get("/services")
def list_services():
    return pm.list()


def _svc(name):
    s = pm.get(name)
    if not s:
        raise HTTPException(404, f"unknown service '{name}'")
    return s


@app.post("/services/{name}/start")
async def start(name: str):
    s = _svc(name)
    await s.start()
    return s.info()


@app.post("/services/{name}/stop")
async def stop(name: str):
    s = _svc(name)
    await s.stop()
    return s.info()


@app.post("/services/stop-all")
async def stop_all():
    await pm.stop_all()
    return pm.list()


# Orders the simulation panel may publish on /mission/order (whitelist, same strings the bridge sends)
SIM_ORDERS = {"RUN-START", "UAV-GO", "MISSION-DONE"}


@app.post("/simulate/{order}")
def simulate(order: str):
    if order not in SIM_ORDERS:
        raise HTTPException(400, f"order must be one of {sorted(SIM_ORDERS)}")
    if not telem.publish_order(order):
        raise HTTPException(503, "ROS publisher not ready")
    return {"sent": order, "t": time.time()}


def snapshot():
    return {**telem.snapshot(), "video": relay.stats()}


@app.get("/telemetry")
def telemetry():
    return snapshot()


@app.get("/video")
async def video():
    """MJPEG feed of the vision stream (works in a plain <img> tag)."""
    return StreamingResponse(relay.stream(), media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
                             headers={"Cache-Control": "no-store"})


@app.get("/video/log")
def video_log():
    return list(relay.log)


@app.websocket("/ws/telemetry")
async def ws_telemetry(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            await ws.send_json(snapshot())
            await asyncio.sleep(0.2)  # 5 Hz
    except (WebSocketDisconnect, RuntimeError):
        pass


@app.websocket("/ws/logs/{name}")
async def ws_logs(ws: WebSocket, name: str):
    s = pm.get(name)
    await ws.accept()
    if not s:
        await ws.close(code=4404)
        return
    q = asyncio.Queue()
    for line in s.logs:
        await ws.send_text(line)
    s.subscribers.add(q)
    try:
        while True:
            await ws.send_text(await q.get())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        s.subscribers.discard(q)
