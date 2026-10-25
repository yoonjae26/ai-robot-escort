#!/usr/bin/env python3
"""Robot measurements -> StepMap live server (stepmap live, port 8060), in StepMap's events.csv format.

  source ~/terrain_dataset/env.sh
  python3 stepmap_bridge.py --ros-args -p session:=20261026_yeondong_A [-p server:=http://127.0.0.1:8060]
  (stepmap_live.sh starts the live server and this bridge together)

Sources (all optional; whatever is running is used):
  /terrain_geometry/slope (terrain_geometry_node.py, JSON)
      slope  every slope_every_m travelled: median of the OK estimates since the last one. value = |longitudinal|
             slope [deg], cross slope in the note (StepMap has one slope kind). Place = robot + middle of the ROI ahead.
      step   each confirmed step (>= confirm_n views): |dz| [cm] at robot + step distance ahead. Seeing the same step
             again (same 0.5 m cell) updates it, keeping the closest view.
  logs/inspect/<session>/state.json (inspect_node.py): sunken / raised tiles and holes -> step [cm] with the snapshot.
  /utlidar/robot_odom: trajectory (every 0.5 s when moving) and the robot pose for placing measurements.
  /dev/shm/auto_recorder.json: battery for the dashboard robot card.
Camera results are placed on the ground where the problem is (StepMap phase_b_checklist 3), not at the robot.

Delivery: every item is first appended to <spool>/outbox.jsonl (fsync), then a sender thread posts it to the server
in order and stores how far it got (sent.txt). If the server is down or the robot restarts, it resumes from there,
so nothing measured is lost. The live server itself replicates to the laptop (stepmap live --pull).
"""
import json
import math
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import rclpy
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from std_msgs.msg import String

HOME = Path.home()


class Outbox:
    """Append-only item log on disk + a sender thread that posts unsent items in order."""

    def __init__(self, folder, server, log):
        self.dir = Path(folder)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path, self.cursor = self.dir / "outbox.jsonl", self.dir / "sent.txt"
        self.server, self.log = server.rstrip("/"), log
        self.lock = threading.Lock()
        self.n = sum(1 for _ in open(self.path, encoding="utf-8")) if self.path.exists() else 0
        self.sent = int(self.cursor.read_text()) if self.cursor.exists() else 0
        self.ok = None
        threading.Thread(target=self._run, daemon=True).start()

    def put(self, item, file_bytes=None):
        """file_bytes: a picture to upload before the item (item["row"]["image"] is its path)."""
        with self.lock:
            if file_bytes is not None:
                rel = item["row"]["image"]
                p = self.dir / "files" / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(file_bytes)
                item = {**item, "_file": rel}
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            self.n += 1

    def _post(self, url, data, ctype):
        req = urllib.request.Request(url, data, {"Content-Type": ctype}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))

    def _run(self):
        while True:
            try:
                with self.lock:
                    pending = self.n - self.sent
                if pending <= 0:
                    time.sleep(0.3)
                    continue
                with open(self.path, encoding="utf-8") as f:
                    lines = [ln for i, ln in enumerate(f) if self.sent <= i < self.sent + 200]
                items = [json.loads(ln) for ln in lines]
                for it in items:                           # pictures first, so the dashboard can show them
                    if "_file" in it:
                        data = (self.dir / "files" / it["_file"]).read_bytes()
                        self._post(f"{self.server}/api/file?path={urllib.request.quote(it['_file'])}", data,
                                   "application/octet-stream")
                payload = [{k: v for k, v in it.items() if k != "_file"} for it in items]
                res = self._post(f"{self.server}/api/ingest", json.dumps({"items": payload}).encode("utf-8"),
                                 "application/json")
                if res.get("errors"):
                    self.log.warn("server rejected: %s" % res["errors"][:3])
                self.sent += len(items)
                self.cursor.write_text(str(self.sent))
                if self.ok is not True:
                    self.log.info("server %s ok, %d item(s) sent" % (self.server, self.sent))
                    self.ok = True
            except (urllib.error.URLError, OSError, ValueError) as e:
                if self.ok is not False:
                    self.log.warn("server %s unreachable (%s); items wait in %s" % (self.server, e, self.path))
                    self.ok = False
                time.sleep(2.0)


class Bridge(Node):
    def __init__(self):
        super().__init__("stepmap_bridge")
        P = self.declare_parameter
        self.session = P("session", time.strftime("%Y%m%d_%H%M%S")).value
        server = P("server", "http://127.0.0.1:8060").value
        spool = P("spool", str(HOME / "stepmap_sessions" / self.session / "bridge")).value
        self.slope_every = P("slope_every_m", 2.0).value
        self.inspect_dir = Path(P("inspect_dir", str(HOME / "terrain_dataset" / "logs" / "inspect")).value)
        self.inspect_session = P("inspect_session", "").value   # empty: the newest one written after the bridge start
        self.out = Outbox(spool, server, self.get_logger())
        self.pose = None                                         # (x, y, yaw)
        self.last_traj = (0.0, None)
        self.slope_buf, self.slope_from, self.n_slope = [], None, 0
        self.n_ok = self.n_all = 0
        self.steps = {}                                          # 0.5 m cell -> (dist, key)
        self.inspect_seen = {}                                   # event id -> (h_mm, snap mtime)
        self.t_start = time.time()
        self.battery = None
        self.run = time.strftime("%H%M%S")                       # slope keys stay unique after a bridge restart
        self.create_subscription(Odometry, P("odom_topic", "/utlidar/robot_odom").value, self.on_odom,
                                 qos_profile_sensor_data)
        self.create_subscription(String, "/terrain_geometry/slope", self.on_slope, 10)
        self.create_timer(1.0, self.on_timer)
        self.get_logger().info("session %s -> %s (spool %s)" % (self.session, server, spool))

    # ---- helpers ----
    def ahead(self, dist):
        x, y, yaw = self.pose
        return x + dist * math.cos(yaw), y + dist * math.sin(yaw)

    def event(self, key, kind, value, unit, x, y, confidence, note="", image="", file_bytes=None):
        row = {"t": round(time.time(), 2), "session": self.session, "x": round(x, 3), "y": round(y, 3),
               "kind": kind, "value": round(value, 2), "unit": unit, "source": "camera", "leg": "",
               "confidence": round(min(1.0, max(0.0, confidence)), 2), "image": image, "note": note}
        self.out.put({"type": "event", "key": key, "row": row}, file_bytes)

    # ---- callbacks ----
    def on_odom(self, m):
        p, q = m.pose.pose.position, m.pose.pose.orientation
        yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
        self.pose = (p.x, p.y, yaw)
        now = time.time()
        t_last, xy_last = self.last_traj
        moved = xy_last is None or math.hypot(p.x - xy_last[0], p.y - xy_last[1]) >= 0.1
        if (moved and now - t_last >= 0.5) or now - t_last >= 5.0:
            self.last_traj = (now, (p.x, p.y))
            self.out.put({"type": "traj", "row": {"t": round(now, 2), "x": round(p.x, 3), "y": round(p.y, 3)}})

    def on_slope(self, msg):
        if self.pose is None:
            return
        r = json.loads(msg.data)
        self.n_all += 1
        if r.get("status") == "OK" and r.get("along_deg") is not None:
            self.n_ok += 1
            roi = r.get("roi_x") or [0.3, 2.0]
            self.slope_buf.append((r["along_deg"], r.get("side_deg") or 0.0, (roi[0] + roi[1]) / 2))
        if self.slope_from is None:
            self.slope_from = self.pose[:2]
        if math.hypot(self.pose[0] - self.slope_from[0], self.pose[1] - self.slope_from[1]) >= self.slope_every:
            if len(self.slope_buf) >= 5:
                a = np.array(self.slope_buf)
                along, side, mid = np.median(a[:, 0]), np.median(a[:, 1]), np.median(a[:, 2])
                x, y = self.ahead(mid)
                self.n_slope += 1
                self.event("slope:%s:%d" % (self.run, self.n_slope), "slope", abs(along), "deg", x, y, self.n_ok / max(1, self.n_all),
                           "종단 %+.1f° · 횡단 %+.1f° (카메라 %d회 중앙값)" % (along, side, len(a)))
            self.slope_buf, self.slope_from, self.n_ok, self.n_all = [], self.pose[:2], 0, 0
        if r.get("step_confirmed") and r.get("step_confirmed_dz_m") is not None:
            dz, dist = r["step_confirmed_dz_m"], r.get("step_confirmed_dist_m") or 1.0
            x, y = self.ahead(dist)
            cell = (round(x / 0.5), round(y / 0.5))
            old = self.steps.get(cell)
            if old is None or dist < old[0]:                    # new step, or a closer (better) view of it
                key = old[1] if old else "step:%d_%d" % cell
                self.steps[cell] = (dist, key)
                self.event(key, "step", abs(dz) * 100, "cm", x, y, 0.9,
                           "%s 단차 %.1f cm (%.1f m 앞에서 확인)" % ("오르막" if dz > 0 else "내리막", abs(dz) * 100, dist))

    def on_timer(self):
        if self.pose is None and time.time() - self.t_start > 10:
            self.get_logger().warn("no odometry yet: measurements cannot be placed (is sport mode running? "
                                   "/utlidar/robot_odom comes from the sport service)", throttle_duration_sec=30.0)
        self.read_inspect()
        try:
            st = json.loads(Path("/dev/shm/auto_recorder.json").read_text())
            pct = st.get("battery_pct", st.get("battery_soc_pct"))      # auto_recorder writes battery_pct
            if pct is not None and pct != self.battery:                  # send only when it changes
                self.battery = int(pct)
                self.out.put({"type": "status", "row": {"battery": self.battery}})
        except (OSError, ValueError):
            pass

    def read_inspect(self):
        """Sunken / raised tiles and holes found by inspect_node (state.json, rewritten every second)."""
        folder = self.inspect_dir / self.inspect_session if self.inspect_session else None
        if folder is None:
            cands = [d for d in self.inspect_dir.glob("*/state.json") if d.stat().st_mtime > self.t_start - 5]
            if not cands:
                return
            folder = max(cands, key=lambda p: p.stat().st_mtime).parent
        try:
            st = json.loads((folder / "state.json").read_text())
        except (OSError, ValueError):
            return
        for e in st.get("events", []):
            snap = folder / "snap" / (e.get("snap") or "")
            mtime = snap.stat().st_mtime if snap.is_file() else 0
            if self.inspect_seen.get(e["id"]) == (e["h_mm"], mtime):
                continue
            self.inspect_seen[e["id"]] = (e["h_mm"], mtime)
            image, data = "", None
            if mtime:
                image, data = "img/%s_E%s.jpg" % (folder.name, e["id"]), snap.read_bytes()
            self.event("inspect:%s:%s" % (folder.name, e["id"]), "step", abs(e["h_mm"]) / 10.0, "cm", e["x"], e["y"],
                       min(1.0, e.get("n_obs", 3) / 10.0),
                       "%s %+.1f mm · 면적 %.0f cm² (관측 %d회)" % (e["kind"], e["h_mm"], e.get("area_cm2", 0),
                                                              e.get("n_obs", 0)), image, data)


def main():
    rclpy.init()
    node = Bridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
