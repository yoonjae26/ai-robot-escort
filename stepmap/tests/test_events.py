import math
import random
from pathlib import Path

import pytest

from stepmap.events import (
    DEFAULT_THRESHOLDS, EVENT_COLUMNS, FormatError, GeoRef, georef_from_config, judge,
    latlon_to_odom, load_config, odom_to_latlon, path_length, read_events, read_trajectory,
    thresholds_from_config, validate_events, validate_trajectory, write_events, write_trajectory,
)

ROOT = Path(__file__).resolve().parents[1]


def make_event(**kw):
    e = {
        "id": "ev_0001", "t": 1792454410.0, "session": "s", "x": 4.42, "y": 0.36,
        "lat": 33.486, "lon": 126.4866, "kind": "step", "value": 3.7, "unit": "cm",
        "source": "camera+foot", "leg": "FR", "confidence": 0.85, "level": "danger",
        "image": "", "note": "횡단보도 진입부 연석", "value_foot": 3.9, "image_mark": "",
    }
    e.update(kw)
    return e


# --- 형식 검사 ---------------------------------------------------------------

def test_valid_event_passes():
    assert validate_events([make_event()]) == []


def test_missing_column():
    e = make_event()
    del e["unit"]
    errors = validate_events([e])
    assert any("열 누락" in m and "unit" in m for m in errors)


@pytest.mark.parametrize("kind,unit", [("step", "mm"), ("slope", "cm"), ("crack", "deg"), ("loose", "cm")])
def test_wrong_unit(kind, unit):
    e = make_event(kind=kind, unit=unit, source="camera", leg="", value_foot=None)
    assert any("unit" in m for m in validate_events([e]))


@pytest.mark.parametrize("field,value", [
    ("kind", "pothole"), ("source", "lidar"), ("level", "bad"), ("leg", "XX"),
])
def test_bad_enum(field, value):
    assert any(field in m for m in validate_events([make_event(**{field: value})]))


def test_foot_rules():
    # 발 측정인데 leg 없음
    assert validate_events([make_event(source="foot", leg="", value_foot=None)])
    # 교차 측정인데 value_foot 없음
    assert validate_events([make_event(value_foot=None)])
    # 카메라 단독인데 value_foot 있음
    assert validate_events([make_event(source="camera", leg="")])


def test_duplicate_id_and_confidence_range():
    errors = validate_events([make_event(), make_event(confidence=1.5)])
    assert any("중복" in m for m in errors)
    assert any("confidence" in m for m in errors)


def test_latlon_both_or_neither():
    assert validate_events([make_event(lat=None, lon=None)]) == []
    assert validate_events([make_event(lon=None)])


def test_write_rejects_invalid(tmp_path):
    with pytest.raises(FormatError):
        write_events(tmp_path / "e.csv", [make_event(unit="mm")])
    assert not (tmp_path / "e.csv").exists()


def test_events_roundtrip(tmp_path):
    rows = [make_event(), make_event(id="ev_0002", kind="crack", value=0.62, unit="score",
                                     source="camera", leg="", value_foot=None, level="warn", note="")]
    write_events(tmp_path / "e.csv", rows)
    back = read_events(tmp_path / "e.csv")
    assert list(back[0].keys()) == EVENT_COLUMNS
    assert back == rows


def test_read_rejects_missing_column(tmp_path):
    p = tmp_path / "e.csv"
    p.write_text(",".join(c for c in EVENT_COLUMNS if c != "lat") + "\n", encoding="utf-8")
    with pytest.raises(FormatError, match="lat"):
        read_events(p)


def test_trajectory_time_order(tmp_path):
    rows = [{"t": 2.0, "x": 0, "y": 0, "lat": None, "lon": None},
            {"t": 1.0, "x": 1, "y": 0, "lat": None, "lon": None}]
    assert any("시간순" in m for m in validate_trajectory(rows))
    write_trajectory(tmp_path / "t.csv", rows[::-1])
    assert len(read_trajectory(tmp_path / "t.csv")) == 2


# --- 판정 경계값 (계획서 6.3) ------------------------------------------------

@pytest.mark.parametrize("kind,value,expected", [
    ("step", 0.99, "ok"), ("step", 1.0, "warn"), ("step", 1.99, "warn"), ("step", 2.0, "danger"),
    ("slope", 4.75, "ok"), ("slope", 4.76, "warn"), ("slope", 7.12, "warn"), ("slope", 7.13, "danger"),
    ("crack", 0.49, "ok"), ("crack", 0.5, "warn"), ("crack", 0.79, "warn"), ("crack", 0.8, "danger"),
    ("loose", 2.99, "ok"), ("loose", 3.0, "warn"), ("loose", 5.99, "warn"), ("loose", 6.0, "danger"),
])
def test_judge_boundaries(kind, value, expected):
    assert judge(kind, value) == expected


def test_judge_unknown_kind():
    with pytest.raises(ValueError):
        judge("pothole", 1.0)


def test_config_thresholds_match_defaults():
    cfg = load_config(ROOT / "config.yaml")
    assert thresholds_from_config(cfg) == DEFAULT_THRESHOLDS


def test_judge_uses_config_thresholds():
    th = thresholds_from_config({"thresholds": {"step_warn_cm": 1.5, "step_danger_cm": 3.0}})
    assert judge("step", 2.0, th) == "warn"
    assert th["slope"] == DEFAULT_THRESHOLDS["slope"]  # 빠진 항목은 기본값


# --- 좌표 변환 ---------------------------------------------------------------

def test_config_geo_placeholder_is_none():
    assert georef_from_config(load_config(ROOT / "config.yaml")) is None
    geo = georef_from_config({"geo": {"origin_lat": 33.486, "origin_lon": 126.4866, "heading_deg": 90}})
    assert geo == GeoRef(33.486, 126.4866, 90.0)


@pytest.mark.parametrize("heading,x,y,d_north,d_east", [
    (0, 100, 0, 100, 0),     # 북쪽을 보고 전진
    (90, 100, 0, 0, 100),    # 동쪽을 보고 전진
    (90, 0, 100, 100, 0),    # 동쪽을 볼 때 왼쪽(y+)은 북쪽
    (0, 0, 100, 0, -100),    # 북쪽을 볼 때 왼쪽(y+)은 서쪽
])
def test_heading_direction(heading, x, y, d_north, d_east):
    geo = GeoRef(33.486, 126.4866, heading)
    lat, lon = odom_to_latlon(x, y, geo)
    north = math.radians(lat - geo.origin_lat) * 6378137.0
    east = math.radians(lon - geo.origin_lon) * 6378137.0 * math.cos(math.radians(geo.origin_lat))
    assert north == pytest.approx(d_north, abs=1e-6)
    assert east == pytest.approx(d_east, abs=1e-6)


def test_roundtrip_within_1cm_through_csv(tmp_path):
    """odom → 위경도 → CSV 저장·읽기 → odom 왕복 오차 1cm 이내."""
    rng = random.Random(0)
    for heading in (0, 37.5, 92.9, 180, 271):
        geo = GeoRef(33.4860825, 126.48661, heading)
        rows = []
        for i in range(200):
            x, y = rng.uniform(-1000, 1000), rng.uniform(-1000, 1000)
            lat, lon = odom_to_latlon(x, y, geo)
            rows.append({"t": float(i), "x": x, "y": y, "lat": lat, "lon": lon})
        write_trajectory(tmp_path / "t.csv", rows)
        for orig, back in zip(rows, read_trajectory(tmp_path / "t.csv")):
            x2, y2 = latlon_to_odom(back["lat"], back["lon"], geo)
            assert math.hypot(x2 - orig["x"], y2 - orig["y"]) < 0.01


# --- 이동 거리 -----------------------------------------------------------------

def test_path_length_ignores_jitter():
    rng = random.Random(1)
    # 100m 직선을 0.25m 간격으로, 위치 흔들림 ±3cm
    pts = [{"x": i * 0.25 + rng.gauss(0, 0.03), "y": rng.gauss(0, 0.03)} for i in range(401)]
    raw = sum(math.hypot(b["x"] - a["x"], b["y"] - a["y"]) for a, b in zip(pts, pts[1:]))
    assert raw > 101  # 흔들림이 더해져 늘어난다
    assert path_length(pts) == pytest.approx(100, abs=0.2)


def test_path_length_edge_cases():
    assert path_length([]) == 0
    assert path_length([{"x": 0, "y": 0}]) == 0
    # 1m 미만만 움직이면 마지막 점까지의 거리만
    assert path_length([{"x": 0, "y": 0}, {"x": 0.4, "y": 0}, {"x": 0.6, "y": 0}]) == pytest.approx(0.6)
    # 정지 중 흔들림만 있으면 거의 0
    assert path_length([{"x": 0.01 * (i % 2), "y": 0} for i in range(100)]) < 0.02


# --- image_mark (선택 열) ---------------------------------------------------------

def test_image_mark_parse_and_validate():
    from stepmap.events import parse_image_mark
    assert parse_image_mark("") is None
    assert parse_image_mark("0.35, 0.4, 0.13") == (0.35, 0.4, 0.13)
    for bad in ("0.5,0.5", "1.2,0.5,0.1", "0.5,0.5,0", "a,b,c"):
        with pytest.raises(ValueError):
            parse_image_mark(bad)
    assert validate_events([make_event(image="photos/a.jpg", image_mark="0.5,0.5,0.1")]) == []
    assert any("image_mark" in m for m in validate_events([make_event(image="photos/a.jpg", image_mark="2,0,0")]))
    assert any("image가 있을 때만" in m for m in validate_events([make_event(image_mark="0.5,0.5,0.1")]))


def test_file_without_image_mark_column_is_read(tmp_path):
    cols = [c for c in EVENT_COLUMNS if c != "image_mark"]
    e = make_event()
    p = tmp_path / "old.csv"
    lines = [",".join(cols), ",".join("" if e[c] is None else str(e[c]) for c in cols)]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    [row] = read_events(p)
    assert row["image_mark"] == ""
    write_events(tmp_path / "new.csv", [row])
    assert (tmp_path / "new.csv").read_text(encoding="utf-8-sig").splitlines()[0].endswith(",image_mark")


def test_uneven_kind():
    """노면 요철 (깊이 카메라 바닥 높이 편차, mm): 판정·기준 문구·config 키."""
    from stepmap.events import KIND_UNITS, criterion_text, thresholds_from_config
    assert KIND_UNITS["uneven"] == "mm"
    assert judge("uneven", 9.9) == "ok" and judge("uneven", 10.0) == "warn" and judge("uneven", 25.0) == "danger"
    assert criterion_text("uneven", "danger") == "노면 요철 20mm 이상 (휠체어 회피 기준)"
    assert thresholds_from_config({"thresholds": {"uneven_warn_mm": 8, "uneven_danger_mm": 15}})["uneven"] == (8.0, 15.0)
