"""StepMap live: 측정 결과를 받는 즉시 합쳐(merge) 대시보드를 몇 초마다 갱신하고, 다른 컴퓨터로 끊김 없이 복제한다.

  # 로봇(Jetson): 측정 노드 → stepmap_bridge가 POST /api/ingest → 이 서버
  stepmap live -d sessions/<세션> --port 8060
  # 노트북: 로봇 서버에서 끌어와(pull) 같은 대시보드를 띄운다. 네트워크가 끊겨도 다시 연결되면 빠진 것부터 이어받는다
  stepmap live -d sessions/<세션> --port 8060 --pull http://<로봇 주소>:8060
  # 경로가 여럿이면 쉼표로: 끊기면 다음 주소로 자동 전환 (유선 → Go2 WiFi 경유 → 핫스팟 → Tailscale)
  stepmap live -d sessions/<세션> --pull http://192.168.123.18:8060,http://100.65.117.65:8060

저장: 받은 항목은 모두 순번(seq)을 붙여 <세션>/stream.jsonl에 한 줄씩 추가하고 디스크에 바로 쓴다 (fsync).
서버를 다시 켜면 stream.jsonl을 다시 읽어 그대로 복원한다. CSV(events·trajectory·foot_traces)는 stream에서
`stepmap merge`와 같은 함수(merge_events, link_foot_traces)로 다시 만든 결과이므로, 같은 입력이면 오프라인 merge와
같은 파일이 나온다.

항목 (JSON, ingest·since 공통):
  {"type": "event", "key": "<출처별 고유 키>", "row": {events.csv 열, id·level 빈칸 가능}}
      같은 key가 다시 오면 덮어쓴다 (측정이 쌓이며 값·사진이 바뀌는 지점)
  {"type": "traj", "row": {"t", "x", "y"}}                 이동 궤적 한 점 (t가 앞 점보다 늦을 때만)
  {"type": "trace", "key": "<걸음 키>", "rows": [foot_traces 열, id 빈칸 + t_event]}
  {"type": "status", "row": {"battery": 72, ...}}          로봇 상태 (CSV에는 넣지 않고 화면용)
  {"type": "file", "path": "img/xx.jpg"}                    사진이 도착했다는 표시 (복제 쪽이 GET /files/로 받아 간다)

시계: Jetson은 RTC 배터리가 없어 인터넷이 없으면 1970년부터 다시 센다. 로봇 쪽 시각이 CLOCK_VALID보다 작으면,
노트북이 /api/since?now=<노트북 시각>으로 처음 연결될 때 차이(clock_offset)를 기록하고, CSV·대시보드에는
보정한 시각을 쓴다 (stream에는 원래 값 그대로). 복제본(--pull)은 로봇이 알려 주는 같은 보정값을 쓴다.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .events import (_NUMERIC_DIGITS, EVENT_COLUMNS, FOOT_TRACE_COLUMNS, FormatError, GeoRef, georef_from_config,
                     link_foot_traces, load_config, merge_events, merge_from_config, thresholds_from_config,
                     validate_events, validate_foot_traces, write_events, write_foot_traces, write_trajectory)

STREAM = "stream.jsonl"
META = "live_meta.json"
OUT_DIR = "live"                 # <세션>/live/: dashboard.html, report.html, photos/
CLOCK_VALID = 1.6e9              # 2020-09-13. 이보다 작은 시각 = 시계가 맞지 않은 로봇
EXPORT_MIN_S = 2.0               # 내보내기 확인 간격
TRAJ_REFRESH_S = 30.0            # 측정 지점이 그대로이고 궤적만 늘었을 때 대시보드를 다시 만드는 간격
PULL_PERIOD_S = 1.0
# config.yaml의 geo가 아직 <...>이면 지도에 필요한 위도·경도를 이 기준점으로 만든다 (위치는 출발점 기준 상대값).
# 실제 지도 위치가 필요하면 config.yaml geo 또는 --geo LAT,LON,HEADING
FALLBACK_GEO = GeoRef(33.4860373, 126.4866073, 0.0)

LIVE_SCRIPT = """
<div id="stepmap-live" style="position:fixed;left:12px;bottom:12px;z-index:100000;
 font:600 12px/1.6 system-ui,sans-serif;background:rgba(255,255,255,.92);border:1px solid #d9d9d9;border-radius:999px;
 padding:2px 12px;color:#333;box-shadow:0 1px 4px rgba(0,0,0,.12)">● 실시간 연결 중…</div>
<script>
(function () {
  var badge = document.getElementById("stepmap-live");
  var loaded = __VERSION__, last = Date.now();
  function hhmmss(d) { return d.toTimeString().slice(0, 8); }
  function tick() {
    fetch("api/version", {cache: "no-store"}).then(function (r) { return r.json(); }).then(function (v) {
      last = Date.now();
      if (v.version > loaded) { location.reload(); return; }
      badge.style.color = "#1e7b34";
      badge.textContent = "● 실시간 · 측정 지점 " + v.events + "개 (위험 " + v.danger + " · 주의 " + v.warn + ")"
        + (v.battery != null ? " · 배터리 " + v.battery + "%" : "") + " · " + hhmmss(new Date());
    }).catch(function () {
      badge.style.color = "#b42318";
      badge.textContent = "● 연결 끊김 · 마지막 수신 " + hhmmss(new Date(last));
    });
  }
  tick();
  setInterval(tick, 2000);
})();
</script>
"""


def _norm_event(row: dict) -> dict:
    """JSON으로 받은 행을 events.py의 내부 형식(숫자 열은 float/None, 나머지는 문자열)으로 맞춘다."""
    out = {}
    for c in EVENT_COLUMNS:
        v = row.get(c)
        if c in _NUMERIC_DIGITS:
            out[c] = None if v is None or v == "" else (float(v) if isinstance(v, (int, float)) else v)
        else:
            out[c] = "" if v is None else str(v)
    return out


def _norm_trace(row: dict) -> dict:
    out = {}
    for c in FOOT_TRACE_COLUMNS:
        v = row.get(c)
        if c in ("id", "leg"):
            out[c] = "" if v is None else str(v)
        else:
            out[c] = None if v is None or v == "" else (float(v) if isinstance(v, (int, float)) else v)
    return out


class LiveStore:
    """세션 하나의 실시간 저장소: stream.jsonl (추가 전용) + 메모리 상태 + CSV·대시보드 내보내기."""

    def __init__(self, folder: str | Path, cfg: dict | None = None, geo: GeoRef | None = None):
        self.dir = Path(folder)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.cfg = cfg or {}
        self.geo = geo or georef_from_config(self.cfg)
        self.geo_is_fallback = self.geo is None
        self.geo = self.geo or FALLBACK_GEO
        self.lock = threading.RLock()
        self.seq = 0
        self.events: dict[str, dict] = {}
        self.traj: list[dict] = []
        self.traces: dict[str, list[dict]] = {}
        self.status: dict = {}
        self.items: list[dict] = []          # 모든 항목 (seq 순), since()용
        self.meta = {"clock_offset": 0.0, "pull_seq": 0}
        if (self.dir / META).is_file():
            self.meta.update(json.loads((self.dir / META).read_text(encoding="utf-8")))
        self.version = 0                      # 내보낸 결과가 바뀔 때마다 증가 (대시보드 새로고침 기준)
        self.summary = {"events": 0, "danger": 0, "warn": 0}
        self.dirty = False
        self.pull_state: dict = {}                # --pull: 지금 받는 주소와 상태
        self._sig = None                      # 마지막으로 그린 측정 지점·발끝 기록·상태
        self._drawn_at = 0.0
        self._replay()

    # ---- 저장 ----
    def _replay(self):
        path = self.dir / STREAM
        if not path.is_file():
            return
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    self._apply(json.loads(line))
        self.dirty = bool(self.items)

    def _save_meta(self):
        tmp = self.dir / (META + ".tmp")
        tmp.write_text(json.dumps(self.meta), encoding="utf-8")
        os.replace(tmp, self.dir / META)

    def _apply(self, item: dict):
        self.seq = max(self.seq, int(item["seq"]))
        self.items.append(item)
        kind = item["type"]
        if kind == "event":
            self.events[item["key"]] = _norm_event(item["row"])
        elif kind == "traj":
            r = item["row"]
            if not self.traj or float(r["t"]) > self.traj[-1]["t"]:   # 시간순만 받는다
                self.traj.append({"t": float(r["t"]), "x": float(r["x"]), "y": float(r["y"])})
        elif kind == "trace":
            self.traces[item["key"]] = [_norm_trace(r) for r in item["rows"]]
        elif kind == "status":
            self.status.update(item["row"])

    def check(self, item: dict) -> list[str]:
        """받기 전에 형식 검사 (잘못된 항목이 stream에 들어가 내보내기를 깨지 않게)."""
        kind = item.get("type")
        if kind == "event":
            if not item.get("key"):
                return ["event: key 필요"]
            row = _norm_event(item.get("row") or {})
            return validate_events([row], raw=True)
        if kind == "traj":
            r = item.get("row") or {}
            return [] if all(isinstance(r.get(c), (int, float)) for c in ("t", "x", "y")) else ["traj: t, x, y 숫자 필요"]
        if kind == "trace":
            if not item.get("key") or not item.get("rows"):
                return ["trace: key, rows 필요"]
            return validate_foot_traces([_norm_trace(r) for r in item["rows"]], raw=True)
        if kind in ("status", "file"):
            return []
        return [f"알 수 없는 type {kind!r}"]

    def ingest(self, items: list[dict], keep_src_seq: bool = False) -> tuple[int, list[str]]:
        """항목을 검사·저장한다. 잘못된 항목은 건너뛰고 오류를 돌려준다. 반환: (마지막 seq, 오류 목록)."""
        errors = []
        with self.lock:
            lines = []
            for item in items:
                if item.get("type") == "event" and isinstance(item.get("row"), dict) and not item["row"].get("session"):
                    item = {**item, "row": {**item["row"], "session": self.dir.name}}
                e = self.check(item)
                if e:
                    errors += e
                    continue
                self.seq += 1
                rec = {k: v for k, v in item.items() if k != "seq"}
                rec["seq"] = self.seq
                if keep_src_seq and "seq" in item:
                    rec["src_seq"] = item["seq"]
                lines.append(json.dumps(rec, ensure_ascii=False))
                self._apply(rec)
            if lines:
                with open(self.dir / STREAM, "a", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                self.dirty = True
            return self.seq, errors

    def since(self, seq: int, limit: int = 2000) -> list[dict]:
        with self.lock:
            lo, hi = 0, len(self.items)
            while lo < hi:                      # items는 seq 순
                mid = (lo + hi) // 2
                if self.items[mid]["seq"] <= seq:
                    lo = mid + 1
                else:
                    hi = mid
            return self.items[lo:lo + limit]

    def note_remote_clock(self, now: float):
        """복제하는 쪽 시각으로 로봇 시계 보정값을 정한다 (로봇 시계가 1970이고 아직 보정값이 없을 때 한 번)."""
        mine = time.time()
        with self.lock:
            if mine < CLOCK_VALID and now > CLOCK_VALID and not self.meta.get("clock_offset"):
                self.meta["clock_offset"] = now - mine
                self._save_meta()
                self.dirty = True

    # ---- 내보내기 ----
    def _rows(self):
        off = float(self.meta.get("clock_offset") or 0.0)
        session = self.dir.name
        events = []
        for r in self.events.values():
            r = dict(r)
            r["t"] = r["t"] + off
            r["session"] = r["session"] or session
            events.append(r)
        traj = [{"t": p["t"] + off, "x": p["x"], "y": p["y"], "lat": None, "lon": None} for p in self.traj]
        for p in traj:
            p["lat"], p["lon"] = self.geo.to_latlon(p["x"], p["y"])
        traces = []
        for rows in self.traces.values():
            for r in rows:
                r = dict(r)
                if r.get("t_event") is not None:
                    r["t_event"] += off
                traces.append(r)
        return events, traj, traces

    def export(self, force: bool = False) -> bool:
        """events.csv·trajectory.csv·foot_traces.csv를 다시 쓰고, 측정 지점이 바뀌었으면(또는 궤적만 바뀐 지
        TRAJ_REFRESH_S가 지났으면) 대시보드도 다시 만든다. 대시보드를 새로 만들었으면 True."""
        with self.lock:
            if not self.dirty and not force:
                return False
            self.dirty = False
            raw_events, traj, traces = self._rows()
            status = dict(self.status)
        try:
            return self._export(raw_events, traj, traces, status, force)
        except Exception:
            with self.lock:
                self.dirty = True                # 다음 주기에 다시 시도
            raise

    def _export(self, raw_events, traj, traces, status, force) -> bool:
        from .dashboard import write_dashboard
        th = thresholds_from_config(self.cfg)
        events, _ = merge_events(raw_events, th, merge_from_config(self.cfg), self.geo)
        write_events(self.dir / "events.csv", events)
        if not traj:                             # 대시보드는 궤적이 한 점 이상 있어야 그린다
            traj = [{"t": e["t"], "x": e["x"], "y": e["y"], "lat": e["lat"], "lon": e["lon"]} for e in events[:1]]
        write_trajectory(self.dir / "trajectory.csv", traj)
        linked, _ = link_foot_traces(traces, events) if traces else ([], [])
        trace_path = self.dir / "foot_traces.csv"
        if linked:
            write_foot_traces(trace_path, linked)
        elif trace_path.exists():
            trace_path.unlink()
        out = self.dir / OUT_DIR
        sig = json.dumps([events, linked, status.get("battery")], sort_keys=True, default=str)
        stale = time.time() - self._drawn_at > TRAJ_REFRESH_S
        if not force and sig == self._sig and not stale:
            return False
        self._sig, self._drawn_at = sig, time.time()
        if events or traj:
            meta = _meta(self.cfg, status)
            dash = write_dashboard(self.dir / "events.csv", self.dir / "trajectory.csv", out / "dashboard.html",
                                   th, meta, trace_path if linked else None)
            with self.lock:
                self.version += 1
                page = dash.read_text(encoding="utf-8")
                page = page.replace("</body>", LIVE_SCRIPT.replace("__VERSION__", str(self.version)) + "</body>", 1)
                tmp = dash.with_suffix(".tmp")
                tmp.write_text(page, encoding="utf-8")
                os.replace(tmp, dash)
        with self.lock:
            self.summary = {"events": len(events), "danger": sum(e["level"] == "danger" for e in events),
                            "warn": sum(e["level"] == "warn" for e in events)}
        return True

    def report(self) -> Path:
        from .report import write_report
        self.export(force=True)
        out = self.dir / OUT_DIR / "report.html"
        write_report(self.dir / "events.csv", self.dir / "trajectory.csv", out, thresholds_from_config(self.cfg),
                     str((self.cfg.get("report") or {}).get("area") or ""))
        self.export(force=True)                  # 대시보드에 "신고서 열기" 버튼을 넣으려면 다시 만든다
        return out


def _meta(cfg: dict, status: dict) -> dict:
    robot = cfg.get("robot") or {}
    battery = status.get("battery", robot.get("battery"))
    return {"area": str((cfg.get("report") or {}).get("area") or ""),
            "robot": str(robot.get("name") or ""),
            "model": str(robot.get("model") or ""),
            "sensors": [str(x) for x in robot.get("sensors") or []],
            "battery": battery}


# ---------------------------------------------------------------------------
# HTTP 서버
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    store: LiveStore = None  # type: ignore[assignment]

    def log_message(self, fmt, *args):   # 요청마다 찍지 않는다
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _file(self, path: Path):
        if not path.is_file():
            self._send(404, b"not found", "text/plain")
            return
        ctype = {".html": "text/html; charset=utf-8", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                 ".csv": "text/csv; charset=utf-8", ".json": "application/json"}.get(path.suffix.lower(),
                                                                                   "application/octet-stream")
        self._send(200, path.read_bytes(), ctype)

    def _safe(self, base: Path, rel: str) -> Path | None:
        p = (base / urllib.parse.unquote(rel)).resolve()
        return p if str(p).startswith(str(base.resolve())) else None

    def do_GET(self):
        s = self.store
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            self.send_response(302)
            self.send_header("Location", "/dashboard.html")
            self.end_headers()
        elif u.path == "/api/version":
            with s.lock:
                self._json({"version": s.version, "seq": s.seq, **s.summary, "battery": s.status.get("battery"),
                            "status": s.status, "clock_offset": s.meta.get("clock_offset"),
                            "geo_fallback": s.geo_is_fallback, "pull": s.pull_state})
        elif u.path == "/api/since":
            if "now" in q:
                s.note_remote_clock(float(q["now"][0]))
            items = s.since(int(q.get("seq", ["0"])[0]))
            self._json({"items": items, "last": s.seq, "clock_offset": s.meta.get("clock_offset") or 0.0})
        elif u.path == "/report":
            try:
                s.report()
                self.send_response(302)
                self.send_header("Location", "/report.html")
                self.end_headers()
            except (FormatError, ValueError) as e:
                self._send(500, str(e).encode("utf-8"), "text/plain; charset=utf-8")
        elif u.path.startswith("/files/"):
            p = self._safe(s.dir, u.path[len("/files/"):])
            self._file(p) if p else self._send(403, b"forbidden", "text/plain")
        else:
            p = self._safe(s.dir / OUT_DIR, u.path.lstrip("/"))
            self._file(p) if p else self._send(403, b"forbidden", "text/plain")

    def do_POST(self):
        s = self.store
        u = urllib.parse.urlparse(self.path)
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if u.path == "/api/ingest":
            try:
                items = json.loads(body.decode("utf-8"))["items"]
            except (ValueError, KeyError) as e:
                self._json({"ok": False, "errors": [f"JSON: {e}"]}, 400)
                return
            seq, errors = s.ingest(items)
            self._json({"ok": not errors, "seq": seq, "errors": errors[:20]}, 200 if not errors else 207)
        elif u.path == "/api/file":
            rel = urllib.parse.parse_qs(u.query).get("path", [""])[0]
            p = self._safe(s.dir, rel)
            if not p or not rel:
                self._send(403, b"forbidden", "text/plain")
                return
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + ".part")
            tmp.write_bytes(body)
            os.replace(tmp, p)
            s.ingest([{"type": "file", "path": rel}])
            self._json({"ok": True})
        else:
            self._send(404, b"not found", "text/plain")


def _exporter(store: LiveStore, stop: threading.Event):
    while not stop.is_set():
        try:
            if store.export():
                print(f"[live] {time.strftime('%H:%M:%S')} 대시보드 갱신 v{store.version}: {store.summary}", flush=True)
        except (FormatError, ValueError) as e:     # 내보내기 실패는 다음 갱신 때 다시 시도
            print(f"[live] 내보내기 실패: {e}", file=sys.stderr, flush=True)
        stop.wait(EXPORT_MIN_S)


def _pull_once(store: LiveStore, url: str) -> int:
    """url에서 새 항목을 한 번 받아 저장한다. 받은 항목 수를 돌려준다 (실패하면 예외)."""
    last = int(store.meta.get("pull_seq") or 0)
    q = urllib.parse.urlencode({"seq": last, "now": f"{time.time():.3f}"})
    with urllib.request.urlopen(f"{url}/api/since?{q}", timeout=4) as r:
        data = json.loads(r.read().decode("utf-8"))
    items = data["items"]
    off = float(data.get("clock_offset") or 0.0)     # 복제본은 로봇의 시계 보정값을 그대로 쓴다
    if off != store.meta.get("clock_offset"):
        with store.lock:
            store.meta["clock_offset"] = off
            store._save_meta()
            store.dirty = True
    for it in items:
        if it["type"] == "file":                    # 사진: 먼저 파일을 받아 둔다
            dst = store.dir / it["path"]
            if not dst.exists():
                with urllib.request.urlopen(f"{url}/files/{urllib.parse.quote(it['path'])}", timeout=10) as r:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    tmp = dst.with_name(dst.name + ".part")
                    with open(tmp, "wb") as f:
                        shutil.copyfileobj(r, f)
                    os.replace(tmp, dst)
    if items:
        store.ingest(items, keep_src_seq=True)
        with store.lock:
            store.meta["pull_seq"] = items[-1]["seq"]
            store._save_meta()
    return len(items)


def _puller(store: LiveStore, urls, stop: threading.Event):
    """원격(로봇) 서버에서 새 항목을 끌어온다. 끊기면 마지막으로 받은 seq 다음부터 다시 받는다.

    urls: 같은 로봇에 닿는 주소 여러 개 (쉼표로 구분한 문자열 또는 목록). 예: 유선 LAN, Go2 WiFi 경유,
    휴대폰 핫스팟, Tailscale. 지금 주소가 끊기면 다음 주소를 차례로 시도하고, 닿는 주소에 머문다.
    """
    if isinstance(urls, str):
        urls = [u for u in urls.split(",") if u.strip()]
    urls = [u.strip().rstrip("/") for u in urls]
    i, connected = 0, None
    while not stop.is_set():
        url = urls[i]
        try:
            n = _pull_once(store, url)
            store.pull_state = {"url": url, "ok": True, "t": time.time()}
            if connected != url:
                print(f"[live] {url} 연결됨 (받은 seq {store.meta.get('pull_seq')})", flush=True)
                connected = url
            if n >= 2000:
                continue                             # 밀린 것이 더 있으면 바로 다음 묶음
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            if connected is not False:
                print(f"[live] {url} 연결 끊김 ({e}); 다른 주소/재연결 시 이어받음", flush=True)
            store.pull_state = {"url": url, "ok": False, "t": time.time()}
            connected = False
            if len(urls) > 1:
                i = (i + 1) % len(urls)
                if i != 0:
                    continue                         # 다음 주소를 바로 시도, 한 바퀴 돌면 잠시 쉰다
        stop.wait(PULL_PERIOD_S)


def serve(folder: str | Path, port: int = 8060, config: str | Path = "config.yaml", pull: str | None = None,
          geo: GeoRef | None = None, host: str = "0.0.0.0") -> None:
    cfg = load_config(config) if Path(config).exists() else {}
    store = LiveStore(folder, cfg, geo)
    if store.geo_is_fallback:
        print("[live] config.yaml geo 미설정: 지도 위치는 기준점 대비 상대값입니다 (--geo LAT,LON,HEADING)", flush=True)
    _Handler.store = store
    stop = threading.Event()
    threading.Thread(target=_exporter, args=(store, stop), daemon=True).start()
    if pull:
        threading.Thread(target=_puller, args=(store, pull, stop), daemon=True).start()
    httpd = ThreadingHTTPServer((host, port), _Handler)
    print(f"[live] 세션 {store.dir} (항목 {store.seq}개) → http://{host}:{port}/", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        httpd.server_close()
        store.export(force=True)
