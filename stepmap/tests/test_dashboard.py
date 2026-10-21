import json
import math
import re

import pytest

from stepmap import demo
from stepmap.dashboard import LEAFLET_VERSION, MissingLatLon, build_html, write_dashboard
from stepmap.events import (DEFAULT_THRESHOLDS, EVENT_COLUMNS, criterion_text, display_meters, exceed_ratio, path_length,
                            read_events, read_trajectory)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    d = tmp_path_factory.mktemp("dash")
    demo.generate(d)
    demo.generate_history(d)  # 지난 점검 4회: <d>/history/<날짜>/
    write_dashboard(d / "events.csv", d / "trajectory.csv", d / "dashboard.html")
    return d


@pytest.fixture(scope="module")
def page(built):
    return (built / "dashboard.html").read_text(encoding="utf-8")


def embedded(page):
    m = re.search(r'<script id="stepmap-data" type="application/json">(.*?)</script>', page, re.S)
    return json.loads(m.group(1))


def test_data_embedded_with_latlon(built, page):
    data = embedded(page)
    assert len(data["events"]) == 40
    assert len(data["trajectory"]) == len(read_trajectory(built / "trajectory.csv"))
    assert all(-90 <= lat <= 90 and -180 <= lon <= 180 for lat, lon in data["trajectory"])
    assert all(e["lat"] and e["lon"] for e in data["events"])
    assert data["session"] == demo.SESSION


def test_leaflet_pinned_and_attribution(page):
    assert f"leaflet@{LEAFLET_VERSION}/dist/leaflet.js" in page
    assert 'integrity="sha256-' in page
    assert "tile.openstreetmap.org" not in page  # Referer 없는 file:// 요청을 거부하는 서버
    assert "tile.opentopomap.org" in page
    assert "basemaps.cartocdn.com" not in page  # 키 없는 요청에 워터마크 타일
    assert "OpenStreetMap</a> contributors, SRTM" in page and "OpenTopoMap</a>" in page and "CC-BY-SA" in page
    assert "--tile-filter: grayscale(1) invert(1)" in page  # 다크 모드
    assert 'setPosition("bottomright")' in page



def test_map_background_toggle(page):
    """지도 배경은 페이지 테마와 따로: 기본 밝은 지도, 브라우저에 기억, 어두운 지도는 네이비 톤."""
    assert 'id="mapcard" data-map="light"' in page  # 기본: 밝은 지도
    assert '<button type="button" data-map="light" aria-pressed="true">밝은 지도</button>' in page
    assert '<button type="button" data-map="dark" aria-pressed="false">어두운 지도</button>' in page
    assert 'const MAP_KEY = "stepmap-map"' in page
    light = page.split('.mapcard[data-map="light"] {', 1)[1].split("}", 1)[0]
    assert "--map-bg: #EEF2F7" in light and "--map-text: #0F1A2E" in light
    assert "--m-ring: #0B1220" in light and "--m-warn: #A35F00" in light  # 진한 네이비 테두리, 진한 호박색
    assert "var(--m-${e.level})" in page and "var(--m-ring)" in page  # 마커는 지도 배경별 색을 쓴다


def test_home_no_route_drawn_and_session(page):
    """종합 현황 지도에는 이동 경로·출발·도착을 그리지 않는다 (지도·평면 지도 모두). 거리 계산과 범위용 데이터는 남긴다."""
    script = page.split("<script>", 1)[1]
    home_map = script.split("function startTiles() {", 1)[1].split("function fallback(reason) {", 1)[0]
    assert "L.polyline" not in home_map  # 점검 이력 지도(그날 경로)와 다르게 종합 현황 지도는 경로를 그리지 않는다
    for gone in ("route-key", "ep-icon", "endSides", "END_LABEL"):
        assert gone not in page, gone
    legend = script.split("종합 현황: 범례", 1)[1].split("// ----", 1)[0]
    assert "이동 경로" not in legend and "lvBadge" not in legend  # 범례: 경로 항목 없음, 판정은 필터 버튼으로
    plane = script.split("function startPlane() {", 1)[1].split("function renderMap() {", 1)[0]
    assert "<polyline" not in plane  # 평면 지도도 경로 선 없음 (발끝 높이 그래프의 선은 다른 페이지)
    assert "DATA.trajectory_xy" in script  # 지점이 없을 때만 쓰는 범위 대비
    # 지도 범위: 전체 측정 지점 기준 한 번 (판정 필터와 무관)
    assert "L.latLngBounds(DATA.events.length ? DATA.events.map((e) => [e.lat, e.lon]) : DATA.trajectory)" in page
    assert "map.fitBounds(bounds.pad(0.35))" in page
    assert "const pts = DATA.events.length ? DATA.events.map((e) => [e.x, e.y]) : DATA.trajectory_xy;" in page
    assert '$("s-session").setAttribute("title", DATA.session || "")' in page
    assert ".session dd#s-session { overflow: hidden; white-space: nowrap; text-overflow: ellipsis;" in page
    assert "@media (min-width: 1260px) and (min-height: 700px)" in page  # 데스크톱: 지도 = 남은 높이


def level_buttons(page):
    return re.findall(r'<button type="button" class="lv-btn" data-level="(\w+)" aria-pressed="(\w+)">'
                      r'<span class="dot" aria-hidden="true"></span>(\S+) <span class="n">(\d+)</span></button>', page)


def test_level_filter_buttons_and_counts(page):
    """범례의 판정 필터: button 3개 (위험·주의·정상), 각각 색 점 + 이름 + 전체 개수."""
    assert [(lv, name, int(n)) for lv, _, name, n in level_buttons(page)] == [
        ("danger", "위험", 4), ("warn", "주의", 5), ("ok", "정상", 31)]
    assert '<div class="lv-filter" id="lv-filter" role="group" aria-label="판정별 지점 보기">' in page
    for lv, color in (("danger", "#F25F5C"), ("warn", "#F5B841"), ("ok", "#2BB673")):
        assert f"--{lv}: {color}" in page
    # 셋 다 끄면 안내, 클러스터·목록은 보이는 지점만, 브라우저 저장소는 쓰지 않는다
    assert '<div class="map-empty" id="map-empty" role="status" hidden>표시할 지점이 없어요</div>' in page
    assert '$("map-empty").hidden = LEVELS.some((l) => shown[l]);' in page
    assert page.count("shownEvents().map(") == 2  # Leaflet 지도·평면 지도 모두
    setter = page.split("function setShown(lv, on) {", 1)[1].split("\n  }", 1)[0]
    assert "localStorage" not in setter and "sessionStorage" not in setter and "fitBounds" not in setter


def test_level_filter_initial_pressed(page):
    """처음 HTML: 위험만 켜짐(aria-pressed="true"), 주의·정상은 꺼짐."""
    assert {lv: pressed for lv, pressed, _, _ in level_buttons(page)} == {"danger": "true", "warn": "false", "ok": "false"}
    assert 'b.getAttribute("aria-pressed") === "true"' in page  # JS도 처음 상태를 HTML에서 읽는다


def test_plane_fallback_embedded(built, page):
    data = embedded(page)
    assert len(data["trajectory_xy"]) == len(data["trajectory"])
    assert all("x" in e and "y" in e for e in data["events"])
    # 타일 실패·대체 이미지·Leaflet 미로딩 모두 평면 지도로 전환
    for reason in ('fallback("tileerror")', 'fallback("placeholder")', 'fallback("leaflet")', 'fallback("timeout")'):
        assert reason in page


def test_marker_shapes_and_level_colors(page):
    for kind in ("step", "slope", "crack", "loose"):
        assert f"{kind}:" in page
    for level in ("danger", "warn", "ok"):
        assert f"--{level}:" in page


def test_no_forbidden_words(page):
    for word in ("가상", "예시", "샘플", "demo", "mock", "test", "sample"):
        assert word.lower() not in page.lower(), word


def test_missing_latlon_raises(tmp_path):
    demo.generate(tmp_path)
    events = read_events(tmp_path / "events.csv")
    traj = read_trajectory(tmp_path / "trajectory.csv")
    traj[0]["lat"] = traj[0]["lon"] = None
    with pytest.raises(MissingLatLon):
        build_html(events, traj)


def test_screen_sections(page):
    for sid in ("nav", "s-session", "s-time", "s-area", "s-robot", "theme-toggle",
                "page-home", "page-visual", "page-physical", "page-history",
                "k-dist", "k-visual", "k-loose", "k-ok", "map", "plane", "retry", "legend", "dpanel"):
        assert f'id="{sid}"' in page, sid
    assert "지도 다시 불러오기" in page
    assert "휠체어 회피 기준" in page


def test_four_pages_with_hash_links(page):
    # 사이드바 링크 4개 (설정 메뉴 없음), 처음엔 종합 현황만 보인다
    assert re.findall(r'<a href="#(\w+)" data-page="\w+">', page) == ["home", "visual", "physical", "history"]
    for title in ("종합 현황", "외관 검사", "물리적 안정성 검사", "점검 이력"):
        assert f">{title}<" in page
    assert '<section class="page" id="page-home" data-page="home"' in page
    for p in ("visual", "physical", "history"):
        assert re.search(rf'<section class="page" id="page-{p}"[^>]*hidden>', page), p
    assert "다음 단계에서 구성" not in page  # 네 페이지 모두 구성됨
    assert 'addEventListener("hashchange", route)' in page  # 뒤로 가기
    assert "설정" not in re.search(r'<nav class="nav".*?</nav>', page, re.S).group(0)


def test_click_rule_and_theme_default(page):
    # 흔들림은 물리적 안정성, 나머지는 외관 검사 (종합 현황 상세 패널의 "자세히 보기")
    assert 'const pageFor = (e) => (e.kind === "loose" ? "physical" : "visual");' in page
    assert "const detailHref = (e) => `#${pageFor(e)}/${e.id}`;" in page
    assert '<html lang="ko" data-theme="dark">' in page and ':root[data-theme="light"]' in page
    assert "stroke-dasharray:3.4 2.4" in page  # 흔들림 마커 점선 고리


def test_session_meta_and_ratio(tmp_path):
    demo.generate(tmp_path)
    out = write_dashboard(tmp_path / "events.csv", tmp_path / "trajectory.csv", tmp_path / "d.html",
                          meta={"area": "제주시 노형동·연동", "robot": "Unitree Go2 EDU"})
    data = embedded(out.read_text(encoding="utf-8"))
    traj = read_trajectory(tmp_path / "trajectory.csv")
    assert (data["area"], data["robot"], data["t1"]) == ("제주시 노형동·연동", "Unitree Go2 EDU", traj[-1]["t"])
    flagged = sorted((e for e in data["events"] if e["level"] != "ok"), key=lambda e: -e["ratio"])
    assert flagged and all(e["ratio"] > 0 for e in flagged)


def test_payload_summary_and_thresholds(tmp_path):
    demo.generate(tmp_path)
    events = read_events(tmp_path / "events.csv")
    traj = read_trajectory(tmp_path / "trajectory.csv")
    data = embedded(build_html(events, traj, {**DEFAULT_THRESHOLDS, "step": (1.5, 3.0)}))
    assert data["t0"] == traj[0]["t"]
    assert 600 <= data["distance_m"] <= 1000
    assert data["thresholds"]["step"] == [1.5, 3.0]
    assert data["thresholds"]["slope"] == list(DEFAULT_THRESHOLDS["slope"])


def test_data_strings_not_injected_as_html(page):
    # 데이터 문자열(비고·ID 등)은 textContent/setAttribute로만 넣는다
    script = page.split('<script>', 1)[1]
    for line in script.splitlines():
        if "innerHTML" in line:
            assert not re.search(r"\.(note|id|session|image)\b|label\(|tipLines", line), line


def test_card_distance_is_path_length_rounded_once(built, page):
    """카드 거리 = path_length를 정수로 반올림한 값. 데이터에는 반올림 없이 넣고 화면에서 한 번만."""
    data = embedded(page)
    exact = path_length(read_trajectory(built / "trajectory.csv"))
    assert data["distance_m"] == exact
    # 화면 표시는 공용 함수 putDistance의 Math.round 한 번 (반올림을 두 번 하면 912.47 → 912.5 → 913).
    # 종합 현황 KPI와 점검 이력 요약이 같은 함수를 쓴다
    assert "node.textContent = Math.round(meters).toLocaleString" in page
    assert 'putDistance($("k-dist"), DATA.distance_m)' in page
    assert 'putDistance($("h-k-dist"), i >= 0 ? DATES[i].meters : DATA.distance_m)' in page  # 점검 이력: display_meters 값
    assert page.count("Math.round(DATA.distance_m)") == 0
    card = math.floor(data["distance_m"] + 0.5)  # JS Math.round와 같은 규칙
    assert card == math.floor(exact + 0.5) == 912


def test_visual_page_structure(page):
    for sid in ("v-crumb", "v-tabs", "v-ok", "v-list", "v-detail"):
        assert f'id="{sid}"' in page, sid
    assert '<a href="#home">종합 현황 지도</a> ›' in page
    # 대상: 흔들림 제외, 정렬은 종합 현황 목록과 같은 순서
    assert 'DATA.events.filter((e) => e.kind !== "loose").sort(byIssueOrder)' in page
    assert "b.ratio - a.ratio" in page
    for text in ("깊이 카메라 바닥 평면 대비 높이 차", "발 접지 높이 차", "깊이 카메라 바닥 평면 기울기",
                 "RGB 영상 균열 검출 점수", "신고서에 포함됨", "사진 없음", "지도에서 위치 보기", "두 측정 차이"):
        assert text in page, text
    assert 'if (e.kind !== "crack") crit.append' in page  # 균열은 배수 표시 안 함
    assert "location.hash = `#home/${e.id}`" in page


def test_spiderfy_at_max_zoom(page):
    assert "function spiderfy(g)" in page
    assert "map.getZoom() >= map.getMaxZoom()" in page and "클릭 → 펼치기" in page


def test_visual_targets_match_data(built, page):
    data = embedded(page)
    visual = [e for e in data["events"] if e["kind"] != "loose"]
    assert visual and all(e["kind"] in ("step", "slope", "crack") for e in visual)
    assert any(e["kind"] == "step" and e["source"] == "foot" for e in visual)  # 발로만 잡은 단차 포함


# --- 점검 이력 --------------------------------------------------------------------------

def test_history_page_structure(page):
    for sid in ("h-dates", "h-chips", "h-cal-btn", "h-cal", "h-kind", "h-level", "h-source", "h-csv", "h-report",
                "h-report-note", "h-k-dist", "h-k-danger", "h-k-warn", "h-k-ok", "h-bars", "h-points"):
        assert f'id="{sid}"' in page, sid
    for gone in ("h-session", "h-sessions", "h-k-all", "h-ses-title", "kpis-5"):  # 세션 필터·표, 측정 지점 KPI 없음
        assert gone not in page, gone
    assert "CSV 다운로드" in page and "신고서 열기" in page and "PDF로 저장" in page
    for label in ("판정", "종류", "값", "기준", "측정 방식", "위도·경도", "시각", "보기"):
        assert f'label: "{label}"' in page, label
    assert 'const SOURCE = { camera: "카메라", foot: "발", "camera+foot": "교차" };' in page
    assert '<small>카메라</small>' in page and "카메라: 단차·경사·균열" not in page  # KPI 보조 라벨 짧게


def test_history_csv_cells_match_events_csv(built, page):
    """CSV 다운로드는 칸 문자열을 그대로 이어 붙인다: 필터 없이 내려받으면 events.csv와 바이트까지 같다."""
    data = embedded(page)
    assert data["csv_columns"] == EVENT_COLUMNS

    def q(v):  # 화면 쪽 csvText와 같은 규칙 (Python csv 모듈의 QUOTE_MINIMAL)
        return '"' + v.replace('"', '""') + '"' if any(ch in v for ch in ',"\r\n') else v
    lines = [data["csv_columns"]] + [e["csv"] for e in data["events"]]
    text = "﻿" + "\r\n".join(",".join(q(v) for v in r) for r in lines) + "\r\n"
    assert text.encode("utf-8") == (built / "events.csv").read_bytes()
    assert r'"\ufeff" + lines.join("\r\n")' in page


def test_history_report_link_only_when_report_exists(built, tmp_path):
    out = tmp_path / "d.html"
    no = embedded(write_dashboard(built / "events.csv", built / "trajectory.csv", out).read_text(encoding="utf-8"))
    assert no["report"] is None  # 같은 폴더에 report.html이 없으면 버튼을 숨긴다
    (tmp_path / "report.html").write_text("<!doctype html>", encoding="utf-8")
    yes = embedded(write_dashboard(built / "events.csv", built / "trajectory.csv", out).read_text(encoding="utf-8"))
    assert yes["report"] == "report.html"


# --- 종합 현황: 지도 옆 상세 패널 ------------------------------------------------------------

def test_home_detail_panel_replaces_issue_list(page):
    """위험·주의 목록 박스 대신 지도 옆 상세 패널. 마커를 누르면 #home/<id>로 패널을 연다."""
    assert '<aside class="dpanel" id="dpanel" aria-label="지점 상세"></aside>' in page
    for gone in ('id="issue-list"', 'id="issues-count"', "위험·주의 지점"):
        assert gone not in page, gone
    assert "location.replace(`#home/${e.id}`)" in page  # 페이지 이동 대신 같은 페이지에서 선택
    assert "지도에서 지점을 누르면 사진과 근거가 여기에 표시돼요" in page
    assert 'function closePanel() { location.replace("#home"); }' in page
    assert 'if (state.page === "home" && state.sel && !document.querySelector("dialog[open]")) closePanel();' in page  # Esc
    assert "byId[state.sel.id].level === lv) closePanel();" in page  # 필터로 숨기면 닫기
    assert '.home-grid { display: grid; grid-template-columns: minmax(0, 1fr) 380px;' in page
    assert "@media (max-width: 1259px)" in page
    assert "state.map.invalidateSize({ animate: false });  // 패널" in page
    assert "stroke:#FFFFFF;stroke-width:3" in page  # 선택된 마커: 흰색 3px 링


def test_home_detail_data_embedded(built, page):
    """패널이 쓰는 지점별 상세(사진 경로, criterion_text, exceed_ratio, 위도·경도)가 페이지에 들어간다."""
    data = embedded(page)
    events = {e["id"]: e for e in read_events(built / "events.csv")}
    for d in data["events"]:
        e = events[d["id"]]
        assert d["criterion"] == criterion_text(e["kind"], e["level"], DEFAULT_THRESHOLDS)
        assert d["ratio"] == round(exceed_ratio(e["kind"], e["level"], e["value"], DEFAULT_THRESHOLDS), 4)
        assert (d["lat"], d["lon"]) == (e["lat"], e["lon"])
        if d["photo"]:  # 사진 사본 경로 (원본이 있는 지점만)
            assert e["image"] and d["photo"]["src"].startswith("photos/") and d["photo"]["src"] in page
    assert "Number(e.lat).toFixed(6)" in page and "Number(e.lon).toFixed(6)" in page


def test_home_detail_link_targets(page):
    """"자세히 보기": 흔들림은 #physical/<id>, 나머지는 #visual/<id>."""
    data = embedded(page)
    panel = page.split("function renderPanel() {", 1)[1].split("\n  }\n", 1)[0]
    assert 'el("a", "btn primary", "자세히 보기")' in panel and "more.href = detailHref(e);" in panel

    def href(e):  # 화면 쪽 detailHref·pageFor와 같은 규칙
        return f"#{'physical' if e['kind'] == 'loose' else 'visual'}/{e['id']}"
    kinds = {e["kind"]: href(e) for e in data["events"]}
    assert kinds["loose"].startswith("#physical/")
    assert all(kinds[k].startswith("#visual/") for k in ("step", "slope", "crack"))


# --- 점검 이력: 날짜 ------------------------------------------------------------------------

DATES = ["2026-10-20", "2026-10-13", "2026-10-06", "2026-09-29", "2026-09-15"]


def history_section(page):
    return page.split('<section class="page" id="page-history"', 1)[1].split("</section>\n  </main>", 1)[0]


def chips(page):
    return re.findall(r'<button type="button" class="h-chip" data-date="([\d-]+)" aria-pressed="(\w+)" title="[^"]*">'
                      r'<span class="h-dot h-dot-(\w+)" aria-hidden="true"></span>([^<]+)</button>', page)


def test_history_dates_in_html(page):
    """점검 날짜 5개: 칩(최신순, "10.20 (화)", 왼쪽 점 = 그날 가장 높은 판정) + 데이터."""
    got = chips(page)
    assert [d for d, *_ in got] == DATES
    assert [label for *_, label in got] == ["10.20 (화)", "10.13 (화)", "10.06 (화)", "09.29 (화)", "09.15 (화)"]
    assert [w for _, _, w, _ in got] == ["danger", "danger", "warn", "warn", "warn"]
    assert [d["date"] for d in embedded(page)["dates"]] == DATES
    assert 'aria-controls="h-cal"' in page and 'role="dialog" aria-label="점검 날짜 달력"' in page


def test_history_newest_date_selected_by_default(page):
    """처음엔 가장 최근 날짜. 주소는 #history/<YYYY-MM-DD> (모르는 날짜·날짜 없음 → 가장 최근)."""
    assert [p for _, p, *_ in chips(page)] == ["true", "false", "false", "false", "false"]
    assert 'if (page === "history" && NEWEST && !DATE_BY[rawId]) { location.replace(`#history/${NEWEST}`); return; }' in page
    assert "location.replace(`#history/${date}`)" in page


def test_history_kpis_match_each_date(built, page):
    """날짜별 KPI 4개(점검 거리 display_meters, 위험·주의·정상)가 그날 파일과 같다."""
    data = embedded(page)
    files = {d: (read_events(built / "history" / d / "events.csv"), read_trajectory(built / "history" / d / "trajectory.csv"))
             for d in DATES[1:]}
    files[DATES[0]] = (read_events(built / "events.csv"), read_trajectory(built / "trajectory.csv"))
    for d in data["dates"]:
        events, traj = files[d["date"]]
        shown = d["events"] if d["events"] is not None else data["events"]
        assert d["meters"] == display_meters(path_length(traj)), d["date"]
        for lv in ("danger", "warn", "ok"):
            assert sum(e["level"] == lv for e in shown) == sum(e["level"] == lv for e in events), (d["date"], lv)
    assert data["dates"][0]["events"] is None  # 가장 최근 날짜는 종합 현황과 같은 지점 (중복해 넣지 않음)
    # 날짜가 지나며 주의 → 위험으로 나빠진 지점이 있다
    first = {lv: sum(e["level"] == lv for e in data["dates"][-1]["events"]) for lv in ("danger", "warn")}
    assert first["danger"] == 0 and first["warn"] > 0
    # 화면: KPI 카드 4개뿐 (점검 거리·위험·주의·정상)
    kpis = history_section(page).split('<div class="kpis"', 1)[1].split('<div class="h-tools">', 1)[0]
    assert re.findall(r'<div class="label">([^<]+)</div>', kpis) == ["점검 거리", "위험", "주의", "정상"]


def test_history_newest_kpis_match_home(built, page):
    """가장 최근 날짜의 KPI = 종합 현황 KPI (912 m, 위험 4, 주의 5, 정상 31)."""
    data = embedded(page)
    newest = data["dates"][0]
    assert newest["date"] == DATES[0] and newest["meters"] == display_meters(data["distance_m"]) == 912
    counts = {lv: sum(e["level"] == lv for e in data["events"]) for lv in ("danger", "warn", "ok")}
    assert counts == {"danger": 4, "warn": 5, "ok": 31}
    assert "const dateEvents = (date) => (DATE_BY[date] && DATE_BY[date].events) || DATA.events;" in page


def test_history_has_no_session_word(page):
    """점검 이력 화면에 "세션"이 없다: 페이지 마크업·화면 문자열, 사이드바의 세션 항목은 이 페이지에서 숨김."""
    section = history_section(page)
    assert "세션" not in re.sub(r"<[^>]+>", " ", section) and "세션" not in section
    script = page.split("// ---------------------------------------------------------------- 점검 이력", 1)[1].split("function route()", 1)[0]
    strings = re.findall(r'"[^"\n]*"|`[^`]*`', script)
    assert not [t for t in strings if "세션" in t]
    assert '.app:has(#page-history:not([hidden])) .session dl > :nth-child(-n+4) { display: none; }' in page


# --- 점검 이력: 지도·막대·지점 목록 ---------------------------------------------------------------

def test_history_route_distance_matches_kpi(built, page):
    """날짜별 경로(1 m 규칙으로 고른 점)의 마지막 누적 거리 = path_length, 반올림하면 KPI 점검 거리. 눈금은 100 m마다."""
    data = embedded(page)
    for d in data["dates"]:
        folder = built if d["date"] == DATES[0] else built / "history" / d["date"]
        traj = read_trajectory(folder / "trajectory.csv")
        r = d["route"]
        assert r["total"] == path_length(traj), d["date"]
        assert display_meters(r["total"]) == d["meters"], d["date"]
        assert [t["m"] for t in r["ticks"]] == list(range(100, int(r["total"]) + 1, 100))
        assert len(r["ll"]) == len(r["xy"]) >= 2 and r["ll"][0] == [round(traj[0]["lat"], 7), round(traj[0]["lon"], 7)]
    assert data["dates"][0]["meters"] == 912
    # 화면: 도착 라벨에 KPI와 같은 값(display_meters), 경로는 accent 3px, 토글은 기본 켜짐
    assert "도착 ${dateMeters(H.date).toLocaleString(\"ko-KR\")} m" in page
    assert 'L.polyline(r.ll, { className: "h-route-line", weight: 3,' in page and "--h-route: #4F8BFF" in page
    assert '<button type="button" class="h-route-btn" id="h-route-btn" aria-pressed="true">' in page


def test_history_bars_sum_to_kpi(page):
    """종류별 판정 막대는 그날 전체 지점(필터와 무관): 종류별 합을 더하면 KPI 위험·주의·정상과 같다."""
    data = embedded(page)
    kinds = ("step", "slope", "crack", "loose")
    assert 'const KINDS = ["step", "slope", "crack", "loose"];' in page
    assert "LEVELS.map((lv) => all.filter((e) => e.kind === k && e.level === lv).length)" in page
    for d in data["dates"]:
        evs = d["events"] if d["events"] is not None else data["events"]
        assert all(e["kind"] in kinds for e in evs)  # 막대에서 빠지는 종류가 없다
        for lv in ("danger", "warn", "ok"):
            bars = sum(sum(e["kind"] == k and e["level"] == lv for e in evs) for k in kinds)
            assert bars == sum(e["level"] == lv for e in evs), (d["date"], lv)


def test_history_point_rows_match_day_events(built, page):
    """지점 목록 = 그날 지점 전체 (정상은 접어 두었다가 "정상 N건 보기"로 펼친다). 순서: 위험→주의→정상, 같은 판정은 ratio 큰 순."""
    data = embedded(page)
    for d in data["dates"]:
        folder = built if d["date"] == DATES[0] else built / "history" / d["date"]
        evs = d["events"] if d["events"] is not None else data["events"]
        assert len(evs) == len(read_events(folder / "events.csv")), d["date"]
    assert "const rows = fold ? sorted.filter((e) => e.level !== \"ok\") : sorted;" in page
    assert "more.textContent = H.showOk ? `정상 ${nOk}건 접기` : `정상 ${nOk}건 보기`;" in page
    assert "showOk: false" in page  # 처음엔 접힘
    assert '{ key: "level",  label: "판정",      cmp: byIssueOrder }' in page
    assert "const byIssueOrder = (a, b) => LEVEL[b.level].rank - LEVEL[a.level].rank || b.ratio - a.ratio || a.t - b.t;" in page
