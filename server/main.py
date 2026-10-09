"""RobotX mission-control API. Run: ./run_server.sh"""
import asyncio
import os
import socket
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask

import camera
import gcs
from process_manager import ProcessManager
from recorder import Recorder
from telemetry import Telemetry
from video import BOUNDARY, VideoRelay

HERE = Path(__file__).parent
pm = ProcessManager(Path(os.environ.get("SERVICES_FILE", HERE / "services.yaml")))
telem = Telemetry()
relay = VideoRelay()
rec = Recorder(relay)


@asynccontextmanager
async def lifespan(app):
    relay.start()
    try:
        await asyncio.to_thread(camera.restore_saved)      # saved camera config back on after a reboot / replug
    except Exception:  # noqa: BLE001 - no camera must not stop the API
        pass
    yield
    await rec.stop()
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
async def start(name: str, body: dict | None = Body(default=None)):
    s = _svc(name)
    fmt = detail = None
    if s.needs == "gcs":
        p = gcs.get((body or {}).get("gcs") or "")
        if not p:
            raise HTTPException(400, "choose a GCS profile")
        fmt, detail = {"gcs_url": gcs.gcs_url(p)}, f"GCS {p['name']} · {p['ip']}:{p['port']}"
        gcs.set_last(p["id"])
    if s.uses_camera:
        await asyncio.to_thread(camera.restore_saved)
    await s.start(fmt, detail)
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
    return {**telem.snapshot(), "video": relay.stats(), "recorder": rec.status()}


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


# ---- GCS profiles (where MAVROS forwards MAVLink) ------------------------------------------------
@app.get("/gcs/profiles")
def gcs_list():
    return gcs.listing()


@app.post("/gcs/profiles")
def gcs_add(body: dict = Body(...)):
    try:
        return gcs.add(body.get("name"), body.get("ip"), body.get("port", 14550))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.put("/gcs/profiles/{pid}")
def gcs_update(pid: str, body: dict = Body(...)):
    try:
        p = gcs.update(pid, body.get("name"), body.get("ip"), body.get("port", 14550))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not p:
        raise HTTPException(404, "no such profile")
    return p


@app.delete("/gcs/profiles/{pid}")
def gcs_delete(pid: str):
    if not gcs.remove(pid):
        raise HTTPException(404, "no such profile")
    return {"deleted": pid}


# ---- camera settings (GUI version of script/camera_setup.sh) ---------------------------------------
@app.get("/camera")
def camera_info():
    ctrls = camera.list_controls()
    return {"device": camera.DEVICE, "users": camera.camera_users(), "controls": ctrls, "modes": camera.list_modes(),
            "mode": camera.get_mode(), "presets": ["script", "defaults"], "saved": camera.saved_info(ctrls)}


@app.post("/camera/controls")
def camera_controls(body: dict = Body(...)):
    values = {k: int(v) for k, v in (body.get("controls") or {}).items()}
    results = camera.apply_controls(values)
    return {"results": results, "controls": camera.list_controls(), "saved": camera.saved_info()}


@app.post("/camera/preset/{name}")
def camera_preset(name: str):
    ctrls = camera.list_controls()
    if name == "script":
        values = camera.preset_script(ctrls)
    elif name == "defaults":
        values = camera.preset_defaults(ctrls)
    else:
        raise HTTPException(404, "unknown preset")
    results = camera.apply_controls(values)
    return {"results": results, "controls": camera.list_controls(), "saved": camera.saved_info()}


@app.post("/camera/save")
def camera_save():
    """Persist the camera's current image settings (re-applied on API start and before Vision starts)."""
    camera.save_current()
    return {"saved": camera.saved_info()}


@app.post("/camera/restore")
def camera_restore():
    results = camera.restore_saved()
    return {"results": results, "controls": camera.list_controls(), "saved": camera.saved_info()}


@app.post("/camera/mode")
def camera_mode(body: dict = Body(...)):
    try:
        mode = {"fourcc": str(body["fourcc"]), "width": int(body["width"]), "height": int(body["height"]), "fps": int(body["fps"])}
    except (KeyError, ValueError):
        raise HTTPException(400, "fourcc, width, height and fps are required")
    ok = any(m["fourcc"] == mode["fourcc"] and any(s["width"] == mode["width"] and s["height"] == mode["height"]
             for s in m["sizes"]) for m in camera.list_modes())
    if not ok:
        raise HTTPException(400, "the camera does not offer that mode")
    camera.save(mode=mode)
    return mode


# ---- dataset recording ------------------------------------------------------------------------------
@app.post("/record/start")
async def record_start(body: dict = Body(...)):
    try:
        return await rec.start(body.get("kind", "video"), body.get("name", ""), float(body.get("interval", 1.0)),
                               body.get("quality", "balanced"), bool(body.get("undistort", True)))
    except (ValueError, RuntimeError) as e:
        raise HTTPException(409, str(e))


@app.post("/record/stop")
async def record_stop():
    return await rec.stop()


@app.get("/recordings")
def recordings():
    return rec.library()


@app.get("/recordings/{sid}/download")
def recording_download(sid: str):
    d = rec.path_of(sid)
    if not d:
        raise HTTPException(404, "no such recording")
    video = rec.video_file(d)
    if video:
        return FileResponse(video, filename=video.name, media_type="video/mp4" if video.suffix == ".mp4" else "video/x-matroska")
    z = rec.make_zip(d)
    return FileResponse(z, filename=f"{sid}.zip", media_type="application/zip", background=BackgroundTask(z.unlink))


@app.delete("/recordings/{sid}")
def recording_delete(sid: str):
    d = rec.path_of(sid)
    if not d or (rec.session and rec.session["id"] == sid):
        raise HTTPException(404, "no such recording (or it is still recording)")
    import shutil
    shutil.rmtree(d)
    return {"deleted": sid}
