from collections import Counter
from pathlib import Path

import pytest

from stepmap import demo
from stepmap.cli import main
from stepmap.events import (
    DEFAULT_THRESHOLDS, FormatError, GeoRef, MERGE_DEFAULTS, is_foot_traces_file, link_foot_traces, merge_events,
    merge_from_config, read_events, read_foot_traces, write_events, write_foot_traces,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def split_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("split")
    demo.generate(d, split=True)
    return d


def raw(**kw):
    r = {"id": "", "t": 0.0, "session": "s", "x": 0.0, "y": 0.0, "lat": None, "lon": None,
         "kind": "step", "value": 2.5, "unit": "cm", "source": "camera", "leg": "", "confidence": 0.8,
         "level": "", "image": "", "note": "", "value_foot": None}
    r.update(kw)
    return r


def foot_step(**kw):
    return raw(**{"source": "foot", "leg": "FR", "value": 2.7, **kw})


# --- 왕복: 기능별로 나눈 파일을 합치면 원래 events.csv ----------------------------

def test_split_files(split_dir):
    files = sorted(p.name for p in (split_dir / "raw").glob("*.csv"))
    assert files == sorted(demo.RAW_FILES + (demo.RAW_TRACES,))
    raw_traces = read_foot_traces(split_dir / "raw" / demo.RAW_TRACES, raw=True)
    assert all(r["id"] == "" and r["t_event"] is not None for r in raw_traces)  # 모듈 출력처럼 id 빈칸
    assert is_foot_traces_file(split_dir / "raw" / demo.RAW_TRACES)
    assert not is_foot_traces_file(split_dir / "raw" / "foot.csv")
    rows = {name: read_events(split_dir / "raw" / name, raw=True) for name in demo.RAW_FILES}
    assert all(r["id"] == "" and r["level"] == "" for rs in rows.values() for r in rs)
    assert Counter(r["source"] for r in rows["camera_step.csv"]) == {"camera": 11}
    assert Counter((r["kind"], r["source"]) for r in rows["foot.csv"]) == {("step", "foot"): 9, ("loose", "foot"): 8}
    assert len(rows["camera_crack.csv"]) == 22 and len(rows["camera_slope.csv"]) == 16  # 중복 검출 포함
    with pytest.raises(FormatError):  # id·level이 빈 파일은 일반 읽기로는 통과하지 않는다
        read_events(split_dir / "raw" / "foot.csv")


def test_roundtrip_equals_original(split_dir):
    rows = [r for name in demo.RAW_FILES for r in read_events(split_dir / "raw" / name, raw=True)]
    merged, stats = merge_events(rows)
    assert stats == {"inputs": 66, "pairs": 7, "duplicates_dropped": 19, "events": 40}
    write_events(split_dir / "merged.csv", merged)
    assert read_events(split_dir / "merged.csv") == read_events(split_dir / "events.csv")
    assert (split_dir / "merged.csv").read_bytes() == (split_dir / "events.csv").read_bytes()


def test_cli_merge_with_wildcard(split_dir, tmp_path, capsys):
    """나눈 파일(발끝 기록 포함)을 합치면 events.csv와 foot_traces.csv 모두 원래와 같다."""
    out = tmp_path / "events.csv"
    code = main(["merge", str(split_dir / "raw" / "*.csv"), "-o", str(out), "-c", str(ROOT / "config.yaml")])
    assert code == 0
    assert out.read_bytes() == (split_dir / "events.csv").read_bytes()
    assert (tmp_path / "foot_traces.csv").read_bytes() == (split_dir / "foot_traces.csv").read_bytes()
    printed = capsys.readouterr()
    assert "단차 교차 측정 7쌍" in printed.out and "발끝 기록 8개 지점 연결" in printed.out
    assert "경고" not in printed.err


def test_cli_merge_warns_unmatched_traces(split_dir, tmp_path, capsys):
    raw = read_foot_traces(split_dir / "raw" / demo.RAW_TRACES, raw=True)
    first = raw[0]["t_event"]
    moved = [{**r, "t_event": r["t_event"] + 30.0} if r["t_event"] == first else r for r in raw]  # 한 지점 시각을 어긋나게
    write_foot_traces(tmp_path / "foot_traces_raw.csv", moved, raw=True)
    inputs = [str(split_dir / "raw" / n) for n in demo.RAW_FILES] + [str(tmp_path / "foot_traces_raw.csv")]
    code = main(["merge", *inputs, "-o", str(tmp_path / "out" / "events.csv"), "-c", str(ROOT / "config.yaml")])
    assert code == 0  # 경고만 하고 계속
    printed = capsys.readouterr()
    assert "경고: 짝이 없는 발끝 기록" in printed.err and "짝 없음 1개" in printed.out
    linked = read_foot_traces(tmp_path / "out" / "foot_traces.csv")
    assert len({r["id"] for r in linked}) == 7


# --- 단차 교차 측정 경계값 -----------------------------------------------------------

@pytest.mark.parametrize("dx,merged", [(0.0, True), (0.99, True), (1.0, True), (1.01, False), (2.0, False)])
def test_step_pair_radius_boundary(dx, merged):
    out, stats = merge_events([raw(), foot_step(x=dx, t=1.0)])
    assert stats["pairs"] == (1 if merged else 0)
    assert len(out) == (1 if merged else 2)


def test_step_pair_diagonal_exactly_one_meter():
    out, _ = merge_events([raw(), foot_step(x=0.6, y=0.8)])
    assert len(out) == 1


@pytest.mark.parametrize("dt,merged", [(10.0, True), (10.5, False)])
def test_step_pair_time_window(dt, merged):
    out, _ = merge_events([raw(), foot_step(x=0.2, t=dt)])
    assert len(out) == (1 if merged else 2)


def test_step_pair_fields():
    cam = raw(x=1.0, y=2.0, t=5.0, value=3.7, confidence=0.9, note="연석", image="img/a.jpg")
    foot = foot_step(x=1.3, y=2.2, t=6.0, value=3.9, leg="FL", confidence=0.8, note="연석")
    [e], _ = merge_events([foot, cam])
    assert e["source"] == "camera+foot"
    assert (e["value"], e["value_foot"], e["leg"]) == (3.7, 3.9, "FL")
    assert (e["x"], e["y"], e["t"]) == (1.0, 2.0, 5.0)  # 위치·시각은 카메라 기준
    assert e["confidence"] == 0.9 and e["note"] == "연석" and e["image"] == "img/a.jpg"


def test_step_pairs_are_one_to_one_nearest_first():
    cams = [raw(x=0.0), raw(x=1.6)]
    feet = [foot_step(x=0.8, value=2.0), foot_step(x=1.5, value=3.0)]
    out, stats = merge_events(cams + feet)
    assert stats["pairs"] == 2
    by_x = {e["x"]: e["value_foot"] for e in out}
    assert by_x == {1.6: 3.0, 0.0: 2.0}  # 1.6↔1.5(0.1m)가 먼저, 남은 0.0↔0.8


def test_loose_not_merged_with_camera():
    out, stats = merge_events([raw(), raw(kind="loose", unit="mm", value=4.0, source="foot", leg="RR", x=0.1)])
    assert stats["pairs"] == 0 and len(out) == 2
    assert {e["source"] for e in out} == {"camera", "foot"}


# --- 균열·경사 중복 제거 --------------------------------------------------------------

def crack(**kw):
    return raw(kind="crack", unit="score", **kw)


def test_dedup_keeps_highest_confidence():
    rows = [crack(x=0.0, value=0.6, confidence=0.6), crack(x=0.5, value=0.9, confidence=0.9, t=1),
            crack(x=0.9, value=0.7, confidence=0.7, t=2), crack(x=3.0, value=0.55, confidence=0.55, t=3)]
    out, stats = merge_events(rows)
    assert stats["duplicates_dropped"] == 2
    assert sorted(e["value"] for e in out) == [0.55, 0.9]


@pytest.mark.parametrize("dx,kept", [(1.0, 1), (1.01, 2)])
def test_dedup_radius_boundary(dx, kept):
    rows = [raw(kind="slope", unit="deg", value=5.0, confidence=0.9),
            raw(kind="slope", unit="deg", value=5.2, confidence=0.7, x=dx, t=1)]
    out, _ = merge_events(rows)
    assert len(out) == kept


def test_dedup_only_same_kind():
    rows = [crack(value=0.9, confidence=0.9), raw(kind="slope", unit="deg", value=5.0, confidence=0.5, x=0.2)]
    out, stats = merge_events(rows)
    assert stats["duplicates_dropped"] == 0 and len(out) == 2


# --- 판정·id·좌표·설정 -------------------------------------------------------------

def test_level_recomputed_and_ids_by_time():
    rows = [raw(t=9, value=2.5, level="ok"), raw(t=1, x=50, value=1.2), crack(t=5, x=90, value=0.85)]
    out, _ = merge_events(rows, {**DEFAULT_THRESHOLDS, "step": (1.5, 3.0)})
    assert [(e["id"], e["t"], e["level"]) for e in out] == [
        ("ev_0001", 1, "ok"), ("ev_0002", 5, "danger"), ("ev_0003", 9, "warn")]


def test_latlon_filled_from_geo():
    [e], _ = merge_events([raw(x=100.0, y=0.0)], geo=GeoRef(33.486, 126.4866, 90))
    assert e["lat"] == pytest.approx(33.486, abs=1e-6) and e["lon"] > 126.4866


def test_merge_config():
    assert merge_from_config({}) == MERGE_DEFAULTS
    assert merge_from_config({"merge": {"step_radius_m": 0.5}})["step_radius_m"] == 0.5
    from stepmap.events import load_config
    assert merge_from_config(load_config(ROOT / "config.yaml")) == MERGE_DEFAULTS
    out, _ = merge_events([raw(), foot_step(x=0.8)], merge={"step_radius_m": 0.5})
    assert len(out) == 2



# --- 발끝 기록 연결 -----------------------------------------------------------------------

def trace(t_event, leg="FL", n=3):
    return [{"id": "", "leg": leg, "t": round(-0.01 + i * 0.01, 2), "z_step": 0.0, "z_mean": 0.0, "z_lo": -1.0,
             "z_hi": 1.0, "n_normal": 20, "t_event": t_event} for i in range(n)]


def loose(eid, t, leg="FL"):
    return raw(id=eid, t=t, kind="loose", unit="mm", value=4.0, source="foot", leg=leg)


def test_link_by_time_and_leg_nearest():
    events = [loose("ev_0001", 10.0), loose("ev_0002", 10.3), loose("ev_0003", 50.0, leg="RR")]
    rows = trace(10.25) + trace(9.95) + trace(50.0, leg="FL") + trace(80.0)
    linked, unmatched = link_foot_traces(rows, events)
    ids = sorted({r["id"] for r in linked})
    assert ids == ["ev_0001", "ev_0002"]  # 10.25 → ev_0002(0.05초), 9.95 → ev_0001
    assert {(u["t_event"], u["leg"]) for u in unmatched} == {(50.0, "FL"), (80.0, "FL")}  # 다리가 다르거나 시각이 멀면 짝 없음
    assert [r["t"] for r in linked if r["id"] == "ev_0001"] == sorted(r["t"] for r in linked if r["id"] == "ev_0001")


def test_link_one_trace_per_event_and_window():
    events = [loose("ev_0001", 10.0)]
    linked, unmatched = link_foot_traces(trace(10.1) + trace(10.4), events)
    assert {r["id"] for r in linked} == {"ev_0001"} and len(unmatched) == 1  # 가까운 기록 하나만
    assert link_foot_traces(trace(10.6), events)[0] == []  # 0.5초 밖


def test_link_repeat_step_on_same_block():
    """첫 걸음이 붙은 지점의 다른 발이 2초 안에 다시 밟은 걸음은 같은 블록으로 붙는다."""
    events = [loose("ev_0001", 10.0, leg="FL"), loose("ev_0002", 30.0, leg="FR")]
    rows = trace(10.0) + trace(10.9, leg="RL") + trace(11.0, leg="FL") + trace(13.0, leg="RR") + trace(29.5, leg="RR")
    linked, unmatched = link_foot_traces(rows, events)
    steps = sorted({(r["id"], r["t_event"], r["leg"]) for r in linked})
    assert steps == [("ev_0001", 10.0, "FL"), ("ev_0001", 10.9, "RL")]
    # 같은 발 다시(11.0 FL), 2초 밖(13.0), 첫 걸음보다 앞(29.5)은 짝 없음
    assert {(u["t_event"], u["leg"]) for u in unmatched} == {(11.0, "FL"), (13.0, "RR"), (29.5, "RR")}
    assert [(r["id"], r["t_event"]) for r in linked] == sorted((r["id"], r["t_event"]) for r in linked)  # id·접지 시각 순
