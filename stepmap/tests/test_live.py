import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from stepmap import demo, live
from stepmap.events import (EVENT_COLUMNS, GeoRef, merge_events, read_events, read_foot_traces, write_events)


@pytest.fixture(scope="module")
def split_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("split")
    demo.generate(d, split=True)
    return d


def items_from_split(d):
    """기능별 결과 파일을 live 항목으로 (측정 노드가 하나씩 보내는 것과 같은 내용)."""
    items = []
    for name in demo.RAW_FILES:
        for i, r in enumerate(read_events(d / "raw" / name, raw=True)):
            items.append({"type": "event", "key": f"{name}:{i}", "row": {c: r[c] for c in EVENT_COLUMNS}})
    steps = {}
    for r in read_foot_traces(d / "raw" / demo.RAW_TRACES, raw=True):
        steps.setdefault((r["leg"], r["t_event"]), []).append(r)
    for (leg, t_event), rows in steps.items():
        items.append({"type": "trace", "key": f"{leg}:{t_event}", "rows": rows})
    return items


def test_live_equals_offline_merge(split_dir, tmp_path):
    items = items_from_split(split_dir)
    store = live.LiveStore(tmp_path / "s", {})
    seq, errors = store.ingest(items)
    assert errors == [] and seq == len(items)
    assert store.export(force=True)
    rows = [r for name in demo.RAW_FILES for r in read_events(split_dir / "raw" / name, raw=True)]
    offline, _ = merge_events(rows)
    write_events(tmp_path / "offline.csv", offline)
    assert (tmp_path / "s" / "events.csv").read_bytes() == (tmp_path / "offline.csv").read_bytes()
    assert (tmp_path / "s" / "foot_traces.csv").is_file()
    page = (tmp_path / "s" / "live" / "dashboard.html").read_text(encoding="utf-8")
    assert "stepmap-live" in page and "api/version" in page
    assert store.summary["events"] == len(offline)


def test_replay_and_upsert(split_dir, tmp_path):
    items = items_from_split(split_dir)
    a = live.LiveStore(tmp_path / "s", {})
    a.ingest(items)
    first = items[0]
    changed = {**first, "row": {**first["row"], "value": 9.9}}
    a.ingest([changed])                                     # 같은 key: 덮어쓰기
    b = live.LiveStore(tmp_path / "s", {})                 # 다시 켜면 stream.jsonl에서 복원
    assert b.seq == a.seq == len(items) + 1
    assert b.events[first["key"]]["value"] == 9.9
    assert len(b.events) == len({i["key"] for i in items if i["type"] == "event"})


def test_bad_items_rejected(tmp_path):
    s = live.LiveStore(tmp_path / "s", {})
    bad = {"type": "event", "key": "k", "row": {"t": 1, "x": 0, "y": 0, "kind": "step", "value": 2, "unit": "mm",
                                               "source": "camera", "confidence": 0.9}}
    seq, errors = s.ingest([bad, {"type": "nope"}, {"type": "traj", "row": {"t": "a"}}])
    assert seq == 0 and len(errors) == 3
    assert not (tmp_path / "s" / live.STREAM).exists()
    ok = {**bad, "row": {**bad["row"], "unit": "cm"}}
    seq, errors = s.ingest([ok])
    assert seq == 1 and errors == [] and s.events["k"]["session"] == "s"   # session 빈칸이면 세션 폴더 이름


def test_trajectory_only_does_not_redraw(tmp_path):
    s = live.LiveStore(tmp_path / "s", {})
    s.ingest([{"type": "event", "key": "k", "row": {"t": 1, "x": 0, "y": 0, "kind": "step", "value": 2.5,
                                                    "unit": "cm", "source": "camera", "confidence": 0.9}}])
    assert s.export() and s.version == 1
    s.ingest([{"type": "traj", "row": {"t": 2, "x": 0.5, "y": 0}}])
    assert not s.export() and s.version == 1                # 궤적만 늘면 TRAJ_REFRESH_S 뒤에 다시 그린다
    s.ingest([{"type": "event", "key": "k2", "row": {"t": 3, "x": 1, "y": 0, "kind": "step", "value": 0.5,
                                                     "unit": "cm", "source": "camera", "confidence": 0.9}}])
    assert s.export() and s.version == 2


def test_robot_clock_offset(tmp_path, monkeypatch):
    s = live.LiveStore(tmp_path / "s", {})
    s.ingest([{"type": "event", "key": "k", "row": {"t": 1000.0, "x": 0, "y": 0, "kind": "slope", "value": 3.0,
                                                    "unit": "deg", "source": "camera", "confidence": 0.9}}])
    monkeypatch.setattr(live.time, "time", lambda: 1100.0)       # 로봇 시계: 1970년 근처
    s.note_remote_clock(1_792_454_400.0)                          # 노트북 시각
    monkeypatch.undo()
    s.export(force=True)
    t = read_events(tmp_path / "s" / "events.csv")[0]["t"]
    assert t == pytest.approx(1000.0 + 1_792_454_400.0 - 1100.0)
    assert json.loads((tmp_path / "s" / live.META).read_text())["clock_offset"] > 0


def test_http_ingest_and_pull_replication(split_dir, tmp_path):
    robot = live.LiveStore(tmp_path / "robot", {}, GeoRef(33.4860373, 126.4866073, 0.0))
    live._Handler.store = robot
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), live._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        items = items_from_split(split_dir)
        half = len(items) // 2
        body = json.dumps({"items": items[:half]}).encode()
        with urllib.request.urlopen(urllib.request.Request(url + "/api/ingest", body, method="POST")) as r:
            assert json.loads(r.read())["ok"]
        img = b"\xff\xd8fake-jpeg"
        req = urllib.request.Request(url + "/api/file?path=img/a.jpg", img, method="POST")
        urllib.request.urlopen(req).read()

        laptop = live.LiveStore(tmp_path / "laptop", {}, GeoRef(33.4860373, 126.4866073, 0.0))
        stop = threading.Event()
        threading.Thread(target=live._puller, args=(laptop, url, stop), daemon=True).start()
        for _ in range(100):
            if laptop.meta.get("pull_seq") == robot.seq:
                break
            time.sleep(0.05)
        robot.ingest(items[half:])                               # 연결 중에 들어온 나머지도 이어받는다
        for _ in range(100):
            if laptop.meta.get("pull_seq") == robot.seq:
                break
            time.sleep(0.05)
        stop.set()
        assert laptop.meta["pull_seq"] == robot.seq
        assert (tmp_path / "laptop" / "img" / "a.jpg").read_bytes() == img
        robot.export(force=True)
        laptop.export(force=True)
        assert (tmp_path / "laptop" / "events.csv").read_bytes() == (tmp_path / "robot" / "events.csv").read_bytes()
        with urllib.request.urlopen(url + "/api/version") as r:
            v = json.loads(r.read())
        assert v["events"] == robot.summary["events"] and v["seq"] == robot.seq
        with urllib.request.urlopen(url + "/dashboard.html") as r:
            assert b"stepmap-live" in r.read()
    finally:
        httpd.shutdown()
