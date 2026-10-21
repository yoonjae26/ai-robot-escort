import json
import re
from pathlib import Path

import pytest

from stepmap import demo
from stepmap.cli import main
from stepmap.dashboard import near_visual_issues, write_dashboard
from stepmap.events import (
    FOOT_TRACE_COLUMNS, FormatError, extra_sink, group_foot_traces, read_events, read_foot_traces,
    settle_index, stance_sink, validate_foot_traces, write_foot_traces,
)

ROOT = Path(__file__).resolve().parents[1]


def row(**kw):
    r = {"id": "ev_0001", "leg": "FL", "t": 0.0, "z_step": 0.0, "z_mean": 0.0, "z_lo": -1.0, "z_hi": 1.0, "n_normal": 20,
         "t_event": None}
    r.update(kw)
    return r


def synthetic(extra=4.0, normal_sink=2.0, landing=6.0):
    """접지 뒤 0.05초 동안 landing mm 더 내려와 멈추고, 0.1~0.25초에 체중이 실리며 내려간다."""
    ts = [round(-0.1 + i * 0.01, 2) for i in range(81)]  # -0.1 ~ 0.7

    def curve(sink):
        out = []
        for t in ts:
            z = 10.0 if t < 0 else 4.0 + landing * max(0.0, 1 - t / 0.05) ** 2
            if t >= 0.1:
                z -= sink * min(1.0, (t - 0.1) / 0.15)
            if t >= 0.5:
                z += 20 * (t - 0.5) / 0.2  # 다음 발 들기
            out.append(round(z, 3))
        return out
    return {"t": ts, "z_step": curve(normal_sink + extra), "z_mean": curve(normal_sink)}


# --- 형식 검사 --------------------------------------------------------------------

def test_valid_and_roundtrip(tmp_path):
    rows = [row(t=-0.01), row(t=0.0), row(t=0.01)]
    assert validate_foot_traces(rows) == []
    write_foot_traces(tmp_path / "f.csv", rows)
    back = read_foot_traces(tmp_path / "f.csv")
    assert [list(r) for r in back][0] == FOOT_TRACE_COLUMNS and back == rows


@pytest.mark.parametrize("bad,msg", [
    ({"leg": "XX"}, "leg"), ({"z_lo": 5.0}, "z_lo"), ({"n_normal": 0}, "n_normal"), ({"z_step": "a"}, "숫자"),
])
def test_invalid_rows(bad, msg):
    errors = validate_foot_traces([row(t=-0.01), row(**bad), row(t=0.01)])
    assert any(msg in m for m in errors), errors


def test_time_order_and_contact_included():
    assert any("시간순" in m for m in validate_foot_traces([row(t=0.02), row(t=0.01)]))
    assert any("t=0" in m for m in validate_foot_traces([row(t=0.1), row(t=0.2)]))
    assert any("leg" in m for m in validate_foot_traces([row(t=-0.01), row(t=0.0, leg="FR")]))


def test_missing_column_rejected(tmp_path):
    p = tmp_path / "f.csv"
    p.write_text("id,leg,t,z_step\nev_0001,FL,0,0\n", encoding="utf-8")
    with pytest.raises(FormatError, match="z_mean"):
        read_foot_traces(p)


# --- 추가 침하 계산 -------------------------------------------------------------------

def test_extra_sink_excludes_landing_descent():
    tr = synthetic(extra=4.0, normal_sink=2.0, landing=6.0)
    r = extra_sink(tr)
    assert r["extra_mm"] == pytest.approx(4.0, abs=0.01)
    assert r["sink_mean_mm"] == pytest.approx(2.0, abs=0.01)
    assert 0 < r["t_settle_step"] <= 0.06  # 접지 직후 내려오는 구간(0~0.05초)이 끝난 뒤
    # 접지 순간(t=0)부터 쟀다면 내려온 6mm가 섞여 내려간 양이 커진다
    i0 = tr["t"].index(0.0)
    assert tr["z_step"][i0] - min(tr["z_step"][i0:]) > r["sink_step_mm"] + 5


def test_contact_diff_and_settle_index():
    tr = synthetic(extra=0.0)
    tr["z_step"] = [z + 1.5 for z in tr["z_step"]]  # 이번 걸음이 1.5mm 높게 접지
    r = extra_sink(tr)
    assert r["contact_diff_mm"] == pytest.approx(1.5, abs=0.01) and r["extra_mm"] == pytest.approx(0.0, abs=0.01)
    i = settle_index(tr["t"], tr["z_mean"])
    assert tr["t"][i] >= 0 and stance_sink(tr["t"], tr["z_mean"])[2] == i


# --- 데모 데이터 ------------------------------------------------------------------------

@pytest.fixture(scope="module")
def demo_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("traces")
    demo.generate(d)
    return d


def test_demo_traces_match_values(demo_dir):
    events = {e["id"]: e for e in read_events(demo_dir / "events.csv")}
    traces = group_foot_traces(read_foot_traces(demo_dir / "foot_traces.csv"))
    loose = {i for i, e in events.items() if e["kind"] == "loose"}
    assert set(traces) == loose and len(loose) == 8  # 흔들림 지점만, 모두 기록 있음
    for i, tr in traces.items():
        e, r = events[i], extra_sink(tr)
        assert r["extra_mm"] == pytest.approx(e["value"], abs=0.05), i  # 그래프에서 읽히는 추가 침하 = value
        assert abs(r["contact_diff_mm"]) <= 0.6  # 접지 높이는 평소와 비슷
        assert tr["leg"] == e["leg"] and 18 <= tr["n_normal"] <= 26
        assert -0.31 <= tr["t"][0] <= -0.29 and 0.79 <= tr["t"][-1] <= 0.83
    assert round(extra_sink(traces["ev_0014"])["extra_mm"], 1) == 8.5


def test_demo_traces_baseline_is_normal_stance(demo_dir):
    tr = next(iter(group_foot_traces(read_foot_traces(demo_dir / "foot_traces.csv")).values()))
    stance = [z for t, z in zip(tr["t"], tr["z_mean"]) if 0.06 <= t <= 0.42]
    assert abs(sum(stance) / len(stance)) < 0.5  # 평소 걸음이 딛고 있을 때 평균 높이 ≈ 0mm


# --- 대시보드 ---------------------------------------------------------------------------

def payload_of(html: str) -> dict:
    return json.loads(re.search(r'<script id="stepmap-data" type="application/json">(.*?)</script>', html, re.S).group(1))


def test_dashboard_trace_payload_and_default_path(demo_dir):
    html = write_dashboard(demo_dir / "events.csv", demo_dir / "trajectory.csv", demo_dir / "d.html").read_text(encoding="utf-8")
    ev = {e["id"]: e for e in payload_of(html)["events"]}
    assert ev["ev_0014"]["trace"]["extra"] == pytest.approx(8.5, abs=0.05)
    assert ev["ev_0014"]["trace"]["n"] >= 18 and len(ev["ev_0014"]["trace"]["t"]) == len(ev["ev_0014"]["trace"]["step"])
    assert all("trace" not in e for e in ev.values() if e["kind"] != "loose")
    assert ev["ev_0014"]["near_visual"] == []


def test_dashboard_without_traces_file(demo_dir, tmp_path):
    html = write_dashboard(demo_dir / "events.csv", demo_dir / "trajectory.csv", tmp_path / "d.html",
                           traces_path=tmp_path / "none.csv").read_text(encoding="utf-8")
    assert all(e.get("trace") is None for e in payload_of(html)["events"])
    assert "발끝 기록 없음" in html


def test_cli_map_traces_option(demo_dir, tmp_path):
    rows = [r for r in read_foot_traces(demo_dir / "foot_traces.csv") if r["id"] != "ev_0014"]
    write_foot_traces(tmp_path / "part.csv", rows)
    code = main(["map", str(demo_dir / "events.csv"), str(demo_dir / "trajectory.csv"), "-o", str(tmp_path / "m.html"),
                 "--traces", str(tmp_path / "part.csv"), "-c", str(ROOT / "config.yaml")])
    assert code == 0
    ev = {e["id"]: e for e in payload_of((tmp_path / "m.html").read_text(encoding="utf-8"))["events"]}
    assert ev["ev_0014"]["trace"] is None and ev["ev_0031"]["trace"] is not None


def test_near_visual_issues():
    loose = {"id": "L", "kind": "loose", "level": "danger", "x": 0.0, "y": 0.0}
    events = [loose,
              {"id": "a", "kind": "step", "level": "danger", "x": 0.8, "y": 0.0},
              {"id": "b", "kind": "crack", "level": "warn", "x": 0.0, "y": 0.5},
              {"id": "c", "kind": "slope", "level": "ok", "x": 0.1, "y": 0.0},     # 정상은 제외
              {"id": "d", "kind": "step", "level": "danger", "x": 1.2, "y": 0.0}]  # 1m 밖
    assert near_visual_issues(loose, events) == ["b", "a"]


def test_physical_page_structure(demo_dir):
    html = write_dashboard(demo_dir / "events.csv", demo_dir / "trajectory.csv", demo_dir / "d.html").read_text(encoding="utf-8")
    for sid in ("p-crumb", "p-k-all", "p-k-flag", "p-k-hidden", "p-k-ok", "p-list", "p-detail"):
        assert f'id="{sid}"' in html, sid
    for text in ("발이 땅에 닿은 뒤 시간 [초]", "발끝 높이 [mm]", "평소 걸음 범위", "평소 걸음 평균", "이번 걸음",
                 "접지 높이: 평소보다", "체중이 실린 뒤 추가 침하", "위험 기준", "관절 각도 → 발끝 위치(정기구학), IMU 중력 정렬, 평소 걸음 대비",
                 "카메라로는 이상 없음", "외관 검사 비교", "평소 걸음 수"):
        assert text in html, text
    assert "stroke-dasharray:6 4" in html  # 평균은 점선 (색만으로 구분하지 않음)
    assert "다음 단계에서 구성" not in html  # 네 페이지 모두 구성됨


# --- 모듈 출력(raw)과 t_event ------------------------------------------------------------

def test_raw_traces_need_t_event_when_id_empty(tmp_path):
    raw = [row(id="", t=-0.01, t_event=100.0), row(id="", t=0.0, t_event=100.0), row(id="", t=0.01, t_event=100.0)]
    assert validate_foot_traces(raw, raw=True) == []
    assert any("id 빈칸" in m for m in validate_foot_traces(raw))  # 최종 파일은 id 필요
    assert any("t_event" in m for m in validate_foot_traces([row(id="", t=0.0)], raw=True))
    write_foot_traces(tmp_path / "raw.csv", raw, raw=True)
    assert read_foot_traces(tmp_path / "raw.csv", raw=True) == raw


def test_file_without_t_event_column_is_read(tmp_path):
    p = tmp_path / "old.csv"
    lines = ["id,leg,t,z_step,z_mean,z_lo,z_hi,n_normal", "ev_0001,FL,0,0,0,-1,1,20"]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    [r] = read_foot_traces(p)
    assert r["t_event"] is None
