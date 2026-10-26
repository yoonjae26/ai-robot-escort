import json
import math
import random
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from stepmap import live
from stepmap.events import GeoRef
from stepmap.gps import fit_geo, shift_m

TRUE = GeoRef(37.5665, 126.9780, 130.0)      # 정답: odom 원점·방위각


def fixes_along(path, noise=0.0, acc=5.0, seed=0):
    rnd = random.Random(seed)
    out = []
    for x, y in path:
        lat, lon = TRUE.to_latlon(x + rnd.gauss(0, noise), y + rnd.gauss(0, noise))
        out.append({"lat": lat, "lon": lon, "acc": acc, "x": x, "y": y})
    return out


def test_fit_recovers_origin_and_heading():
    path = [(0.5 * i, 0.1 * i) for i in range(60)]          # 30 m 직진
    geo, heading_ok = fit_geo(fixes_along(path, noise=2.0))
    assert heading_ok
    assert abs((geo.heading_deg - TRUE.heading_deg + 180) % 360 - 180) < 5
    assert shift_m(geo, TRUE, [(0, 0), path[-1]]) < 3.0


def test_single_fix_places_robot_but_not_heading():
    geo, heading_ok = fit_geo(fixes_along([(4.0, -2.0)]))
    assert not heading_ok
    assert shift_m(geo, TRUE, [(4.0, -2.0)]) < 0.01           # 그 순간 로봇 위치는 정확
    geo2, ok2 = fit_geo(fixes_along([(0, 0), (1, 0), (2, 0)]), heading_deg=TRUE.heading_deg)
    assert not ok2 and abs(geo2.heading_deg - TRUE.heading_deg) < 1e-6   # 거의 안 움직이면 주어진 방위각 유지


def test_outlier_and_inaccurate_fixes_ignored():
    path = [(0.5 * i, 0.0) for i in range(40)]
    fx = fixes_along(path, noise=1.0)
    fx[10] = {**fx[10], "lat": fx[10]["lat"] + 0.002}         # 200 m 튄 위치
    fx.append({"lat": 0.0, "lon": 0.0, "acc": 900.0, "x": 1.0, "y": 1.0})  # WiFi 추정 등 부정확한 위치
    geo, ok = fit_geo(fx)
    assert ok and shift_m(geo, TRUE, [(0, 0), path[-1]]) < 3.0
    assert fit_geo([{"lat": 1.0, "lon": 1.0, "acc": 900.0, "x": 0.0, "y": 0.0}]) is None


def _row(x, y, t):
    return {"type": "traj", "row": {"t": t, "x": x, "y": y}}


def test_store_gps_moves_map_and_replays(tmp_path):
    store = live.LiveStore(tmp_path / "s", {})
    assert store.geo_source == "none"
    assert store.add_gps(37.0, 127.0, 5.0) == "로봇 위치(odom)가 아직 없습니다"
    path = [(0.5 * i, 0.0) for i in range(40)]
    for i, (x, y) in enumerate(path):
        store.ingest([_row(x, y, 1000.0 + i)])
        lat, lon = TRUE.to_latlon(x, y)
        store.gps.append({"t": 1000.0 + i, "lat": lat, "lon": lon, "acc": 4.0, "x": x, "y": y})  # 짝 (시간 간격 무시)
    store.export(force=True)
    assert store.geo_source == "gps" and store.gps_heading_ok and not store.geo_is_fallback
    lat, lon = store.robot_latlon()
    tl, to = TRUE.to_latlon(*path[-1])
    assert abs(lat - tl) < 1e-5 and abs(lon - to) < 1e-5
    traj = (tmp_path / "s" / "trajectory.csv").read_text(encoding="utf-8")
    assert f"{TRUE.to_latlon(0, 0)[0]:.4f}" in traj

    # add_gps: 마지막 odom 위치와 짝지어 stream에 저장 → 다시 켜도 같은 위치
    assert store.add_gps(*TRUE.to_latlon(*path[-1]), 3.0) is None
    again = live.LiveStore(tmp_path / "s", {})
    assert len(again.gps) == 1 and again.gps[0]["x"] == path[-1][0]
    again.export(force=True)
    assert again.geo_source == "gps"


def test_config_geo_wins(tmp_path):
    store = live.LiveStore(tmp_path / "s", {}, geo=GeoRef(33.0, 126.0, 0.0))
    store.ingest([_row(0.0, 0.0, 1.0)])
    store.add_gps(37.0, 127.0, 3.0)
    store.export(force=True)
    assert store.geo_source == "config" and store.geo.origin_lat == 33.0


def test_bad_gps_item_rejected(tmp_path):
    store = live.LiveStore(tmp_path / "s", {})
    _, errors = store.ingest([{"type": "gps", "row": {"t": 1, "lat": 99.0, "lon": 1, "x": 0, "y": 0}},
                              {"type": "gps", "row": {"t": 1, "lat": "a"}}])
    assert len(errors) == 2 and not store.gps


@pytest.fixture
def robot_server(tmp_path):
    store = live.LiveStore(tmp_path / "robot", {})
    live._Handler.store = store
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), live._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield store, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def post(url, obj):
    req = urllib.request.Request(url, data=json.dumps(obj).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_http_gps_and_version(robot_server):
    store, url = robot_server
    assert post(f"{url}/api/gps", {"lat": 37.0, "lon": 127.0})[0] == 409     # odom 없음
    assert post(f"{url}/api/gps", {"lat": "x"})[0] == 400
    store.ingest([_row(2.0, 1.0, 5.0)])
    code, d = post(f"{url}/api/gps", {"lat": 37.5, "lon": 127.1, "acc": 6.0})
    assert code == 200 and d["ok"]
    store.export(force=True)
    with urllib.request.urlopen(f"{url}/api/version") as r:
        v = json.loads(r.read())
    assert v["geo"]["source"] == "gps" and v["geo"]["fixes"] == 1 and not v["geo"]["heading_ok"]
    assert math.isclose(v["robot"][0], 37.5, abs_tol=1e-6) and math.isclose(v["robot"][1], 127.1, abs_tol=1e-6)


def test_replica_forwards_gps_to_robot(robot_server, tmp_path):
    store, url = robot_server
    store.ingest([_row(0.0, 0.0, 5.0)])
    replica = live.LiveStore(tmp_path / "laptop", {})
    replica.forward_gps = True
    replica.pull_state = {"url": url, "ok": True}
    h = type("H", (live._Handler,), {"store": replica})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        code, d = post(f"http://127.0.0.1:{httpd.server_address[1]}/api/gps", {"lat": 37.5, "lon": 127.1, "acc": 6.0})
    finally:
        httpd.shutdown()
    assert code == 200 and d["ok"] and len(store.gps) == 1 and not replica.gps   # 로봇이 저장, 복제본은 pull로 받는다
