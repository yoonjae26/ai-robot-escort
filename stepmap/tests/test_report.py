import csv
import json
import re
from pathlib import Path

import pytest

from stepmap import demo
from stepmap.cli import main
from stepmap.dashboard import build_payload
from stepmap.events import (
    DEFAULT_THRESHOLDS, ENCODING, criterion_text, display_meters, read_events, read_trajectory,
    round_half_up, slope_fraction,
)
from stepmap.report import CSV_COLUMNS, build_csv_rows, build_html, report_items, summary

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = ("가상", "예시", "샘플", "demo", "mock", "test", "sample")


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    d = tmp_path_factory.mktemp("report")
    demo.generate(d)
    return d, read_events(d / "events.csv"), read_trajectory(d / "trajectory.csv")


@pytest.fixture(scope="module")
def outputs(data):
    d, _, _ = data
    code = main(["report", str(d / "events.csv"), str(d / "trajectory.csv"), "-o", str(d / "out" / "report.html"),
                 "-c", str(ROOT / "config.yaml")])
    assert code == 0
    html = (d / "out" / "report.html").read_text(encoding="utf-8")
    with open(d / "out" / "report.csv", encoding=ENCODING, newline="") as f:
        rows = list(csv.reader(f))
    return html, rows


def level_counts(events):
    """데이터 기준 판정별 건수 (숫자를 테스트에 고정하지 않는다)."""
    return {lv: sum(1 for e in events if e["level"] == lv) for lv in ("danger", "warn", "ok")}


def n_report(events):
    c = level_counts(events)
    return c["danger"] + c["warn"]


# --- 대시보드와 같은 숫자·문구 --------------------------------------------------------

def test_same_numbers_as_dashboard(data):
    _, events, traj = data
    payload = build_payload(events, traj)
    sm = summary(events, traj)
    assert sm["distance_m"] == display_meters(payload["distance_m"]) == 912
    by_level = {lv: sum(1 for e in payload["events"] if e["level"] == lv) for lv in ("danger", "warn", "ok")}
    assert sm["by_level"] == by_level == level_counts(events)
    assert sum(by_level.values()) == len(events)


def test_same_criterion_as_dashboard(data):
    _, events, traj = data
    payload = {e["id"]: e["criterion"] for e in build_payload(events, traj)["events"]}
    for item in report_items(events):
        assert item["criterion"] == payload[item["id"]]


@pytest.mark.parametrize("kind,level,text", [
    ("step", "danger", "휠체어 회피 기준 2cm 이상"),
    ("step", "warn", "주의 기준 1cm 이상 · 휠체어 회피 기준 2cm 미만"),
    ("slope", "danger", "휠체어 회피 기준 1/8(7.13°) 이상"),
    ("slope", "ok", "주의 기준 1/12(4.76°) 미만"),
    ("crack", "warn", "균열 점수 0.5 이상 · 0.8 미만"),
    ("loose", "danger", "접지 후 추가 침하 6mm 이상"),
])
def test_criterion_text(kind, level, text):
    assert criterion_text(kind, level) == text


def test_rounding_helpers():
    assert round_half_up(912.5) == 913 and round_half_up(912.47) == 912 and round(912.5) == 912
    assert slope_fraction(7.13) == "1/8" and slope_fraction(4.76) == "1/12"


# --- 대상·정렬 ---------------------------------------------------------------------

def test_only_danger_and_warn_sorted(data):
    _, events, _ = data
    items = report_items(events)
    c, n = level_counts(events), n_report(events)
    assert len(items) == n and [i["no"] for i in items] == list(range(1, n + 1))
    levels = [i["level"] for i in items]
    assert levels == ["danger"] * c["danger"] + ["warn"] * c["warn"]
    for lv in ("danger", "warn"):
        ratios = [i["ratio"] for i in items if i["level"] == lv]
        assert ratios == sorted(ratios, reverse=True)
    assert items[0]["id"] == "ev_0012" and items[0]["value"] == 4.8  # 단차 4.8cm = 기준의 2.4배


def test_ratio_uses_config_thresholds(data):
    _, events, _ = data
    th = {**DEFAULT_THRESHOLDS, "step": (1.0, 4.0)}
    items = report_items(events, th)
    # 단차 4.8cm는 기준의 1.2배로 내려가고, 흔들림 8.5mm(6mm의 1.42배)가 맨 앞
    assert (items[0]["kind"], items[0]["value"]) == ("loose", 8.5)
    step48 = next(i for i in items if i["id"] == "ev_0012")
    assert step48["ratio"] == pytest.approx(1.2) and step48["criterion"] == "휠체어 회피 기준 4cm 이상"


# --- HTML -------------------------------------------------------------------------

def test_html_summary_and_items(data, outputs):
    _, events, _ = data
    html, _ = outputs
    c = level_counts(events)
    assert "20261020_nohyeong_yeon_A" in html and "제주시 노형동·연동" in html
    assert "2026-10-20 09:00 ~ 09:33 (KST)" in html
    assert "912 m" in html and f"{len(events)}개 (위험 {c['danger']} · 주의 {c['warn']} · 정상 {c['ok']})" in html
    assert html.count('<article class="item') == n_report(events)
    assert "카메라 4.8cm · 발 5.1cm · 앞 오른발(FR) · 차이 0.3cm" in html
    assert re.search(r"<dd>33\.\d{6}, 126\.\d{6}</dd>", html)
    assert '<img' not in html  # 사진이 없으면 사진 영역을 만들지 않는다


def test_html_print_layout_and_offline_figure(data, outputs):
    _, events, _ = data
    html, _ = outputs
    assert "@page { size: A4;" in html
    assert re.search(r"\.item \{[^}]*break-inside: avoid", html)
    assert "<svg class=\"route\"" in html and "http" not in html.split("<svg", 1)[1].split("</svg>")[0].replace(
        "http://www.w3.org/2000/svg", "")
    figure = html.split('<svg class="route"', 1)[1].split("</svg>")[0]
    numbers = [int(n) for n in re.findall(r'class="no-text[^"]*">(\d+)</text>', figure)]
    assert sorted(numbers) == list(range(1, n_report(events) + 1))
    assert "<script" not in html


def test_no_forbidden_words(outputs):
    html, rows = outputs
    text = (html + json.dumps(rows, ensure_ascii=False)).lower()
    for w in FORBIDDEN:
        assert w not in text, w


# --- 이스케이프 ----------------------------------------------------------------------

def test_escaping(data):
    _, events, traj = data
    bad = [dict(e) for e in events]
    target = next(e for e in bad if e["level"] == "danger")
    target.update(note='<script>alert(1)</script> "x" & y', id="=cmd|' /C calc'!A0")
    photos = {target["id"]: {"src": 'photos/a.jpg" onerror="alert(1)', "w": 10, "h": 10, "mark": None, "overlay": ""}}
    html = build_html(bad, traj, photos=photos)
    assert "<script>alert" not in html and "&lt;script&gt;alert(1)&lt;/script&gt; &quot;x&quot; &amp; y" in html
    assert 'onerror="alert' not in html and 'src="photos/a.jpg&quot; onerror=&quot;alert(1)"' in html
    rows = build_csv_rows(bad, photos=photos)
    row = next(r for r in rows if r[-1].endswith("calc'!A0"))
    assert row[-1].startswith("'=")  # CSV 수식 주입 방지


# --- CSV ---------------------------------------------------------------------------

def test_csv_rows(data, outputs):
    _, events, _ = data
    _, rows = outputs
    assert rows[0] == CSV_COLUMNS
    body, n = rows[1:], n_report(events)
    assert len(body) == n and [r[0] for r in body] == [str(i) for i in range(1, n + 1)]
    assert {r[1] for r in body} <= {"위험", "주의"}  # 신고서 CSV는 위험·주의만
    first = dict(zip(CSV_COLUMNS, body[0]))
    assert first["판정"] == "위험" and first["카메라 값"] == "4.8" and first["발 값"] == "5.1" and first["차이"] == "0.3"
    assert first["기준"] == "휠체어 회피 기준 2cm 이상" and first["측정 시각"] == "2026-10-20T09:11:00+09:00"
    assert re.fullmatch(r"\d+\.\d{6}", first["위도"]) and re.fullmatch(r"\d+\.\d{6}", first["경도"])


def test_cli_report_hints_dashboard_without_link(tmp_path, capsys):
    """대시보드를 신고서보다 먼저 만들면 '신고서 열기' 버튼이 없다 → report가 map을 다시 실행하라고 알린다."""
    demo.generate(tmp_path)
    ev, tr, out = str(tmp_path / "events.csv"), str(tmp_path / "trajectory.csv"), tmp_path / "out"
    assert main(["map", ev, tr, "-o", str(out / "dashboard.html")]) == 0
    assert main(["report", ev, tr, "-o", str(out / "report.html")]) == 0
    assert "map을 다시 실행하면 연결됩니다" in capsys.readouterr().out
    assert main(["map", ev, tr, "-o", str(out / "dashboard.html")]) == 0
    assert '"report":"report.html"' in (out / "dashboard.html").read_text(encoding="utf-8")
    assert main(["report", ev, tr, "-o", str(out / "report.html")]) == 0
    assert "map을 다시 실행" not in capsys.readouterr().out
