from collections import Counter

import pytest

from stepmap import demo
from stepmap.events import judge, path_length, read_events, read_trajectory


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    d = tmp_path_factory.mktemp("demo")
    demo.generate(d)
    return d


def test_files_pass_format_check(out):
    # read_* 는 형식 검사를 통과해야 성공한다
    assert read_trajectory(out / "trajectory.csv")
    assert read_events(out / "events.csv")


def test_event_counts(out):
    ev = read_events(out / "events.csv")
    assert len(ev) == 40
    assert Counter(e["kind"] for e in ev) == {"step": 13, "slope": 8, "crack": 11, "loose": 8}


def test_special_cases(out):
    ev = read_events(out / "events.csv")
    steps = [e for e in ev if e["kind"] == "step"]
    assert Counter(e["source"] for e in steps) == {"camera+foot": 7, "camera": 4, "foot": 2}
    for e in steps:
        if e["source"] == "camera+foot":
            assert 0.2 - 1e-9 <= abs(e["value"] - e["value_foot"]) <= 0.3 + 1e-9
    loose = [e for e in ev if e["kind"] == "loose"]
    assert all(e["source"] == "foot" and e["leg"] for e in loose)
    assert sum("외관 정상" in e["note"] for e in loose) == 4


def test_levels_from_judge_and_all_levels_present(out):
    ev = read_events(out / "events.csv")
    for e in ev:
        assert e["level"] == judge(e["kind"], e["value"])
    for kind in ("step", "slope", "crack"):
        assert {e["level"] for e in ev if e["kind"] == kind} == {"ok", "warn", "danger"}


def test_value_ranges_follow_tables(out):
    """값 범위는 demo.py 표에서 계산한다 (숫자를 테스트에 고정하지 않는다)."""
    ev = read_events(out / "events.csv")
    rng = lambda k: [e["value"] for e in ev if e["kind"] == k]
    table = {"slope": [v for _, v, _ in demo.SLOPES], "crack": [v for _, v, _ in demo.CRACKS],
             "loose": [v for _, v, _, _ in demo.LOOSE]}
    for kind, values in table.items():
        assert (min(rng(kind)), max(rng(kind))) == (min(values), max(values))


def test_realistic_level_ratio(out):
    """위험은 종류별 1개, 위험·주의 합계는 전체의 30% 이하."""
    ev = read_events(out / "events.csv")
    danger = Counter(e["kind"] for e in ev if e["level"] == "danger")
    assert danger == {"step": 1, "slope": 1, "crack": 1, "loose": 1}
    flagged = sum(e["level"] != "ok" for e in ev)
    assert flagged / len(ev) <= 0.3
    # 사진 연결 대상은 종류별 유일한 위험 지점
    assert {(e["kind"], e["value"]) for e in ev if e["level"] == "danger" and e["kind"] != "slope"} == {
        ("step", 4.8), ("crack", 0.91), ("loose", 8.5)}


def test_trajectory_shape(out):
    traj = read_trajectory(out / "trajectory.csv")
    assert 600 <= path_length(traj) <= 1000
    assert traj[0]["x"] == pytest.approx(0, abs=0.15) and traj[0]["y"] == pytest.approx(0, abs=0.15)
    # 제주시 노형동·연동 일대
    for p in traj:
        assert 33.484 < p["lat"] < 33.492 and 126.485 < p["lon"] < 126.492


def test_events_on_trajectory(out):
    traj = read_trajectory(out / "trajectory.csv")
    for e in read_events(out / "events.csv"):
        near = min((p["x"] - e["x"]) ** 2 + (p["y"] - e["y"]) ** 2 for p in traj) ** 0.5
        assert near < 0.5


def test_deterministic(tmp_path, out):
    demo.generate(tmp_path)
    for name in ("trajectory.csv", "events.csv"):
        assert (tmp_path / name).read_bytes() == (out / name).read_bytes()
