import json
import math
import re
from pathlib import Path

import pytest

from stepmap import demo
from stepmap.dashboard import LEAFLET_VERSION, MissingLatLon, build_html, write_dashboard
from stepmap.events import (DEFAULT_THRESHOLDS, EVENT_COLUMNS, criterion_text, display_meters, exceed_ratio, path_length,
                            read_blocks, read_events, read_trajectory)


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
    assert "tile.opentopomap.org" in page  # CARTO를 못 받을 때 대신 쓰는 타일
    assert "--tile-filter: grayscale(1) invert(1)" in page  # 다크 모드
    assert 'setPosition("bottomright")' in page



def test_light_fixed_and_attribution_corner(page):
    """화면은 라이트, 지도는 밝은 지도로 고정: 지도 밝기·다크 모드 버튼 없음, 저장된 다크 설정도 읽지 않는다.
    종합 현황 저작자 표시는 화면 가장 아래 오른쪽 구석(오른쪽 8px, 아래 4px, 블록 줄보다 위 레이어, 11px 한 줄, 반투명 흰 배경)."""
    assert '<html lang="ko" data-theme="light">' in page and 'id="mapcard" data-map="light"' in page
    for gone in ("theme-toggle", "tb-map", ">밝은 지도<", ">어두운 지도<", "stepmap-theme", "stepmap-map", "applyTheme", "localStorage.getItem"):
        assert gone not in page, gone
    assert '<div class="map-attr" id="map-attr"></div>' in page
    assert '$("map-attr").append(map.attributionControl.getContainer());' in page.split("function startTiles() {", 1)[1]
    assert ".map-attr { position: fixed; right: 8px; bottom: 4px; z-index: 750;" in page  # 블록 줄(z-index 700)보다 위, 아래 여백 24px 안
    attr = page.split(".map-attr .leaflet-control-attribution {", 1)[1].split("}", 1)[0]
    assert "font-size: 11px" in attr and "white-space: nowrap" in attr and "background: rgb(255 255 255 / 0.86)" in attr
    assert "line-height: 14px" in attr and "padding: 1px 6px" in attr  # 높이 16px < 아래 여백 24px - 4px
    assert _contrast("#55505A", "#DBDBDB") >= 4.5  # 검정 위 0.86 흰 배경에서도
    assert "#page-home .leaflet-bottom { bottom: 286px; }" in page  # 확대 버튼은 블록 줄 바로 위
    light = page.split('.mapcard[data-map="light"] {', 1)[1].split("}", 1)[0]
    assert "--map-bg: #EDEDED" in light and "--map-grid: #FFFFFF" in light and "--map-park: #BFEBD6" in light
    assert "var(--m-${e.level})" in page and "var(--m-ring)" in page


def test_home_no_route_drawn_and_session(page):
    """종합 현황 지도에는 이동 경로·출발·도착을 그리지 않는다 (지도·평면 지도 모두). 거리 계산과 범위용 데이터는 남긴다."""
    script = page.split("<script>", 1)[1]
    home_map = script.split("function startTiles() {", 1)[1].split("function fallback(reason) {", 1)[0]
    assert "L.polyline" not in home_map  # 점검 이력 지도(그날 경로)와 다르게 종합 현황 지도는 경로·연결선을 그리지 않는다
    for gone in ("route-key", "ep-icon", "endSides", "END_LABEL"):
        assert gone not in page, gone
    legend = script.split("종합 현황: 범례", 1)[1].split("// ----", 1)[0]
    assert "이동 경로" not in legend and "lvBadge" not in legend  # 범례: 경로 항목 없음, 판정은 필터 버튼으로
    plane = script.split("function startPlane() {", 1)[1].split("function renderMap() {", 1)[0]
    assert "<polyline" not in plane  # 평면 지도도 경로 선 없음 (발끝 높이 그래프의 선은 다른 페이지)
    assert "DATA.trajectory_xy" in script  # 지점이 없을 때만 쓰는 범위 대비
    # 지도 범위: 전체 측정 지점 기준 한 번 (판정 필터와 무관)
    assert "L.latLngBounds(DATA.events.length ? DATA.events.map((e) => [e.lat, e.lon]) : DATA.trajectory)" in page
    # maxZoom 19: 실시간 첫 화면처럼 점이 하나뿐이어도 타일이 있는 배율에서 멈춘다
    assert "map.fitBounds(bounds, { paddingTopLeft: pad.tl, paddingBottomRight: pad.br, animate: false, maxZoom: 19 });" in page
    assert "const pts = (DATA.events.length ? DATA.events.map((e) => [e.x, e.y]) : DATA.trajectory_xy).concat(ROBOT_XY ? [ROBOT_XY] : []);" in page
    assert 'id="tb-date"' in page  # 위쪽 바 오른쪽: 마지막 점검 날짜
    assert "body:has(#page-home:not([hidden])) { overflow: hidden; }" in page  # 1260px 이상: 지도 전체, 페이지 스크롤 없음


def level_buttons(page):
    return re.findall(r'<button type="button" class="lv-btn" data-level="(\w+)" aria-pressed="(\w+)">'
                      r'<span class="dot" aria-hidden="true"></span>(\S+) <span class="n">(\d+)</span></button>', page)


def test_level_filter_buttons_and_counts(page):
    """범례의 판정 필터: button 3개 (위험·주의·정상), 각각 색 점 + 이름 + 전체 개수."""
    assert [(lv, name, int(n)) for lv, _, name, n in level_buttons(page)] == [
        ("danger", "위험", 4), ("warn", "주의", 5), ("ok", "정상", 31)]
    assert '<div class="lv-filter" id="lv-filter" role="group" aria-label="판정별 지점 보기">' in page
    for lv, color in (("danger", "#EF6461"), ("warn", "#F7B558"), ("ok", "#A5D48C")):
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
    # 타일 실패·대체 이미지·응답 없음은 다음 제공처, 마지막 제공처도 안 되면 평면 지도. Leaflet 미로딩은 바로 평면
    for reason in ('next("tileerror", at)', '"placeholder"', 'next("timeout", at)', 'fallback("leaflet")',
                   "attachTiles(map, 19, () => gen === state.gen && state.mode === \"tiles\", (reason) => fallback(reason), () => $(\"mapcard\").dataset.map);"):
        assert reason in page, reason


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
    for sid in ("nav", "tb-date",
                "page-home", "page-detail", "page-history",
                "map", "plane", "retry", "legend", "hrow", "hblocks", "rc-name", "rc-prev", "rc-next"):
        assert f'id="{sid}"' in page, sid
    assert "지도 다시 불러오기" in page
    assert "휠체어 회피 기준" in page


def test_three_pages_with_hash_links(page):
    """메뉴 3개: 종합 현황 / 검사 결과 / 점검 이력. 처음엔 종합 현황만 보인다."""
    assert re.findall(r'<a href="#(\w+)" data-page="\w+">', page) == ["home", "detail", "history"]
    nav = re.search(r'<nav class="nav".*?</nav>', page, re.S).group(0)
    assert re.findall(r'<span class="full">([^<]+)</span>', nav) == ["종합 현황", "검사 결과", "점검 이력"]
    assert "설정" not in nav
    assert '<section class="page" id="page-home" data-page="home"' in page
    for p in ("detail", "history"):
        assert re.search(rf'<section class="page" id="page-{p}"[^>]*hidden>', page), p
    assert 'id="page-visual"' not in page and 'id="page-physical"' not in page
    assert 'addEventListener("hashchange", route)' in page  # 뒤로 가기
    # 위쪽 가운데 떠 있는 pill 메뉴, 1259px 이하는 화면 아래 고정 탭바
    assert '<header class="topbar">' in page and 'class="side"' not in page
    tab = page.split("/* 1259px 이하: 메뉴는 화면 아래 고정 탭바 */", 1)[1].split("}\n  }", 1)[0]
    assert "@media (max-width: 1259px)" in tab and ".nav { position: fixed; left: 0; right: 0; bottom: 0;" in tab


def test_old_menu_names_not_on_screen(built, page, tmp_path):
    """옛 메뉴 이름("외관 검사", "물리적 안정성 검사")은 대시보드·신고서 어디에도 없다."""
    from stepmap.report import write_report
    rep_html, rep_csv, _ = write_report(built / "events.csv", built / "trajectory.csv", tmp_path / "report.html")
    for doc in (page, rep_html.read_text(encoding="utf-8"), rep_csv.read_text(encoding="utf-8-sig")):
        for old in ("외관 검사", "물리적 안정성", "외관·물리적"):
            assert old not in doc, old


def test_old_routes_open_detail(page):
    """예전 주소 #visual/<id>, #physical/<id>는 #detail/<id>로 바꿔 연다 (없는 id면 #detail)."""
    assert 'if (rawPage === "visual" || rawPage === "physical") {' in page
    assert 'location.replace(rawId && byId[rawId] ? `#detail/${rawId}` : "#detail");' in page
    assert "const detailHref = (e) => `#detail/${e.id}`;" in page
    # 선택 없이 들어오면 목록 첫 지점
    assert "const first = detailShown()[0] || detailAll[0];" in page and "location.replace(`#detail/${first.id}`)" in page


def test_click_rule_and_theme_default(page):
    # 지점 상세는 모두 검사 결과 (종합 현황 상세 패널의 "자세히 보기", 점검 이력 지점 목록)
    assert "pageFor" not in page
    assert '<html lang="ko" data-theme="light">' in page and ':root[data-theme="dark"]' in page  # 라이트 기본
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
    assert 'putDistance($("h-k-dist"), i >= 0 ? DATES[i].meters : DATA.distance_m)' in page  # 점검 이력: display_meters 값
    assert page.count("Math.round(DATA.distance_m)") == 0
    card = math.floor(data["distance_m"] + 0.5)  # JS Math.round와 같은 규칙
    assert card == math.floor(exact + 0.5) == 912


def test_detail_page_structure(page):
    """검사 결과: 요약 한 줄 + 왼쪽 목록(탭·판정 칩) + 오른쪽 상세 + 위치 지도. 처음 칩은 위험·주의만 켜짐."""
    for sid in ("d-summary", "d-tabs", "d-levels", "d-list", "d-detail", "d-map", "d-plane"):
        assert f'id="{sid}"' in page, sid
    chips = re.findall(r'<button type="button" class="lv-btn" data-level="(\w+)" aria-pressed="(\w+)">'
                       r'<span class="dot" aria-hidden="true"></span>(\S+) <span class="n" id="d-n-\w+"></span></button>', page)
    assert chips == [("danger", "true", "위험"), ("warn", "true", "주의"), ("ok", "false", "정상")]
    assert 'const D_TABS = [["all", "전체"], ["surface", "노면 형상"], ["loose", "흔들림"]];' in page
    assert ".d-grid { display: grid; grid-template-columns: 360px minmax(0, 1fr);" in page
    assert "@media (max-width: 1259px) { .d-grid { grid-template-columns: minmax(0, 1fr); } }" in page
    # 정렬: 위험→주의→정상, 같은 판정은 ratio 큰 순
    assert "const detailAll = [...DATA.events].sort(byIssueOrder);" in page and "b.ratio - a.ratio" in page
    assert '밟은 블록 ${DATA.stepped_blocks.toLocaleString("ko-KR")}개 확인' in page  # 천 단위 쉼표
    for text in ("깊이 카메라 바닥 평면 대비 높이 차", "발 접지 높이 차", "깊이 카메라 바닥 평면 기울기",
                 "RGB 영상 균열 검출 점수", "신고서에 포함됨", "사진 없음", "지도에서 위치 보기", "두 측정 차이",
                 "밟은 횟수", "추가 침하", "주변 노면 형상 비교", "측정 방식"):
        assert text in page, text
    assert 'const ratioText = (e) => (e.kind === "crack" ? ""' in page  # 균열은 배수 표시 안 함
    assert "row(\"위도·경도\", `${Number(e.lat).toFixed(6)}, ${Number(e.lon).toFixed(6)}`);" in page
    assert "location.hash = `#home/${e.id}`" in page


def test_detail_tab_counts_sum_to_all(page):
    """탭별 개수: 노면 형상 + 흔들림 = 전체 (판정 칩이 어떻든). 탭 개수는 목록과 같은 함수로 센다."""
    data = embedded(page)
    assert "b.append(el(\"span\", null, label), el(\"span\", \"n\", String(detailShown(k).length)));" in page
    assert 'const inTab = (e, tab) => tab === "all" || (tab === "loose") === (e.kind === "loose");' in page
    levels = ("danger", "warn", "ok")
    for mask in range(8):
        on = {lv for i, lv in enumerate(levels) if mask >> i & 1}
        shown = [e for e in data["events"] if e["level"] in on]
        surface = sum(e["kind"] != "loose" for e in shown)
        loose = sum(e["kind"] == "loose" for e in shown)
        assert surface + loose == len(shown)
    # 처음 칩(위험·주의): 전체 9 = 노면 형상 7 + 흔들림 2
    first = [e for e in data["events"] if e["level"] in ("danger", "warn")]
    assert (len(first), sum(e["kind"] != "loose" for e in first), sum(e["kind"] == "loose" for e in first)) == (9, 7, 2)


def test_loose_detail_has_graph_and_confirmation(built, page):
    """흔들림 상세: 발끝 높이 그래프 + 밟은 횟수 + 추가 침하 + 확정/의심. 목록 행은 ◆ 아이콘과 배지."""
    data = embedded(page)
    card = page.split("function renderDetailCard() {", 1)[1].split("\n  }\n", 1)[0]
    loose_part = card.split("if (loose) {  // 흔들림", 1)[1].split("\n    }\n", 1)[0]
    assert "footGraph(e)" in loose_part and "밟은 횟수" in loose_part and "추가 침하" in loose_part
    assert 'el("span", `dia lv-c-${e.level}`, "◆")' in page
    ev = {e["id"]: e for e in data["events"]}
    assert ev["ev_0014"]["trace"] is not None and len(ev["ev_0014"]["steps"]) == 2 and ev["ev_0014"]["confirm"] == "확정"
    assert ev["ev_0031"]["confirm"] == "의심" and len(ev["ev_0031"]["steps"]) == 1
    assert all(ev[i]["confirm"] is None for i in ev if ev[i]["kind"] == "loose" and ev[i]["level"] == "ok")
    assert data["stepped_blocks"] == len(read_blocks(built / "blocks.csv"))  # 밟은 블록 = blocks.csv 행 수


def test_spiderfy_at_max_zoom(page):
    assert "function spiderfy(g)" in page
    assert "map.getZoom() >= map.getMaxZoom()" in page and "클릭 → 펼치기" in page


def test_surface_targets_match_data(built, page):
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

def test_home_blocks_structure(page):
    """화면 아래 블록 줄: 반투명 회색 틀(안쪽 여백 8px, 모서리 22px) 안에 [로봇 카드][사진][측정값 / 기준 대비][근거].
    틀은 처음엔 로봇 카드 크기만, 지점을 고르면 오른쪽으로 0.25초에 늘어난다 (움직임 줄이기 설정이면 바로)."""
    assert '<div class="hrow" id="hrow" aria-label="점검 로봇과 지점 근거">' in page
    assert ".hrow { display: flex; gap: 8px; padding: 8px; border-radius: 22px; background: rgb(54 50 54 / 0.08); }" in page
    assert ("#page-home .hrow { position: fixed; left: 24px; bottom: 24px; z-index: 700; height: 250px; width: calc(var(--rc-w) + 16px);\n"
            "                       max-width: calc(100vw - 48px); transition: width 0.25s ease-out; }") in page
    assert "#page-home .hrow.open { width: calc(100vw - 48px); }" in page
    assert "@media (min-width: 1260px) and (prefers-reduced-motion: reduce) { #page-home .hrow { transition: none; } }" in page
    assert "#page-home .leaflet-bottom { bottom: 286px; }" in page  # 확대 버튼·저작자 표시는 블록 줄 위
    assert "return { tl: [48, top], br: [72, $(\"hrow\").offsetHeight + 24 + 32] };" in page  # 지도 범위 여백 = 블록 줄 높이
    assert 'grid-template-areas: "photo num why" "photo ratio why";' in page  # 측정값·기준 대비는 위아래
    blocks = page.split("function renderBlocks() {", 1)[1].split("\n  }\n", 1)[0]
    for part in ('el("div", "glass hb hb-photo")', 'el("div", "glass hb hb-num")', 'el("div", "glass hb hb-ratio")', 'el("div", "glass hb hb-why")',
                 'el("span", "t", "측정값")', '`위험 기준 ${withUnit(th[1], unit)}`', 'el("span", "t", "기준 대비")', '"기준 이내"',
                 "halfGauge(e.value / span, e.level, [[th[0] / span, \"var(--warn)\"], [th[1] / span, \"var(--danger)\"]]",
                 '`기준 ${criterion(e)}`', "Number(e.lat).toFixed(6)", "fmtDateTimeS(e.t)", "METHOD_ICONS", 'el("span", "hb-cf", e.confirm)',
                 '`추가 침하 ${fmtNum(e.value, unit)} mm`', 'el("button", "hb-close")', 'close.addEventListener("click", closePanel);',
                 'tag.append(lvBadge(e.level), el("span", null, KIND[e.kind].label), el("span", "id", e.id));', "acts.append(go, close);",
                 "box.append(ph, nb, rb, wb);"):
        assert part in blocks, part
    assert "pattern" in page.split("function halfGauge(", 1)[1].split("\n  }\n", 1)[0]  # 등급 색 + 빗금
    photo = page.split("function blockPhoto(e, onMissing) {", 1)[1].split("\n  }\n", 1)[0]
    assert 'el("span", "hb-mk", "발 접촉 위치")' in photo and "stroke-dasharray:7 5" in photo  # 흔들림: 점선 동그라미 + 작은 라벨
    assert ("font-size: 11px" in page.split(".hb-mk {", 1)[1].split("}", 1)[0]
            and "background: rgb(255 255 255 / 0.86); color: #363236;" in page.split(".hb-mk {", 1)[1].split("}", 1)[0])
    assert ".hblocks.in > .hb { animation: hb-up 0.25s ease-out both; }" in page
    assert "@media (prefers-reduced-motion: reduce) { .hblocks.in > .hb { animation: none; } }" in page
    assert 'if (state.page === "home" && state.sel && !document.querySelector("dialog[open]")) closePanel();' in page  # Esc
    assert "else if (state.sel) closePanel(); });" in page  # 지도 빈 곳
    assert 'class="mk-sel"' in page  # 고른 마커 선택 표시


def test_home_robot_marker_is_last_trajectory_point(built, page):
    """로봇개 마커 = 이동 궤적 마지막 점 (Leaflet·평면 지도 모두). 경로 선은 그리지 않는다."""
    data = embedded(page)
    traj = read_trajectory(built / "trajectory.csv")
    assert data["trajectory"][-1] == [round(traj[-1]["lat"], 7), round(traj[-1]["lon"], 7)]
    assert data["trajectory_xy"][-1] == [round(traj[-1]["x"], 2), round(traj[-1]["y"], 2)]
    assert "const ROBOT_LL = DATA.trajectory.length ? DATA.trajectory[DATA.trajectory.length - 1] : null;" in page
    assert "const ROBOT_XY = DATA.trajectory_xy.length ? DATA.trajectory_xy[DATA.trajectory_xy.length - 1] : null;" in page
    assert 'L.marker(ROBOT_LL, { icon: L.divIcon({ className: "robot-mk"' in page
    assert 'rb.setAttribute("transform", `translate(${(X(ROBOT_XY[0]) - 18).toFixed(1)},${(Y(ROBOT_XY[1]) - 18).toFixed(1)})`);' in page
    assert ".robot-mk .pulse { background: rgb(54 50 54 / 0.28); animation: robot-pulse 2.6s ease-out infinite; }" in page
    assert "@media (prefers-reduced-motion: reduce) {\n    .robot-mk .pulse, #plane .robot-pulse { animation: none;" in page
    home = page.split("function startTiles() {", 1)[1].split("function fallback(reason) {", 1)[0]
    assert "L.polyline" not in home  # 경로 선·연결선 없음


def test_home_default_card_and_next_order(built, page):
    """기본 카드 = 로봇이 가장 최근에 찾은 위험 지점. "다음" 두 칸 = 위험→주의, 같은 판정은 exceed_ratio 큰 순으로 지금 지점 다음."""
    from stepmap.dashboard import home_cards
    data = embedded(page)
    events = read_events(built / "events.csv")
    danger = [e for e in events if e["level"] == "danger"]
    assert data["home"]["default"] == max(danger, key=lambda e: e["t"])["id"] == "ev_0014"
    rank = {"danger": 2, "warn": 1}
    issues = sorted((e for e in events if e["level"] in rank),
                    key=lambda e: (-rank[e["level"]], -exceed_ratio(e["kind"], e["level"], e["value"], DEFAULT_THRESHOLDS), e["t"]))
    order = data["home"]["order"]
    assert order == [e["id"] for e in issues] and len(order) == 9
    assert order[:4] == ["ev_0012", "ev_0014", "ev_0009", "ev_0013"]  # 위험: 2.4배, 1.4배, 1.1배, 1.1배
    i = order.index("ev_0014")
    assert [order[(i + 1) % 9], order[(i + 2) % 9]] == ["ev_0009", "ev_0013"]  # 기본 카드의 "다음" 두 칸
    assert "order[(i + dir + order.length) % order.length]" in page  # 화면 ← → 도 같은 순서 (끝이면 처음으로)
    # 위험이 없으면 가장 최근 주의, 둘 다 없으면 없음
    warn_only = [{**e, "level": "warn" if e["level"] == "danger" else e["level"]} for e in events if e["level"] != "danger"]
    assert home_cards(warn_only, DEFAULT_THRESHOLDS)["default"] == max(warn_only, key=lambda e: e["t"] if e["level"] == "warn" else -1)["id"]
    assert home_cards([e for e in events if e["level"] == "ok"], DEFAULT_THRESHOLDS) == {"order": [], "default": None}


def test_home_glass_style_and_fallback(page):
    """유리 카드: 반투명 바탕 + 흐림. 흐림을 못 쓰거나 투명도 줄이기 설정이면 불투명(라이트 #FFFFFF, 다크 #2A262A).
    지도 가장 어두운 곳(검정)·가장 밝은 곳(흰색) 위에서도 글자·보조 글자 4.5:1 이상."""
    css = page.split("<style>", 1)[1].split("</style>", 1)[0]
    assert "@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {\n    .glass, .nav, .icon-btn, #page-home .retry { background: var(--glass-solid); }" in css
    assert "@media (prefers-reduced-transparency: reduce) {\n    .glass, .nav, .icon-btn, #page-home .retry { background: var(--glass-solid); -webkit-backdrop-filter: none; backdrop-filter: none; }" in css
    assert "backdrop-filter: blur(18px) saturate(1.4)" in css and ".frame { padding: 6px; border-radius: 22px; background: var(--frame-bg); }" in css
    light = css.split(":root { --glass-bg:", 1)[1].split("}", 1)[0]
    dark = css.split(':root[data-theme="dark"] { --glass-bg:', 1)[1].split("}", 1)[0]
    assert "--glass-solid: #FFFFFF" in light and "--glass-solid: #2A262A" in dark

    def alpha(block):
        return float(re.search(r"rgb\((\d+) (\d+) (\d+) / ([\d.]+)\)", block).group(4))

    def over(fg_hex, a, bg):
        fg = [int(fg_hex[k:k + 2], 16) for k in (1, 3, 5)]
        return "#" + "".join(f"{round(f * a + b * (1 - a)):02X}" for f, b in zip(fg, bg))
    la, da = alpha(light), alpha(dark)
    g_l = re.search(r"--glass-muted: (#\w{6})", light).group(1)
    g_d = re.search(r"--glass-muted: (#\w{6})", dark).group(1)
    for bg in ((0, 0, 0), (255, 255, 255)):
        lb, db = over("#FFFFFF", la, bg), over("#1F1C1F", da, bg)
        assert _contrast("#363236", lb) >= 4.5 and _contrast(g_l, lb) >= 4.5, (bg, lb)
        assert _contrast("#F2F0F2", db) >= 4.5 and _contrast(g_d, db) >= 4.5, (bg, db)


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
    """"자세히 보기"와 점검 이력 지점 목록: 모든 지점이 #detail/<id> (방문 기록에 남겨 뒤로 가기 → #history/<날짜>)."""
    blocks = page.split("function renderBlocks() {", 1)[1].split("\n  }\n", 1)[0]
    assert 'const go = el("a", "hb-go");' in blocks and "go.href = detailHref(e);" in blocks  # ↗ 자세히 보기
    assert "if (newest) go.href = detailHref(e);" in page  # 점검 이력 행 (링크 → hash 이동, replace 아님)
    assert "const hOpen = (e) => { hideTip(); location.hash = detailHref(e); };" in page


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
    assert 'class="session"' not in page and "측정 세션" not in page  # 사이드바 세션 칸 없음 (위쪽 바에는 날짜만)


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


# --- 종합 현황 지도: 마커 모양 ----------------------------------------------------------------

def test_home_marker_shapes_by_kind(page):
    """종합 현황 지도: 흔들림은 마름모(ev-diamond, 흰 발 아이콘), 나머지(노면 형상)는 원(ev-circle). 지도·펼친 지점·평면 지도 모두."""
    script = page.split("<script>", 1)[1]
    assert 'const homeShape = (e) => (e.kind === "loose" ? "diamond" : "circle");' in script
    assert 'class="mk-diamond"' in script and 'transform="rotate(45 12 12)"' in script and 'class="mk-circle"' in script
    assert "fill:#FFFFFF" in script.split("const PAW =", 1)[1].split(";", 1)[0]  # 흰 발 아이콘
    home = script.split("function leafletMarkers() {", 1)[1].split("function fallback(reason) {", 1)[0]
    plane = script.split("function startPlane() {", 1)[1].split("function renderMap() {", 1)[0]
    assert home.count("className: `ev-marker ev-${homeShape(") == 2  # 한 지점 + 펼친 지점
    assert 'node.setAttribute("class", `ev ev-${homeShape(e)}`);' in plane
    assert "markerInner(" not in home.replace("homeMarkerInner(", "") and "markerInner(" not in plane.replace("homeMarkerInner(", "")
    data = embedded(page)
    shapes = {e["id"]: ("diamond" if e["kind"] == "loose" else "circle") for e in data["events"]}
    assert sum(v == "diamond" for v in shapes.values()) == 8 and sum(v == "circle" for v in shapes.values()) == 32
    # 묶음은 원, 흔들림이 있으면 오른쪽 위 작은 마름모 배지
    assert 'class="mk-cluster"' in script and 'class="mk-badge"' in script
    assert 'const loose = members.filter((e) => e.kind === "loose");' in script


def test_home_shape_legend_in_html(page):
    """필터 버튼 옆 회색 모양 범례: ● 노면 형상  ◆ 흔들림 (판정 색을 쓰지 않는다)."""
    legend = page.split('<div class="glass hfilter legend" id="legend"', 1)[1].split("</div>\n      </div>", 1)[0]
    assert '<div class="shape-legend" id="shape-legend" role="group" aria-label="마커 모양">' in legend
    assert re.findall(r'<span class="item"><svg class="shp"[^>]*>(?:<circle|<rect)[^<]*</svg>([^<]+)</span>', legend) == ["노면 형상", "흔들림"]
    assert legend.index('id="lv-filter"') < legend.index('id="shape-legend"')
    assert ".shape-legend .shp { width: 14px; height: 14px; flex: none; fill: var(--muted); }" in page
    assert "흔들림 (점선 고리)" not in page



# --- 색감·글꼴·지도 타일 ------------------------------------------------------------------------

def _lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _mix(a, b, t):
    pa, pb = [int(a[i:i + 2], 16) for i in (1, 3, 5)], [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * t + y * (1 - t)):02X}" for x, y in zip(pa, pb))


def _tokens(block):
    return dict(re.findall(r"--([\w-]+): (#[0-9A-Fa-f]{6})", block))


def test_grade_colors_and_ink_contrast(page):
    """등급 색(위험·주의·정상)과 글자용 진한 변형: 흰 카드·배경·배지 바탕(20%) 모두 4.5:1 이상 (라이트·다크)."""
    light = _tokens(page.split(":root {", 1)[1].split("}", 1)[0])
    dark = {**light, **_tokens(page.split(':root[data-theme="dark"] {', 1)[1].split("}", 1)[0])}
    assert (light["danger"], light["warn"], light["ok"]) == ("#EF6461", "#F7B558", "#A5D48C")
    assert (light["bg"], light["surface"], light["text"], light["muted"], light["border"], light["accent"]) == (
        "#EDEDED", "#FFFFFF", "#363236", "#75707A", "#E4E2E6", "#363236")
    assert (dark["bg"], dark["surface"], dark["text"]) == ("#1F1C1F", "#2A262A", "#F2F0F2")
    for t in (light, dark):
        for lv in ("danger", "warn", "ok"):
            for bg in (t["surface"], t["bg"], _mix(t[lv], t["surface"], 0.2)):
                assert _contrast(t[f"{lv}-ink"], bg) >= 4.5, (lv, t[f"{lv}-ink"], bg)
            assert _contrast(t["on-grade"], t[lv]) >= 4.5  # 등급 색 바탕 위 글자 (막대 그래프)
        assert _contrast(t["text"], t["surface"]) >= 4.5 and _contrast(t["text"], t["bg"]) >= 4.5
        assert _contrast(t["muted"], t["surface"]) >= 4.5 and _contrast(t["muted-strong"], t["bg"]) >= 4.5
        assert _contrast(t["muted"], t["surface-2"]) >= 4.5
        assert _contrast(t["on-accent"], t["accent"]) >= 4.5  # 선택된 메뉴·탭·칩·날짜
    assert "background: color-mix(in srgb, var(--c) 20%, var(--surface)); color: var(--ink);" in page  # 배지: 옅은 바탕 + 진한 글자


def test_fonts_inter_tight_then_pretendard(page):
    """영문·숫자 Inter Tight(400/500/600), 한글 Pretendard, 없으면 시스템 글꼴. KPI 큰 숫자는 500, 자간 -0.02em."""
    assert '--font: "Inter Tight", "Pretendard Variable", Pretendard, system-ui,' in page
    assert 'href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600&display=swap"' in page
    assert "pretendardvariable-dynamic-subset.css" in page
    assert ".kpi .value { grid-column: 2; font-size: 30px; font-weight: 500; line-height: 1.1; letter-spacing: -0.02em;" in page
    assert ".kpi .value small { font-size: 14px; font-weight: 500; color: var(--muted);" in page
    css = page.split("<style>", 1)[1].split("</style>", 1)[0]
    assert not re.search(r"font-weight: (6[5-9]0|[7-9]\d\d)", css)  # 받은 굵기(600)보다 굵게 그리지 않는다


def test_tile_providers_and_attribution(page):
    """밝은 지도: CARTO light_all (© OpenStreetMap contributors © CARTO) → 못 받으면 OpenTopoMap + 회색 필터 → 평면 지도."""
    assert "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png" in page
    assert ('&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors '
            '&copy; <a href="https://carto.com/attributions">CARTO</a>') in page
    assert "OpenStreetMap</a> contributors, SRTM" in page and "OpenTopoMap</a>" in page and "CC-BY-SA" in page
    tiles = page.split("const TILES = [", 1)[1].split("];", 1)[0]
    assert tiles.index('name: "carto"') < tiles.index('name: "topo"')
    assert ':root[data-tiles="topo"] .mapcard[data-map="light"] { --tile-filter: grayscale(1)' in page
    assert len(re.findall(r"attachTiles\(map, \d+,", page)) == 3  # 종합 현황·점검 이력·검사 결과 위치 지도 모두 같은 차례



# --- 종합 현황: 근거 카드·점선 연결, 아래 카드 줄 없음 ---------------------------------------------

def test_home_blocks_hidden_until_point_chosen(page):
    """처음 열면 로봇 카드만 있고 지점 블록은 없다. 지점을 고르면(#home/<id>) 블록이 보인다 (새로고침해도)."""
    assert '<div class="hblocks" id="hblocks" aria-label="지점 근거" aria-live="polite" hidden></div>' in page
    assert "const cardEvent = () => (state.sel && byId[state.sel.id]) || null;" in page
    blocks = page.split("function renderBlocks() {", 1)[1].split("\n  }\n", 1)[0]
    assert "box.hidden = !e;" in blocks and '$("hrow").classList.toggle("open", !!e);' in blocks
    assert "renderBlocks();" in page.split("function route() {", 1)[1]  # 주소에 지점이 있으면 블록을 연다
    for gone in ("dstack", "robot-link", "renderCard", "placeCard", "ensureBoth", "dlink"):  # 로봇개 옆 근거 카드·연결 점선 없음
        assert gone not in page, gone


def test_home_blocks_content_matches_point(built, page):
    """블록 내용 = 그 지점 데이터: 측정값, exceed_ratio, criterion_text, 사진 경로 (마커·← → 모두 pick → #home/<id> → renderBlocks)."""
    data = embedded(page)
    ev = {e["id"]: e for e in data["events"]}
    files = {e["id"]: e for e in read_events(built / "events.csv")}
    e12, raw = ev["ev_0012"], files["ev_0012"]
    assert e12["value"] == raw["value"] == 4.8 and e12["unit"] == "cm"
    assert e12["ratio"] == round(exceed_ratio("step", "danger", 4.8, DEFAULT_THRESHOLDS), 4) == 2.4
    assert e12["criterion"] == criterion_text("step", "danger", DEFAULT_THRESHOLDS)
    blocks = page.split("function renderBlocks() {", 1)[1].split("\n  }\n", 1)[0]
    assert "fmtNum(e.value, unit)" in blocks and "ratio.toFixed(1)" in blocks and "criterion(e)" in blocks
    assert "blockPhoto(e, () => btn.replaceWith(noPhoto()))" in blocks and "img.src = p.src;" in page  # 사진: e.photo.src
    pick = page.split("const pick = (e) => {", 1)[1].split("\n  };\n", 1)[0]
    assert "location.replace(`#home/${e.id}`);" in pick and "ensureVisible(e);" in pick


def test_home_prev_next_order(page):
    """← →: 위험→주의(같은 판정은 exceed_ratio 큰 순)로 이전·다음. 아무것도 고르지 않았으면 →는 첫 위험 지점, ←는 마지막."""
    order = embedded(page)["home"]["order"]
    step = page.split("function stepPick(dir) {", 1)[1].split("\n  }\n", 1)[0]
    assert "const i = state.sel ? order.indexOf(state.sel.id) : -1;" in step
    assert "order[dir > 0 ? 0 : order.length - 1]" in step and "order[(i + dir + order.length) % order.length]" in step
    assert "pick(e);" in step  # 지도 마커 누르기와 같은 동작

    def step_py(sel, d):  # 화면 stepPick과 같은 규칙
        i = order.index(sel) if sel in order else -1
        return order[0 if d > 0 else -1] if i < 0 else order[(i + d) % len(order)]
    assert step_py(None, 1) == order[0] == "ev_0012"
    assert step_py(None, -1) == order[-1]
    assert [step_py("ev_0012", 1), step_py("ev_0014", 1), step_py("ev_0012", -1)] == ["ev_0014", "ev_0009", order[-1]]
    assert 'id="rc-prev"' in page and '$("rc-next").addEventListener("click", () => stepPick(1));' in page


def test_home_robot_card(built, tmp_path):
    """로봇 카드: 이름(robot.name)은 주황 칸 + 차콜 글자, 상태 배지 없음. 모델·배터리·센서·점검 일시·이동 거리(display_meters).
    robot.png가 없거나 투명 배경이 아니면 직접 그린 그림."""
    from PIL import Image
    meta = {"area": "제주시 노형동·연동", "robot": "Go2-01", "model": "Unitree Go2 EDU", "sensors": ["LiDAR", "깊이 카메라", "발 접촉"],
            "battery": 72}
    out = tmp_path / "a" / "d.html"
    html = write_dashboard(built / "events.csv", built / "trajectory.csv", out, meta=meta).read_text(encoding="utf-8")
    data = embedded(html)
    assert (data["robot"], data["robot_model"], data["robot_sensors"], data["robot_battery"]) == (
        "Go2-01", "Unitree Go2 EDU", ["LiDAR", "깊이 카메라", "발 접촉"], 72)
    assert '$("rc-name").textContent = DATA.robot || "점검 로봇";' in html and '$("rc-model").textContent = DATA.robot_model || "—";' in html
    assert data["meters"] == display_meters(path_length(read_trajectory(built / "trajectory.csv")))
    assert data["robot_photo"] is None and not (out.parent / "photos" / "robot.png").exists()
    assert '<svg id="rc-draw" viewBox="0 0 220 170" aria-hidden="true">' in html  # 사진이 없으면 그림
    assert '<b class="rc-name" id="rc-name"></b>' in html
    assert "border-radius: 12px; background: #F7B558; color: #363236; font-size: 22px;" in html
    assert _contrast("#363236", "#F7B558") >= 4.5
    assert "rc-done" not in html and "점검 완료" not in html  # 상태 배지 없음
    for sid, label in (("rc-model", "모델:"), ("rc-sensors", "센서:"), ("rc-when", "점검 일시:"), ("rc-dist", "이동 거리:")):
        assert f'<dt>{label}</dt><dd class="chip-bg" id="{sid}"></dd>' in html
    assert '<dt id="rc-battery-k">배터리:</dt><dd class="chip-bg" id="rc-battery"></dd>' in html
    card = html.split("// 로봇 카드: 이름", 1)[1].split("\n  }\n", 1)[0]
    assert '$("rc-battery-k").hidden = $("rc-battery").hidden = !hasBattery;' in card
    assert 'if (hasBattery) $("rc-battery").textContent = `${DATA.robot_battery}%`;' in card
    assert '`${DATA.meters.toLocaleString("ko-KR")} m`' in card
    assert ".rc-art::after {" in html  # 발밑 옅은 타원 그림자
    # 투명 배경 robot.png만 사본을 photos/robot.png로 (투명 배경 유지)
    im0 = Image.new("RGBA", (900, 600), (0, 0, 0, 0))
    im0.paste((80, 80, 80, 255), (100, 100, 400, 300))  # 가운데 로봇(300×200) + 투명 여백
    im0.save(built / "robot.png")
    try:
        out2 = tmp_path / "b" / "d.html"
        data2 = embedded(write_dashboard(built / "events.csv", built / "trajectory.csv", out2, meta=meta).read_text(encoding="utf-8"))
        assert data2["robot_photo"] == "photos/robot.png"
        with Image.open(out2.parent / "photos" / "robot.png") as im:
            assert im.mode == "RGBA" and im.size == (300, 200)  # 투명 여백을 잘라 로봇만
        # 사진: 카드 안쪽 높이의 약 92%, 오른쪽 아래(아래 10px) 카드 안, 칩과 12px 이상 떨어지게 최대로, 그림자 = 사진 폭의 70%
        assert ".rc-art.photo { right: 44px; bottom: 10px; width: 45%; height: calc((100% - 32px) * 0.92); opacity: 1; }" in html
        shadow = html.split(".rc-art.photo::after {", 1)[1].split("}", 1)[0]
        assert "width: calc(var(--shot-w, 100%) * 0.7)" in shadow and "rgb(54 50 54 / 0.12)" in shadow and "blur(8px)" in shadow
        fit = html.split("const fitRobotPhoto = () => {", 1)[1].split("\n      };", 1)[0]
        assert "const room = box.width - (chipRight + 13);" in fit and "const R = Math.max(16, Math.min(44, room - want));" in fit
        assert "const w = Math.max(0, Math.min(want, room - R));" in fit and "0.45" not in fit
        assert ".rc-top { position: relative; z-index: 1;" in html and ".rc-art { position: absolute; z-index: 0;" in html  # 버튼이 사진 위
        # 배경이 있는 그림(카드 캡처 등)은 쓰지 않고 그림으로 대체, 지난 사본도 지운다
        Image.new("RGB", (900, 600), (255, 255, 255)).save(built / "robot.png")
        data3 = embedded(write_dashboard(built / "events.csv", built / "trajectory.csv", out2, meta=meta).read_text(encoding="utf-8"))
        assert data3["robot_photo"] is None and not (out2.parent / "photos" / "robot.png").exists()
    finally:
        (built / "robot.png").unlink()


def test_home_robot_battery_hidden_without_value(built, tmp_path):
    """config robot.battery가 없거나 숫자가 아니면 None → 배터리 줄 숨김. 있으면 0~100 정수."""
    for battery, want in ((None, None), ("", None), ("많음", None), (72, 72), ("85", 85), (120, 100)):
        meta = {"robot": "Go2", "battery": battery}
        data = embedded(write_dashboard(built / "events.csv", built / "trajectory.csv", tmp_path / "d.html", meta=meta).read_text(encoding="utf-8"))
        assert data["robot_battery"] == want, battery


def test_config_robot_battery():
    """config.yaml robot.battery: 72 → stepmap map이 로봇 카드에 72%로 넘긴다."""
    from stepmap.events import load_config
    cfg = load_config(Path(__file__).resolve().parents[1] / "config.yaml")
    assert cfg["robot"]["battery"] == 72
    assert (cfg["robot"]["name"], cfg["robot"]["model"]) == ("Go2-01", "Unitree Go2 EDU")  # 이름 칸과 모델 줄이 다르다
    import inspect
    from stepmap import cli
    assert '"battery": robot.get("battery")' in inspect.getsource(cli.cmd_map)


def test_vector_style_palette(page):
    """벡터 지도 색 덮어쓰기 (OpenFreeMap positron): 밝은·어두운 지도 값, 한국어 이름, 방패·아이콘 숨김."""
    from stepmap.dashboard import VECTOR_PALETTE
    assert VECTOR_PALETTE["light"] == {"land": "#EDEDED", "building": "#E4E4E4", "road": "#FFFFFF", "casing": "#E2E2E2",
                                       "park": "#BFEBD6", "wood": "#A5D48C", "wood_opacity": 0.7, "water": "#D3E2E4", "label": "#A09CA2"}
    dark = VECTOR_PALETTE["dark"]
    assert (dark["land"], dark["road"], dark["park"], dark["water"], dark["label"]) == ("#1F1C1F", "#3A363A", "#2C3B33", "#26303A", "#A09CA2")
    assert f"const MAP_COLORS = {json.dumps(VECTOR_PALETTE)};" in page
    style = page.split("function recolorStyle(src, c) {", 1)[1].split("\n    return st;", 1)[0]
    for part in ('pt["background-color"] = c.land', 'pt["fill-color"] = c.park', 'pt["fill-opacity"] = c.wood_opacity',
                 'pt["fill-color"] = c.water; pt["fill-antialias"] = false;', 'pt["fill-color"] = c.building; pt["fill-outline-color"] = c.building;',
                 'has(id, "casing", "railway") ? c.casing : c.road', 'scaleZoomValue(pt["line-width"], 1.25)',
                 'const NAME = ["coalesce", ["get", "name:ko"], ["get", "name"]];', 'delete lay["icon-image"];',
                 '!has(l.id, "shield")', 'l.id !== "highway-name-path" && l.id !== "highway-name-minor"', 'lay["text-size"] = 11;',
                 'if (id === "highway-name-major") l.minzoom = 15;', 'if (id === "label_other") l.minzoom = 14;', 'pt["text-color"] = c.label;'):
        assert part in style, part
    assert "https://tiles.openfreemap.org/styles/positron" in page
    # 평면 지도도 같은 색 (바탕·길)
    light = page.split('.mapcard[data-map="light"] {', 1)[1].split("}", 1)[0]
    assert "--map-bg: #EDEDED" in light and "--map-grid: #FFFFFF" in light


def test_base_map_fallback_order_and_libraries(page):
    """벡터(OpenFreeMap) → 래스터(CARTO → OpenTopoMap) → 평면 지도. 라이브러리는 정확한 버전 + SRI. 저작자 표시."""
    tiles = page.split("const TILES = [", 1)[1].split("];", 1)[0]
    assert tiles.index('name: "vector"') < tiles.index('name: "carto"') < tiles.index('name: "topo"')
    assert '<script src="https://unpkg.com/maplibre-gl@5.24.0/dist/maplibre-gl.js" integrity="sha384-' in page
    assert '<script src="https://unpkg.com/@maplibre/maplibre-gl-leaflet@0.1.4/leaflet-maplibre-gl.js" integrity="sha384-' in page
    assert 'href="https://unpkg.com/maplibre-gl@5.24.0/dist/maplibre-gl.css" integrity="sha384-' in page
    use = page.split("if (TILES[state.tileIdx].vector) {", 1)[1].split("layer = tileLayer(maxZoom);", 1)[0]
    for reason in ('next("vector-lib", at)', 'next("timeout", at)', 'next("vector-error", at)', 'next("style", at)'):
        assert reason in use, reason
    assert "if (state.tileIdx < TILES.length - 1) { state.tileIdx++; use(); } else onPlane(reason);" in page
    assert ('&copy; <a href="https://openfreemap.org">OpenFreeMap</a> &copy; <a href="https://www.openmaptiles.org/">OpenMapTiles</a> '
            '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors') in page
    assert "attributionControl: { customAttribution: TILES[state.tileIdx].attribution }" in page
    assert len(re.findall(r"attachTiles\(map, \d+,", page)) == 3  # 검사 결과 위치 지도·점검 이력 지도도 같은 바탕 지도
