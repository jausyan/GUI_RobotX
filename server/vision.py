"""Buoy map from vision_geo: every /vision_geo/map/<name> topic (DetectedObjectArray) is one
buoy class (buoy_entry, buoy_exit, buoy_red, ...). New classes show up automatically."""
import threading
import time

try:
    from vision_msgs.msg import DetectedObjectArray
    VISION_OK = True
except ImportError:
    VISION_OK = False

PREFIX = "/vision_geo/map/"
TYPE = "vision_msgs/msg/DetectedObjectArray"


class Vision:
    def __init__(self):
        self._lock = threading.Lock()
        self.groups = {}   # name -> {"objects": [...], "stamp": monotonic}
        self._subs = {}

    def _make_cb(self, name):
        def cb(m):
            objs = [{"id": o.class_id, "lat": o.latitude, "lon": o.longitude,
                     "conf": round(float(o.confidence), 2),
                     "north": float(o.north_offset_m), "east": float(o.east_offset_m)}
                    for o in m.objects]
            with self._lock:
                self.groups[name] = {"objects": objs, "stamp": time.monotonic()}
        return cb

    def discover(self, node, topics):
        """topics: {name: [types]} from node.get_topic_names_and_types()."""
        if not VISION_OK:
            return
        for topic, types in topics.items():
            if topic.startswith(PREFIX) and TYPE in types and topic not in self._subs:
                name = topic[len(PREFIX):]
                self._subs[topic] = node.create_subscription(DetectedObjectArray, topic, self._make_cb(name), 10)

    def snapshot(self):
        now = time.monotonic()
        with self._lock:
            return {"ok": VISION_OK,
                    "groups": {n: {"objects": g["objects"], "age": round(now - g["stamp"], 2)}
                               for n, g in self.groups.items()}}
