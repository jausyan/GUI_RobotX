"""Mission / inter-vehicle topics (rx_msgs). Read-only view of what the UAV bridge exchanges
with the GCS and the other vehicles."""
import threading
import time
from collections import deque

try:
    from rclpy.qos import QoSDurabilityPolicy, QoSProfile
    from std_msgs.msg import String, UInt8
    from rx_msgs.msg import Command, Course, Heartbeat, MissionStatus, SafePassage
    MISSION_OK = True
except ImportError:  # rx_msgs not sourced -> mission panel just stays empty
    MISSION_OK = False

COMMAND_NAMES = {1: "RUN_START", 2: "DELIVERY", 3: "TASK4_ASSISTANCE", 4: "TASK4_KEEP_OUT_ZONE",
                 5: "TASK4_ALL_CLEAR", 6: "TASK4_MOVING_OBJECT", 7: "TASK4_READINESS_CONFIRM",
                 8: "GO", 9: "MISSION_DONE"}
VEHICLES = {"uav": 3, "usv": 1, "uuv": 2}   # name -> rx_msgs/VehicleType
TARGET_NAMES = {0: "ALL", 1: "USV", 2: "UUV", 3: "UAV"}
COLORS = {1: "RED", 2: "GREEN", 3: "BLUE", 4: "ANY"}


class Mission:
    def __init__(self):
        self._lock = threading.Lock()
        self.status = {}        # vehicle_id -> dict (+ stamp)
        self.heartbeats = {}    # uav/usv/uuv -> dict (+ stamp)
        self.course = None
        self.safe_passage = None
        self.current_task = None
        self.events = deque(maxlen=40)
        self._seen_cmds = set()
        self._last_order = None

    # ---- helpers --------------------------------------------------------------
    def _event(self, kind, text):
        self.events.append({"t": time.time(), "kind": kind, "text": text})

    @staticmethod
    def _ll(p):
        return [p.latitude, p.longitude]

    # ---- callbacks (called from the rclpy thread) ---------------------------------
    def on_status(self, m):
        with self._lock:
            old = self.status.get(m.vehicle_id)
            self.status[m.vehicle_id] = {"run_id": m.run_id, "state": m.state, "task": m.current_task,
                                         "message": m.message, "stamp": time.monotonic()}
            if old is None or (old["state"], old["task"], old["message"]) != (m.state, m.current_task, m.message):
                self._event("status", f"{m.vehicle_id}: state {m.state} task {m.current_task} {m.message}".strip())

    def on_command(self, m):
        key = (m.command_seq, m.command_type)
        with self._lock:
            if key in self._seen_cmds:
                return
            self._seen_cmds.add(key)
            name = COMMAND_NAMES.get(m.command_type, str(m.command_type))
            extra = ""
            if m.command_type == 1:
                extra = f" run {m.run_id}"
            elif m.command_type == 2:
                extra = f" {COLORS.get(m.resource_color, '?')} -> {COLORS.get(m.delivery_circle_color, '?')}"
            self._event("command", f"CMD {name}{extra} -> {TARGET_NAMES.get(m.target_vehicle, '?')} (seq {m.command_seq})")

    def on_course(self, m):
        with self._lock:
            new = {"id": m.course_id, "pinger_hz": m.pinger_freq_hz,
                   "boundary": [self._ll(p) for p in m.boundary],
                   "geofence": [self._ll(p) for p in m.uav_geofence]}
            changed = new != self.course
            self.course = new
            if changed:
                self._event("course", f"Course {m.course_id}: boundary {len(m.boundary)} pts, geofence {len(m.uav_geofence)} pts")

    def make_heartbeat_cb(self, name):
        def cb(m):
            with self._lock:
                self.heartbeats[name] = {
                    "state": m.state, "lat": m.position.latitude, "lon": m.position.longitude,
                    "speed": m.spd_mps, "heading": m.heading_deg, "alt": m.altitude_hae_m,
                    "depth": m.depth_m, "task": m.current_task, "flight_phase": m.flight_phase,
                    "stamp": time.monotonic()}
        return cb

    def on_safe_passage(self, m):
        with self._lock:
            self.safe_passage = {"entry": self._ll(m.entry_position), "exit": self._ll(m.exit_position),
                                 "buoys": [{"pos": self._ll(b.position), "state": b.state} for b in m.buoys],
                                 "stamp": time.monotonic()}

    def on_order(self, m):
        with self._lock:
            # the bridge re-sends an order every second until it is ACKed -> log it once
            now = time.monotonic()
            if self._last_order and self._last_order[0] == m.data and now - self._last_order[1] < 15:
                self._last_order = (m.data, now)
                return
            self._last_order = (m.data, now)
            self._event("order", f"order: {m.data}")

    def on_task(self, m):
        with self._lock:
            if m.data != self.current_task:
                self.current_task = m.data
                self._event("task", f"current_task -> {m.data}")

    # ---- wiring -----------------------------------------------------------------------
    def attach(self, node):
        if not MISSION_OK:
            return
        latched = QoSProfile(depth=1, durability=QoSDurabilityPolicy.TRANSIENT_LOCAL)
        node.create_subscription(MissionStatus, "/system/mission/status", self.on_status, 10)
        node.create_subscription(Command, "/system/mission/command", self.on_command, 10)
        node.create_subscription(Course, "/system/mission/course", self.on_course, latched)
        for name in VEHICLES:
            node.create_subscription(Heartbeat, f"/system/vehicle/{name}/heartbeat",
                                     self.make_heartbeat_cb(name), 10)
        node.create_subscription(SafePassage, "/system/vehicle/uav/task1/safe_passage", self.on_safe_passage, 10)
        node.create_subscription(String, "/mission/order", self.on_order, 10)
        node.create_subscription(UInt8, "/mission/current_task", self.on_task, latched)

    def snapshot(self):
        now = time.monotonic()
        with self._lock:
            out = {
                "ok": MISSION_OK,
                "status": {k: {**{a: b for a, b in v.items() if a != "stamp"}, "age": round(now - v["stamp"], 2)}
                           for k, v in self.status.items()},
                "heartbeats": {k: {**{a: b for a, b in v.items() if a != "stamp"}, "age": round(now - v["stamp"], 2)}
                               for k, v in self.heartbeats.items()},
                "course": self.course,
                "current_task": self.current_task,
                "safe_passage": ({**{a: b for a, b in self.safe_passage.items() if a != "stamp"},
                                  "age": round(now - self.safe_passage["stamp"], 2)} if self.safe_passage else None),
                "events": list(self.events)[-25:],
            }
        return out
