"""ROS 2 subscriber thread that keeps the latest MAVROS telemetry in a dict."""
import math
import threading
import time

from mission import Mission
from vision import Vision

try:
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import (QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy,
                           qos_profile_sensor_data)
    from mavros_msgs.msg import State, VfrHud
    from std_msgs.msg import String
    from sensor_msgs.msg import BatteryState, NavSatFix, Range
    from geometry_msgs.msg import PoseStamped
    ROS_OK = True
except ImportError:  # server still runs (GUI shows "no data") without ROS
    ROS_OK = False


def yaw_deg(q):
    siny = 2 * (q.w * q.z + q.x * q.y)
    cosy = 1 - 2 * (q.y * q.y + q.z * q.z)
    return (math.degrees(math.atan2(siny, cosy)) + 360) % 360


def _finite(v):
    """NaN / inf are not valid JSON (the browser's JSON.parse rejects them) -> null."""
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {k: _finite(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_finite(x) for x in v]
    return v


class Telemetry:
    def __init__(self):
        self.data = {"state": None, "gps": None, "pose": None, "battery": None, "hud": None, "range": None}
        self.stamps = {}  # key -> monotonic time of last message
        self._lock = threading.Lock()
        self.ros_ok = ROS_OK
        self.topics = {}  # suffix -> discovered topic name
        self.mission = Mission()
        self.vision = Vision()
        self._order_pub = None
        if ROS_OK:
            threading.Thread(target=self._spin, daemon=True).start()

    def publish_order(self, text):
        """Publish a mission order string on /mission/order (same topic the GCS bridge uses)."""
        if self._order_pub is None:
            return False
        self._order_pub.publish(String(data=text))
        return True

    def _set(self, key, value):
        with self._lock:
            self.data[key] = value
            self.stamps[key] = time.monotonic()

    def snapshot(self):
        now = time.monotonic()
        with self._lock:
            out = dict(self.data)
            out["age"] = {k: round(now - t, 2) for k, t in self.stamps.items()}
        out["ros"] = self.ros_ok
        out["topics"] = dict(self.topics)
        out["mission"] = self.mission.snapshot()
        out["vision"] = self.vision.snapshot()
        out["t"] = time.time()
        return _finite(out)

    def _spin(self):
        rclpy.init()
        node = Node("robotx_gui_telemetry")
        state_qos = QoSProfile(depth=1, reliability=QoSReliabilityPolicy.RELIABLE,
                               durability=QoSDurabilityPolicy.TRANSIENT_LOCAL)

        def on_state(m):
            self._set("state", {"connected": m.connected, "armed": m.armed,
                                "guided": m.guided, "mode": m.mode,
                                "system_status": m.system_status})

        def on_gps(m):
            self._set("gps", {"lat": m.latitude, "lon": m.longitude, "alt": m.altitude,
                              "fix": m.status.status})

        def on_pose(m):
            p, q = m.pose.position, m.pose.orientation
            self._set("pose", {"x": p.x, "y": p.y, "z": p.z, "yaw": yaw_deg(q)})

        def on_batt(m):
            pct = None if math.isnan(m.percentage) else m.percentage * 100
            self._set("battery", {"voltage": m.voltage, "current": m.current, "percent": pct})

        def on_hud(m):
            self._set("hud", {"airspeed": m.airspeed, "groundspeed": m.groundspeed,
                              "heading": m.heading, "throttle": m.throttle, "alt": m.altitude})

        def on_range(m):
            self._set("range", {"range": m.range, "min": m.min_range, "max": m.max_range})

        # (type, topic suffix, callback, qos). Topics are found by type + suffix so any
        # MAVROS namespace works (/mavros/..., /rian/..., ...).
        wanted = [
            ("mavros_msgs/msg/State", "/state", State, on_state, state_qos),
            ("sensor_msgs/msg/NavSatFix", "/global_position/global", NavSatFix, on_gps, qos_profile_sensor_data),
            ("geometry_msgs/msg/PoseStamped", "/local_position/pose", PoseStamped, on_pose, qos_profile_sensor_data),
            ("sensor_msgs/msg/BatteryState", "/battery", BatteryState, on_batt, qos_profile_sensor_data),
            ("mavros_msgs/msg/VfrHud", "/vfr_hud", VfrHud, on_hud, qos_profile_sensor_data),
            ("sensor_msgs/msg/Range", "/rangefinder/rangefinder", Range, on_range, qos_profile_sensor_data),
        ]
        subs = {}  # suffix -> (topic name, subscription)

        def discover():
            found = dict(node.get_topic_names_and_types())
            self.vision.discover(node, found)
            for type_name, suffix, msg, cb, qos in wanted:
                names = sorted((n for n, types in found.items()
                                if type_name in types and n.endswith(suffix)), key=lambda n: (len(n), n))
                if not names:
                    continue
                if suffix in subs and subs[suffix][0] == names[0]:
                    continue
                if suffix in subs:
                    node.destroy_subscription(subs[suffix][1])
                subs[suffix] = (names[0], node.create_subscription(msg, names[0], cb, qos))
                self.topics[suffix] = names[0]

        self.mission.attach(node)
        self._order_pub = node.create_publisher(String, "/mission/order", 10)
        node.create_timer(2.0, discover)
        discover()
        rclpy.spin(node)
