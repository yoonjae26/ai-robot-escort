"""HTML 대시보드 생성 (계획서 8장).

하나의 HTML 안에서 왼쪽 사이드바로 4페이지를 전환한다
(주소 해시: #home/<id>, #visual/<id>, #physical/<id>, #history/<YYYY-MM-DD>).
- 종합 현황: KPI 4개, 큰 지도(판정 색 + 종류 모양, 흔들림은 점선 고리), 판정 필터, 지도 옆 지점 상세 패널
- 외관 검사: 흔들림을 뺀 지점(단차·경사·균열) 목록 + 상세 (사진, 값, 기준, 교차 측정, 측정 근거)
- 물리적 안정성 검사: 흔들림 지점 목록 + 상세 (사진, 발끝 높이 그래프, 추가 침하, 측정 근거, 외관 검사 비교)
- 점검 이력: 점검 날짜 고르기(칩 + 달력), 그날의 KPI 4개(점검 거리·위험·주의·정상), 그날 지도(이동경로 + 100 m 눈금 +
  출발·도착 + 마커, 경로 켜고 끄기) + 종류별 판정 누적 막대, 지점 표(필터·정렬·이동, 정상은 접어 둠),
  현재 필터 결과 CSV 다운로드(events.csv와 같은 열·형식, BOM),
  같은 폴더의 report.html 열기. 지난 날짜는 events.csv 폴더의 history/<YYYY-MM-DD>/에서 읽는다
- 지도: 최대 확대에서도 묶인 마커는 누르면 부채꼴로 펼친다
- 사이드바 아래: 측정 세션 정보 (세션, 측정 시간, 구간, 로봇). 네이비 테마, 다크 기본, 라이트 전환 가능
- 배경: Leaflet + OpenTopoMap 타일을 회색조로 표시. 지도 배경은 페이지 테마와 따로 고른다
  (밝은 지도 기본: 옅은 회청색 / 어두운 지도: 반전 네이비 톤). 판정 색이 배경 도로 색과 섞이지 않게 하기 위함이다.
- 타일이나 Leaflet을 불러오지 못하거나, 타일이 실제 지도가 아닌 대체 이미지(차단·워터마크)이면
  odom (x, y) 평면 SVG 지도로 자동 전환한다.
입력은 events.csv, trajectory.csv 두 파일(가장 최근 점검)과 지난 점검 폴더이고, 데이터는 JSON으로 HTML 안에 넣는다.
"""

from __future__ import annotations

import html
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .events import (DEFAULT_THRESHOLDS, EVENT_COLUMNS, PATH_MIN_STEP_M, _fmt, criterion_text, display_meters, exceed_ratio,
                     extra_sink, group_foot_traces, path_length, read_events, read_foot_traces, read_trajectory)
from .photos import prepare_photos

LEAFLET_VERSION = "1.9.4"
LEAFLET_CSS = f"https://unpkg.com/leaflet@{LEAFLET_VERSION}/dist/leaflet.css"
LEAFLET_JS = f"https://unpkg.com/leaflet@{LEAFLET_VERSION}/dist/leaflet.js"
LEAFLET_CSS_SRI = "sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
LEAFLET_JS_SRI = "sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
# 글꼴: Pretendard 가변 글꼴 (쓰는 글자 묶음만 받는 dynamic subset). 렌더링을 막지 않게 불러오고,
# 인터넷이 없으면 시스템 한글 글꼴(Apple SD Gothic Neo, Malgun Gothic, Noto Sans KR)로 대체된다.
FONT_CSS = "https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css"
FONT_CSS_SRI = "sha384-uR1wgObmx89ZQ4VVXHdzjbDJZ1PvBK01K+E3GebmaBKdZ87qRJvBWPoPbzWeEd5T"

# OpenTopoMap: API 키 없이 file://로 연 HTML에서도 실제 지도를 준다 (2026-10 확인).
# - OSM 공식 타일 서버는 Referer 없는 요청에 403 "Access blocked" 이미지를 준다.
# - CARTO basemap은 키 없는 요청에 "API KEY REQUIRED" 워터마크 이미지를 준다.
TILE_URL = "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png"
TILE_MAX_NATIVE_ZOOM = 17  # 그 위는 확대 표시
TILE_ATTRIBUTION = ('&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, SRTM | '
                    '&copy; <a href="https://opentopomap.org">OpenTopoMap</a> '
                    '(<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA</a>)')

_EVENT_FIELDS = ["id", "t", "x", "y", "kind", "value", "unit", "source", "leg", "confidence",
                 "level", "note", "value_foot", "lat", "lon"]


class MissingLatLon(ValueError):
    pass


REPORT_NAME = "report.html"  # stepmap report 기본 출력 이름
HISTORY_DIR = "history"      # 지난 점검: <events.csv 폴더>/history/<YYYY-MM-DD>/events.csv, trajectory.csv
ROUTE_TICK_M = 100           # 점검 이력 지도: 경로를 따라 이 간격마다 누적 거리 눈금
KST = timezone(timedelta(hours=9))
WEEKDAYS = "월화수목금토일"
NEAR_VISUAL_M = 1.0  # 물리적 안정성 상세의 "외관 검사 비교" 반경


def near_visual_issues(e: dict, events: list[dict], radius: float = NEAR_VISUAL_M) -> list[str]:
    """흔들림 지점 radius m 안의 외관 이상(단차·경사·균열의 위험·주의) 지점 id, 가까운 순."""
    near = [(math.hypot(o["x"] - e["x"], o["y"] - e["y"]), o["id"]) for o in events
            if o["kind"] != "loose" and o["level"] != "ok"]
    return [i for d, i in sorted(near) if d <= radius + 1e-9]


def trace_payload(trace: dict | None) -> dict | None:
    """발끝 기록 + 추가 침하 계산 결과 (그래프와 값 상자가 쓰는 값)."""
    if not trace:
        return None
    r = extra_sink(trace)
    return {"leg": trace["leg"], "n": trace["n_normal"], "t": trace["t"], "step": trace["z_step"],
            "mean": trace["z_mean"], "lo": trace["z_lo"], "hi": trace["z_hi"],
            "extra": round(r["extra_mm"], 2), "contact": round(r["contact_diff_mm"], 2),
            "t_settle": r["t_settle_step"]}


def build_payload(events: list[dict], traj: list[dict], thresholds: dict | None = None,
                  photos: dict | None = None, meta: dict | None = None, traces: dict | None = None,
                  report_href: str | None = None, history: list[tuple[list[dict], list[dict]]] | None = None) -> dict:
    """photos: prepare_photos 결과 {id: {src, w, h, mark, overlay}}. 사진이 없는 지점은 photo=None.
    meta: 세션 정보 {"area": 구간, "robot": 로봇} (config.yaml의 report.area, robot.name).
    report_href: 점검 이력의 "신고서 열기" 주소 (없으면 버튼을 숨긴다).
    각 지점의 csv: events.csv에 쓰는 것과 같은 형식의 칸 문자열 (점검 이력 CSV 다운로드가 그대로 이어 붙인다).
    history: 지난 점검 [(events, trajectory)] (점검 이력 페이지만 쓴다). 가장 최근 날짜와 같은 날은 건너뛴다."""
    _check_latlon(events, traj)
    sessions = sorted({e["session"] for e in events})
    th = thresholds or DEFAULT_THRESHOLDS
    latest = run_date(events, traj)
    past = [(d, ev, tr) for ev, tr in (history or []) if (d := run_date(ev, tr)) and d != latest]
    for _, ev, tr in past:
        _check_latlon(ev, tr)
    return {
        "session": " · ".join(sessions),
        "t0": traj[0]["t"] if traj else None,
        "t1": traj[-1]["t"] if traj else None,
        "area": (meta or {}).get("area") or "",
        "robot": (meta or {}).get("robot") or "",
        "distance_m": path_length(traj),  # 1m 미만 흔들림은 거른다. 반올림은 화면에서 한 번만
        "thresholds": {k: list(v) for k, v in th.items()},
        "trajectory": [[round(p["lat"], 7), round(p["lon"], 7)] for p in traj],
        "trajectory_xy": [[round(p["x"], 2), round(p["y"], 2)] for p in traj],
        "report": report_href,
        "csv_columns": EVENT_COLUMNS,
        "events": [event_payload(e, events, th, photos, traces) for e in events],
        # 점검 날짜 (최신순). 가장 최근 날짜는 위 events를 쓰고(events: null), 지난 날짜는 그날의 지점을 넣는다.
        # meters: 점검 거리 (display_meters, 신고서와 같은 반올림)
        # route: 점검 이력 지도의 그날 이동 경로·100 m 눈금 (route_payload)
        "dates": sorted([{"date": latest, "meters": display_meters(path_length(traj)), "route": route_payload(traj),
                          "events": None}] * bool(latest) +
                        [{"date": d, "meters": display_meters(path_length(tr)), "route": route_payload(tr),
                          "events": [event_payload(e, ev, th) for e in ev]}
                         for d, ev, tr in past], key=lambda x: x["date"], reverse=True),
    }


def _check_latlon(events: list[dict], traj: list[dict]) -> None:
    if any(p["lat"] is None for p in traj) or any(e["lat"] is None for e in events):
        raise MissingLatLon("지도 표시에는 lat, lon이 필요합니다. config.yaml의 geo를 채운 뒤 다시 생성하세요.")


def event_payload(e: dict, events: list[dict], th: dict, photos: dict | None = None, traces: dict | None = None) -> dict:
    """지점 하나의 화면용 값. events: 같은 날 지점 전체 (흔들림의 외관 검사 비교용)."""
    return {**{k: e[k] for k in _EVENT_FIELDS}, "session": e["session"],
            "csv": [_fmt(c, e.get(c)) for c in EVENT_COLUMNS],
            "criterion": criterion_text(e["kind"], e["level"], th),
            "ratio": round(exceed_ratio(e["kind"], e["level"], e["value"], th), 4),  # 신고서와 같은 정렬 기준
            "photo": (photos or {}).get(e["id"]),
            **({"trace": trace_payload((traces or {}).get(e["id"])),
                "near_visual": near_visual_issues(e, events)} if e["kind"] == "loose" else {})}


def route_payload(traj: list[dict], min_step: float = PATH_MIN_STEP_M, tick_m: float = ROUTE_TICK_M) -> dict:
    """점검 이력 지도의 이동 경로. path_length와 같은 규칙으로 고른 점(직전 채택 점에서 min_step 이상)만 잇고
    마지막 점을 더한다. 그래서 누적 거리의 끝(total)이 path_length와 같다 (KPI 점검 거리 = display_meters(total)).
    ll: [위도, 경도], xy: odom [x, y] (평면 지도), ticks: tick_m마다 누적 거리 눈금 {m, i(놓인 구간 = ll[i]~ll[i+1]), ll, xy}."""
    if not traj:
        return {"ll": [], "xy": [], "ticks": [], "total": 0.0}
    pts, cum, anchor = [traj[0]], [0.0], traj[0]
    for p in traj[1:]:
        d = math.hypot(p["x"] - anchor["x"], p["y"] - anchor["y"])
        if d >= min_step:
            pts.append(p)
            cum.append(cum[-1] + d)
            anchor = p
    if traj[-1] is not anchor:  # 남은 거리 (path_length와 같은 순서로 더한다)
        pts.append(traj[-1])
        cum.append(cum[-1] + math.hypot(traj[-1]["x"] - anchor["x"], traj[-1]["y"] - anchor["y"]))
    ticks, i = [], 0
    m = tick_m
    while m < cum[-1]:
        while cum[i + 1] < m:
            i += 1
        a = (m - cum[i]) / (cum[i + 1] - cum[i])
        at = lambda k: pts[i][k] + (pts[i + 1][k] - pts[i][k]) * a
        ticks.append({"m": int(m), "i": i, "ll": [round(at("lat"), 7), round(at("lon"), 7)], "xy": [round(at("x"), 2), round(at("y"), 2)]})
        m += tick_m
    return {"ll": [[round(p["lat"], 7), round(p["lon"], 7)] for p in pts], "xy": [[round(p["x"], 2), round(p["y"], 2)] for p in pts],
            "ticks": ticks, "total": cum[-1]}


def run_date(events: list[dict], traj: list[dict]) -> str | None:
    """점검 날짜 (KST, YYYY-MM-DD): 궤적 첫 시각, 궤적이 없으면 가장 이른 지점 시각."""
    ts = [traj[0]["t"]] if traj else [e["t"] for e in events]
    return datetime.fromtimestamp(min(ts), KST).strftime("%Y-%m-%d") if ts else None


def read_history(folder: str | Path) -> list[tuple[list[dict], list[dict]]]:
    """지난 점검 폴더의 날짜별 (events, trajectory). 두 파일이 모두 있는 하위 폴더만."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return [(read_events(d / "events.csv"), read_trajectory(d / "trajectory.csv")) for d in sorted(folder.iterdir())
            if (d / "events.csv").is_file() and (d / "trajectory.csv").is_file()]


def date_chip_label(date: str) -> str:
    """2026-10-20 → 10.20 (화)"""
    d = datetime.strptime(date, "%Y-%m-%d")
    return f"{d.month:02d}.{d.day:02d} ({WEEKDAYS[d.weekday()]})"


def date_chips_html(dates: list[dict], latest_events: list[dict]) -> str:
    """점검 날짜 칩 (최신순, 처음엔 가장 최근 날짜 선택). 왼쪽 점: 그날 가장 높은 판정 색."""
    out = []
    for i, d in enumerate(dates):
        evs = latest_events if d["events"] is None else d["events"]
        worst = next((lv for lv in ("danger", "warn", "ok") if any(e["level"] == lv for e in evs)), "none")
        label = {"danger": "위험", "warn": "주의", "ok": "정상", "none": "지점 없음"}[worst]
        out.append(f'<button type="button" class="h-chip" data-date="{d["date"]}" aria-pressed="{str(i == 0).lower()}" '
                   f'title="{d["date"]} · 가장 높은 판정: {label}"><span class="h-dot h-dot-{worst}" aria-hidden="true"></span>'
                   f'{date_chip_label(d["date"])}</button>')
    return "".join(out)


# 종합 현황 지도의 판정 필터: 처음엔 위험만 켠다. 개수는 전체 지점 기준 (꺼도 그대로)
LEVEL_FILTER = (("danger", "위험", True), ("warn", "주의", False), ("ok", "정상", False))


def level_filter_html(events: list[dict]) -> str:
    return "".join(
        f'<button type="button" class="lv-btn" data-level="{lv}" aria-pressed="{str(on).lower()}">'
        f'<span class="dot" aria-hidden="true"></span>{label} <span class="n">{sum(e["level"] == lv for e in events)}</span></button>'
        for lv, label, on in LEVEL_FILTER)


def build_html(events: list[dict], traj: list[dict], thresholds: dict | None = None,
               photos: dict | None = None, meta: dict | None = None, traces: dict | None = None,
               report_href: str | None = None, history: list[tuple[list[dict], list[dict]]] | None = None) -> str:
    payload = build_payload(events, traj, thresholds, photos, meta, traces, report_href, history)
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    title = html.escape(f"StepMap · {payload['session']}" if payload["session"] else "StepMap")
    return (_TEMPLATE
            .replace("__TITLE__", title)
            .replace("__LEAFLET_CSS__", LEAFLET_CSS)
            .replace("__LEAFLET_CSS_SRI__", LEAFLET_CSS_SRI)
            .replace("__FONT_CSS__", FONT_CSS)
            .replace("__FONT_CSS_SRI__", FONT_CSS_SRI)
            .replace("__LEAFLET_JS__", LEAFLET_JS)
            .replace("__LEAFLET_JS_SRI__", LEAFLET_JS_SRI)
            .replace("__TILE_URL__", TILE_URL)
            .replace("__TILE_MAX_NATIVE_ZOOM__", str(TILE_MAX_NATIVE_ZOOM))
            .replace("__TILE_ATTRIBUTION__", TILE_ATTRIBUTION)
            .replace("__LEVEL_FILTER__", level_filter_html(events))
            .replace("__DATE_CHIPS__", date_chips_html(payload["dates"], events))
            .replace("__DATA__", data))


def write_dashboard(events_path: str | Path, traj_path: str | Path, out_path: str | Path,
                    thresholds: dict | None = None, meta: dict | None = None,
                    traces_path: str | Path | None = None, history_dir: str | Path | None = None) -> Path:
    """traces_path: 발끝 기록 (기본: events.csv와 같은 폴더의 foot_traces.csv). 없으면 그래프 자리에 "발끝 기록 없음".
    history_dir: 지난 점검 폴더 (기본: events.csv와 같은 폴더의 history/). 없으면 점검 이력에 가장 최근 날짜만.
    같은 폴더에 report.html이 있으면 점검 이력에 "신고서 열기" 버튼을 넣는다 (file://로 연 HTML은 옆 파일이
    있는지 브라우저가 확인할 수 없어서 만들 때 확인한다. 신고서를 나중에 만들었다면 map을 다시 실행)."""
    events = read_events(events_path)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    photos = prepare_photos(events, Path(events_path).parent, out.parent)  # 사본: <HTML 폴더>/photos/
    traces_path = Path(traces_path) if traces_path else Path(events_path).parent / "foot_traces.csv"
    traces = group_foot_traces(read_foot_traces(traces_path)) if traces_path.is_file() else {}
    report_href = REPORT_NAME if (out.parent / REPORT_NAME).is_file() else None
    history = read_history(history_dir if history_dir else Path(events_path).parent / HISTORY_DIR)
    page = build_html(events, read_trajectory(traj_path), thresholds, photos, meta, traces, report_href, history)
    out.write_text(page, encoding="utf-8")
    return out


_TEMPLATE = r"""<!doctype html>
<html lang="ko" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<script>
  // 다크 테마 기본, 사용자가 고른 테마는 브라우저에 기억 (저장소를 못 쓰면 다크)
  try { if (localStorage.getItem("stepmap-theme") === "light") document.documentElement.dataset.theme = "light"; } catch (e) {}
</script>
<link rel="stylesheet" href="__LEAFLET_CSS__" integrity="__LEAFLET_CSS_SRI__" crossorigin="">
<link rel="stylesheet" href="__FONT_CSS__" integrity="__FONT_CSS_SRI__" crossorigin="anonymous" media="print" onload="this.media='all'">
<style>
  /* ---------- 색 토큰: 네이비 다크 (기본) ---------- */
  :root {
    color-scheme: dark;
    --font: "Pretendard Variable", Pretendard, -apple-system, BlinkMacSystemFont, system-ui, "Apple SD Gothic Neo",
            "Malgun Gothic", "Noto Sans KR", sans-serif;
    --bg: #0B1220; --side-bg: #0E1629; --surface: #131C31; --surface-2: #1A2540;
    --border: #23304D; --border-hi: #3B5BDB; --head-bg: rgb(11 18 32 / 0.78);
    --text: #E7ECF5; --muted: #93A1BC; --accent: #4F8BFF; --on-accent: #0B1220; --focus: #4F8BFF;
    --grid: #1C2742;
    --danger: #F25F5C; --warn: #F5B841; --ok: #2BB673;
    --danger-ink: #FF8E8B; --warn-ink: #F7C766; --ok-ink: #4ED39B;
    --shadow: 0 1px 2px rgb(0 0 0 / 0.22), 0 8px 24px rgb(0 0 0 / 0.18);
    --shadow-pop: 0 2px 4px rgb(0 0 0 / 0.3), 0 10px 28px rgb(0 0 0 / 0.38);
    --band: #2C3A5A; --mean: #C9D2E3; --step: #FF6B68;
    --fs-title: 24px; --fs-h2: 16px; --fs-body: 14px; --fs-small: 12.5px; --fs-xs: 11.5px;
  }
  /* ---------- 라이트: 네이비 강조 ---------- */
  :root[data-theme="light"] {
    color-scheme: light;
    --bg: #F5F7FB; --side-bg: #EDF1F8; --surface: #FFFFFF; --surface-2: #F1F4FA;
    --border: #DCE3EF; --border-hi: #2350C8; --head-bg: rgb(245 247 251 / 0.8);
    --text: #0F1A2E; --muted: #4D5B76; --accent: #2350C8; --on-accent: #FFFFFF; --focus: #2350C8;
    --grid: #E3E8F2;
    --danger-ink: #B42318; --warn-ink: #8A5300; --ok-ink: #066633;
    --shadow: 0 1px 2px rgb(15 26 46 / 0.06), 0 8px 24px rgb(15 26 46 / 0.06);
    --shadow-pop: 0 2px 4px rgb(15 26 46 / 0.12), 0 10px 28px rgb(15 26 46 / 0.2);
    --band: #D6DEEB; --mean: #66748F; --step: #E2433F;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; background: var(--bg); color: var(--text); font: var(--fs-body)/1.55 var(--font);
               -webkit-font-smoothing: antialiased; }
  button { font: inherit; color: inherit; }
  :focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
  h1 { font-size: var(--fs-title); font-weight: 750; letter-spacing: -0.3px; margin: 0; }
  h2 { font-size: var(--fs-h2); font-weight: 700; letter-spacing: -0.1px; margin: 0 0 12px; }
  a { color: var(--accent); }

  /* ---------- 뼈대: 왼쪽 사이드바 + 본문 ---------- */
  .app { display: grid; grid-template-columns: 248px minmax(0, 1fr); min-height: 100vh; }
  .side { position: sticky; top: 0; height: 100vh; overflow: auto; display: flex; flex-direction: column; gap: 22px;
          padding: 24px 16px 18px; background: var(--side-bg); border-right: 1px solid var(--border); }
  .brand { padding: 0 10px; font-size: 20px; font-weight: 800; letter-spacing: -0.4px; }
  .brand small { display: block; margin-top: 2px; color: var(--muted); font-size: var(--fs-small); font-weight: 500; letter-spacing: 0; }
  .nav { display: grid; gap: 4px; }
  .nav a { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: 10px; color: var(--muted);
           text-decoration: none; font-weight: 600; transition: background 0.15s, color 0.15s; }
  .nav a:hover { background: var(--surface-2); color: var(--text); }
  .nav a[aria-current="page"] { background: color-mix(in srgb, var(--accent) 14%, transparent); color: var(--text);
                                box-shadow: inset 3px 0 0 var(--accent); }
  .nav a[aria-current="page"] svg { color: var(--accent); }
  .nav svg { width: 18px; height: 18px; flex: none; }
  .nav .short { display: none; }
  .session { margin-top: auto; padding: 16px; border: 1px solid var(--border); border-radius: 16px; background: var(--surface);
             font-size: var(--fs-small); }
  .session h2 { font-size: var(--fs-xs); font-weight: 700; color: var(--muted); letter-spacing: 0.4px; margin: 0 0 10px; }
  .session dl { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 6px 12px; margin: 0; }
  .session dt { color: var(--muted); }
  .session dd { margin: 0; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
  .session dd#s-session { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; font-size: var(--fs-xs); }
  .theme-btn { margin-top: 14px; width: 100%; padding: 8px 12px; border-radius: 10px; border: 1px solid var(--border);
               background: var(--surface-2); color: var(--text); cursor: pointer; text-align: left; font-size: var(--fs-small); }
  .theme-btn:hover { border-color: var(--border-hi); }
  .main { min-width: 0; padding: 0 28px 48px; }

  /* 상단 제목줄: 한 줄로 얇게 (제목 + 오른쪽에 세션·구간·시각). 스크롤해도 붙어 있게, 반투명 + 흐림 */
  .page-head { position: sticky; top: 0; z-index: 40; display: flex; flex-wrap: wrap; align-items: baseline; column-gap: 16px; row-gap: 2px;
               margin: 0 -28px; padding: 12px 28px;
               background: var(--head-bg); -webkit-backdrop-filter: blur(12px) saturate(1.3); backdrop-filter: blur(12px) saturate(1.3);
               border-bottom: 1px solid color-mix(in srgb, var(--border) 70%, transparent); }
  .page-head h1 { flex: none; font-size: 20px; line-height: 1.3; }
  .page-head .sub { flex: 1 1 0; min-width: 0; margin: 0; color: var(--muted); font-size: var(--fs-small); text-align: right;
                    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .page-head .crumbs { flex: 1 0 100%; margin: 0; }

  /* ---------- 판정 배지: 옅은 배경 + 진한 글자 + 기호 ---------- */
  .lv { display: inline-flex; align-items: center; gap: 4px; padding: 2px 9px 2px 7px; border-radius: 10px;
        background: color-mix(in srgb, var(--c) 16%, transparent); color: var(--ink); font-size: var(--fs-small);
        font-weight: 700; line-height: 1.45; white-space: nowrap; }
  .lv .sw { min-width: 11px; text-align: center; font-size: var(--fs-xs); font-weight: 800; }
  .lv-danger { --c: var(--danger); --ink: var(--danger-ink); }
  .lv-warn   { --c: var(--warn);   --ink: var(--warn-ink); }
  .lv-ok     { --c: var(--ok);     --ink: var(--ok-ink); }
  .ico { width: 18px; height: 18px; flex: none; overflow: visible; }

  /* ---------- KPI ---------- */
  /* 본문 전체 폭(지도 + 오른쪽 목록)을 같은 너비 4칸으로. 한 칸 220px 미만이 되면 2×2 */
  .kpis { display: grid; grid-template-columns: repeat(4, minmax(220px, 1fr)); gap: 16px; width: 100%; margin: 16px 0; }
  /* 가로형: [아이콘 원] [라벨 / 큰 숫자 + 옆에 배지·보조 설명] */
  .kpi { display: grid; grid-template-columns: 36px auto minmax(0, 1fr); grid-template-rows: auto auto; column-gap: 12px; row-gap: 6px;
         align-items: center; padding: 16px 20px; min-width: 0; background: var(--surface); border: 1px solid var(--border);
         border-radius: 16px; box-shadow: var(--shadow); }
  .kpi-ico { grid-row: 1 / 3; display: inline-grid; place-items: center; width: 36px; height: 36px; border-radius: 50%;
             background: color-mix(in srgb, var(--c, var(--accent)) 16%, transparent); color: var(--c, var(--accent)); }
  .kpi-ico svg { width: 18px; height: 18px; }
  .kpi-ico.ok { --c: var(--ok); } .kpi-ico.warn { --c: var(--warn); } .kpi-ico.danger { --c: var(--danger); }
  .kpi .label { grid-column: 2 / 4; min-width: 0; color: var(--muted); font-size: var(--fs-small); font-weight: 600; line-height: 1.35;
                white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .kpi .label small { margin-left: 4px; font-size: var(--fs-xs); font-weight: 500; }
  .kpi .value { grid-column: 2; font-size: 29px; font-weight: 750; line-height: 1.1; letter-spacing: -0.5px; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .kpi .value small { font-size: 14px; font-weight: 600; color: var(--muted); margin-left: 2px; letter-spacing: 0; }
  .kpi .sub { grid-column: 3; display: flex; flex-wrap: wrap; align-items: center; gap: 3px 8px; min-width: 0; padding-left: 4px;
              color: var(--muted); font-size: var(--fs-xs); line-height: 1.3; word-break: keep-all; }
  .kpi .sub > span { display: inline-flex; align-items: center; gap: 3px; color: var(--text); font-variant-numeric: tabular-nums; white-space: nowrap; }
  .kpi .sub .lv { padding: 0 6px 0 5px; font-size: var(--fs-xs); line-height: 1.4; }

  /* ---------- 종합 현황: 지도 + 위험·주의 목록 ---------- */
  .home-grid { display: grid; grid-template-columns: minmax(0, 1fr) 380px; gap: 16px; }
  .mapcard { display: grid; gap: 12px; min-width: 0; }
  /* 지도 배경은 페이지 테마와 따로 고른다 (밝은 지도 기본). 경로·마커·조작 버튼 색도 지도 배경에 맞춘다 */
  .mapcard[data-map="light"] {
    --map-bg: #EEF2F7; --tile-filter: grayscale(1) contrast(0.82) brightness(1.02) sepia(0.3) hue-rotate(180deg) saturate(1.5); --tile-opacity: 0.55;
    --map-grid: #D3DBE7; --map-text: #0F1A2E; --map-leader: #0F1A2E;
    --m-danger: #C8302C; --m-warn: #A35F00; --m-ok: #12805C; --m-ink: #FFFFFF; --m-ring: #0B1220; --m-focus: #2350C8;
    --ctl-bg: #FFFFFF; --ctl-hover: #EEF2F7; --ctl-text: #0F1A2E; --ctl-muted: #4D5B76; --ctl-border: #C3CDDD; --ctl-link: #2350C8;
    --ctl-on: #2350C8; --ctl-on-text: #FFFFFF; --ctl-shadow: 0 1px 2px rgb(15 26 46 / 0.12), 0 4px 12px rgb(15 26 46 / 0.12);
  }
  .mapcard[data-map="dark"] {
    --map-bg: #0B1220; --tile-filter: grayscale(1) invert(1) brightness(0.9) contrast(0.9) sepia(1) hue-rotate(180deg) saturate(1.6) brightness(0.7);
    --tile-opacity: 1;
    --map-grid: #1C2742; --map-text: #E7ECF5; --map-leader: #E7ECF5;
    --m-danger: #F25F5C; --m-warn: #F5B841; --m-ok: #2BB673; --m-ink: #0B1220; --m-ring: #0B1220; --m-focus: #4F8BFF;
    --ctl-bg: #131C31; --ctl-hover: #1A2540; --ctl-text: #E7ECF5; --ctl-muted: #93A1BC; --ctl-border: #2C3A5A; --ctl-link: #7FAAFF;
    --ctl-on: #4F8BFF; --ctl-on-text: #0B1220; --ctl-shadow: 0 1px 2px rgb(0 0 0 / 0.3), 0 4px 12px rgb(0 0 0 / 0.3);
  }
  .mapbox { position: relative; isolation: isolate; height: clamp(440px, calc(100vh - 330px), 760px); border: 1px solid var(--border);
            border-radius: 16px; overflow: hidden; background: var(--map-bg); box-shadow: var(--shadow); }
  #map, #plane { position: absolute; inset: 0; }
  :is(#map, #h-map).leaflet-container { background: var(--map-bg); font: var(--fs-small) var(--font); }
  :is(#map, #h-map) .leaflet-tile-pane { filter: var(--tile-filter); opacity: var(--tile-opacity); }
  :is(#map, #h-map) .leaflet-bar { border: 1px solid var(--ctl-border); border-radius: 10px; overflow: hidden; box-shadow: var(--ctl-shadow); }
  :is(#map, #h-map) .leaflet-bar a { width: 32px; height: 32px; line-height: 32px; background: var(--ctl-bg); color: var(--ctl-text); border-bottom: 1px solid var(--ctl-border); }
  :is(#map, #h-map) .leaflet-bar a:hover { background: var(--ctl-hover); }
  :is(#map, #h-map) .leaflet-bar a.leaflet-disabled { color: var(--ctl-muted); background: var(--ctl-bg); opacity: 0.6; }
  :is(#map, #h-map) .leaflet-control-attribution { padding: 2px 8px; border-radius: 10px 0 0 0; color: var(--ctl-muted);
                                      background: color-mix(in srgb, var(--ctl-bg) 90%, transparent); }
  :is(#map, #h-map) .leaflet-control-attribution a { color: var(--ctl-link); }
  .map-tools { position: absolute; top: 12px; right: 12px; z-index: 600; display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
  .map-seg { display: inline-flex; padding: 3px; gap: 2px; border-radius: 10px; border: 1px solid var(--ctl-border);
             background: var(--ctl-bg); box-shadow: var(--ctl-shadow); }
  .map-seg button { padding: 5px 10px; border: 0; border-radius: 7px; background: none; color: var(--ctl-text);
                    font-size: var(--fs-small); font-weight: 600; cursor: pointer; }
  .map-seg button:hover { background: var(--ctl-hover); }
  .map-seg button[aria-pressed="true"] { background: var(--ctl-on); color: var(--ctl-on-text); }
  #plane svg { display: block; width: 100%; height: 100%; }
  .ev-marker, .ev-cluster { background: none; border: none; }
  .ev-marker svg, .ev-cluster svg { display: block; overflow: visible; }
  .ev-marker:focus-visible, .ev-cluster:focus-visible { outline: 2px solid var(--m-focus); outline-offset: 1px; border-radius: 8px; }
  #plane .ev { cursor: pointer; }
  #plane .ev:focus { outline: none; }
  #plane .ev:focus-visible .hit { stroke: var(--m-focus); stroke-width: 2; }
  .retry { padding: 6px 12px; font-size: var(--fs-small); font-weight: 600; border-radius: 10px;
           border: 1px solid var(--ctl-border); background: var(--ctl-bg); color: var(--ctl-text); cursor: pointer; box-shadow: var(--ctl-shadow); }
  .retry:hover { background: var(--ctl-hover); }
  .legend { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; padding: 12px 16px; color: var(--muted);
            font-size: var(--fs-small); background: var(--surface); border: 1px solid var(--border); border-radius: 12px; }
  .legend .item { display: inline-flex; align-items: center; gap: 6px; color: var(--text); }
  .legend .sep { width: 1px; height: 18px; background: var(--border); }
  /* 판정 필터: 켜짐 = 판정색 옅은 배경 + 진한 판정 글자색 테두리, 꺼짐 = 흐린 점 + 흐린 글자 (개수는 그대로) */
  .lv-filter { display: inline-flex; flex-wrap: wrap; gap: 6px; }
  .lv-btn { --c: var(--ok); --ink: var(--ok-ink); display: inline-flex; align-items: center; gap: 6px; padding: 4px 11px 4px 9px;
            border: 1px solid var(--border); border-radius: 999px; background: none; color: var(--muted);
            font-size: var(--fs-small); font-weight: 600; line-height: 1.45; cursor: pointer; transition: background 0.15s, border-color 0.15s; }
  .lv-btn[data-level="danger"] { --c: var(--danger); --ink: var(--danger-ink); }
  .lv-btn[data-level="warn"]   { --c: var(--warn);   --ink: var(--warn-ink); }
  .lv-btn .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--c); box-shadow: 0 0 0 1px var(--ink); opacity: 0.4; }
  .lv-btn .n { font-variant-numeric: tabular-nums; }
  .lv-btn:hover { border-color: var(--border-hi); color: var(--text); }
  .lv-btn[aria-pressed="true"] { background: color-mix(in srgb, var(--c) 16%, transparent); border-color: var(--ink); color: var(--text); font-weight: 700; }
  .lv-btn[aria-pressed="true"] .dot { opacity: 1; }
  .map-empty { position: absolute; left: 50%; top: 50%; z-index: 550; transform: translate(-50%, -50%); padding: 10px 16px;
               border: 1px solid var(--ctl-border); border-radius: 12px; background: var(--ctl-bg); color: var(--ctl-text);
               font-weight: 650; box-shadow: var(--ctl-shadow); pointer-events: none; white-space: nowrap; }
  .map-empty[hidden] { display: none; }
  /* 지도 옆 상세 패널: 마커를 누른 지점의 사진·측정값·근거. 길면 패널 안에서만 스크롤 */
  .dpanel { position: relative; display: flex; flex-direction: column; min-width: 0; padding: 18px 18px 20px; overflow: auto;
            background: var(--surface); border: 1px solid var(--border); border-radius: 16px; box-shadow: var(--shadow); }
  .dp-empty { margin: auto; padding: 32px 12px; color: var(--muted); text-align: center; word-break: keep-all; }
  .dp-empty .ico { display: block; width: 28px; height: 28px; margin: 0 auto 10px; }
  .dp-head { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 8px; padding-right: 40px; margin-bottom: 14px; }
  .dp-head .kind { display: inline-flex; align-items: center; gap: 5px; font-size: var(--fs-h2); font-weight: 700; }
  .dp-head .id { color: var(--muted); font-size: var(--fs-small); font-variant-numeric: tabular-nums; }
  .dp-close { position: absolute; top: 12px; right: 12px; display: grid; place-items: center; width: 32px; height: 32px; padding: 0;
              border: 1px solid var(--border); border-radius: 10px; background: var(--surface-2); color: var(--text); cursor: pointer; }
  .dp-close:hover { border-color: var(--border-hi); }
  .dp-close svg { width: 16px; height: 16px; }
  .dpanel .ph { --maxh: 260px; }
  .dpanel .ph-btn { margin-bottom: 4px; }
  .dpanel .no-photo { height: 140px; margin: 0 0 4px; }
  .dpanel .v-big { margin-top: 12px; }
  .dpanel .v-big .num { font-size: 44px; }
  .dpanel .v-crit { margin: 8px 0 14px; word-break: keep-all; }
  .dpanel .v-basis { margin-top: 0; padding-top: 14px; }
  .dpanel .v-basis dl { gap: 6px 14px; font-size: var(--fs-small); }
  .dp-actions { margin-top: 16px; }
  .dp-actions .btn { display: inline-flex; align-items: center; gap: 6px; text-decoration: none; }

  /* ---------- 외관 검사 · 물리적 안정성 (목록 + 상세) ---------- */
  .crumbs { margin: 0 0 6px; color: var(--muted); font-size: var(--fs-small); overflow-wrap: anywhere; }
  .crumbs a { color: var(--accent); text-decoration: none; font-weight: 600; }
  .crumbs a:hover { text-decoration: underline; }
  .v-tools { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; margin: 20px 0 16px; }
  .tabs { display: flex; flex-wrap: wrap; gap: 4px; padding: 4px; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; }
  .tabs button { display: inline-flex; align-items: center; gap: 6px; padding: 7px 14px; border: 0; border-radius: 8px; background: none;
                 color: var(--muted); font-weight: 600; cursor: pointer; }
  .tabs button:hover { color: var(--text); background: var(--surface-2); }
  .tabs button[aria-selected="true"] { background: color-mix(in srgb, var(--accent) 16%, transparent); color: var(--text);
                                       box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 55%, transparent); }
  .tabs .n { color: var(--muted); font-weight: 600; font-variant-numeric: tabular-nums; }
  .toggle { display: inline-flex; align-items: center; gap: 8px; color: var(--text); cursor: pointer; user-select: none; }
  .toggle input { width: 16px; height: 16px; accent-color: var(--accent); }
  .v-grid { display: grid; grid-template-columns: 372px minmax(0, 1fr); gap: 16px; align-items: start; }
  .v-list { display: grid; gap: 8px; max-height: calc(100vh - 230px); overflow: auto; padding: 2px; }
  .v-empty { padding: 28px 16px; color: var(--muted); text-align: center; border: 1px dashed var(--border); border-radius: 16px; }
  .v-row { width: 100%; display: grid; grid-template-columns: 56px minmax(0, 1fr); gap: 12px; padding: 10px; border: 1px solid var(--border);
           border-radius: 12px; background: var(--surface); text-align: left; cursor: pointer; transition: background 0.15s, border-color 0.15s; }
  .v-row:hover { background: var(--surface-2); }
  .v-row[aria-selected="true"] { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent);
                                 background: color-mix(in srgb, var(--accent) 8%, var(--surface)); }
  .v-thumb { width: 56px; height: 56px; display: grid; place-items: center; overflow: hidden; border-radius: 10px;
             border: 1px solid var(--border); background: var(--surface-2); }
  .v-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .v-thumb .ico { width: 26px; height: 26px; }
  .v-row .l1 { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; font-weight: 700; }
  .v-row .val { font-variant-numeric: tabular-nums; }
  .v-row .nt { margin-top: 2px; color: var(--muted); font-size: var(--fs-small); word-break: keep-all; overflow-wrap: anywhere; }
  .v-row .tm { margin-top: 2px; color: var(--muted); font-size: var(--fs-xs); font-variant-numeric: tabular-nums; }
  .v-detail { min-width: 0; padding: 24px; background: var(--surface); border: 1px solid var(--border); border-radius: 16px; box-shadow: var(--shadow); }
  .v-head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 12px; }
  .v-head .kind { display: inline-flex; align-items: center; gap: 8px; font-size: 18px; font-weight: 750; }
  .v-head .kind .ico { width: 22px; height: 22px; }
  .rep { padding: 4px 12px; border-radius: 10px; border: 1px solid var(--border); color: var(--muted); font-size: var(--fs-small); font-weight: 600; }
  .rep.in { border-color: color-mix(in srgb, var(--accent) 60%, transparent); background: color-mix(in srgb, var(--accent) 12%, transparent); color: var(--text); }
  .v-detail .d-photo { margin: 18px 0 10px; }
  .v-detail .ph { --maxh: 380px; }
  .no-photo { display: grid; place-items: center; align-content: center; gap: 6px; height: 160px; margin: 18px 0 10px;
              border: 1px dashed var(--border); border-radius: 12px; background: var(--surface-2); color: var(--muted); }
  .no-photo .ico { width: 30px; height: 30px; opacity: 0.7; }
  .v-big { display: flex; align-items: baseline; gap: 8px; margin: 10px 0 2px; }
  .v-big .num { font-size: 56px; font-weight: 780; line-height: 1; letter-spacing: -1px; font-variant-numeric: tabular-nums; }
  .v-big .unit { font-size: 20px; font-weight: 600; color: var(--muted); }
  .v-crit { margin: 8px 0 18px; font-weight: 650; }
  .v-crit .k, .v-crit .x { color: var(--muted); font-weight: 500; }
  .v-cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin: 0 0 18px; }
  .v-card { min-width: 0; padding: 12px 14px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface-2); }
  .v-card .k { color: var(--muted); font-size: var(--fs-small); overflow-wrap: anywhere; }
  .v-card .v { margin-top: 2px; font-size: 22px; font-weight: 750; font-variant-numeric: tabular-nums; }
  .v-card .s { color: var(--muted); font-size: var(--fs-xs); }
  .v-card.diff { border-color: color-mix(in srgb, var(--accent) 55%, var(--border)); box-shadow: inset 3px 0 0 var(--accent); }
  .v-basis { margin-top: 6px; padding-top: 18px; border-top: 1px solid var(--border); }
  .v-basis h2 { font-size: 15px; margin: 0 0 10px; }
  .v-basis dl { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 8px 16px; margin: 0; }
  .v-basis dt { color: var(--muted); }
  .v-basis dd { margin: 0; word-break: keep-all; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
  .v-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 20px; }
  .btn { padding: 9px 16px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface-2); font-weight: 650; cursor: pointer; }
  .btn:hover { border-color: var(--border-hi); }
  .btn.primary { background: var(--accent); border-color: var(--accent); color: var(--on-accent); }
  .btn.primary:hover { filter: brightness(1.08); }
  /* 사이드바 248 + 본문 여백 56 + 스크롤바 + 4×220 + 3×16 = 약 1250px 미만 → 2×2 */
  @media (max-width: 1259px) {
    .kpis { grid-template-columns: repeat(2, minmax(220px, 1fr)); }
  }
  @media (max-width: 1000px) {
    .v-grid { grid-template-columns: minmax(0, 1fr); }
    .v-list { max-height: none; }
  }

  /* ---------- 물리적 안정성: 발끝 높이 그래프 ---------- */
  .fg { margin: 10px 0 18px; padding: 16px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface-2); }
  .fg-box { width: 100%; }
  .fg-box svg { display: block; width: 100%; height: auto; }
  .fg figcaption { margin-top: 8px; color: var(--muted); font-size: var(--fs-xs); word-break: keep-all; }
  .fg-empty { display: grid; place-items: center; height: 180px; border: 1px dashed var(--border); border-radius: 12px;
              background: var(--surface); color: var(--muted); }
  .p-near { margin: 18px 0 0; padding-top: 18px; border-top: 1px solid var(--border); }
  .p-near h2 { font-size: 15px; margin: 0 0 8px; }
  .p-near p { margin: 0; }
  .p-near ul { margin: 6px 0 0; padding-left: 18px; }
  .p-near a { color: var(--accent); font-weight: 600; }

  /* ---------- 점검 이력 ---------- */
  /* 날짜 고르기: 칩(최신순, 왼쪽 점 = 그날 가장 높은 판정) + 달력 */
  .h-dates { position: relative; display: flex; align-items: center; gap: 8px; min-width: 0; margin: 16px 0 0; }
  .h-dates[hidden] { display: none; }
  .h-chips { display: flex; gap: 8px; min-width: 0; padding: 2px; overflow-x: auto; scrollbar-width: thin; }
  .h-chip { display: inline-flex; align-items: center; gap: 7px; flex: none; padding: 7px 14px 7px 11px; border: 1px solid var(--border);
            border-radius: 999px; background: var(--surface); color: var(--text); font-size: var(--fs-small); font-weight: 650;
            font-variant-numeric: tabular-nums; cursor: pointer; transition: background 0.15s, border-color 0.15s; }
  .h-chip:hover { border-color: var(--border-hi); }
  .h-chip[aria-pressed="true"] { background: var(--accent); border-color: var(--accent); color: var(--on-accent); }
  .h-dot { width: 9px; height: 9px; flex: none; border-radius: 50%; box-shadow: 0 0 0 1.5px var(--surface); }
  .h-chip[aria-pressed="true"] .h-dot { box-shadow: 0 0 0 1.5px var(--on-accent); }
  .h-dot-danger { background: var(--danger); } .h-dot-warn { background: var(--warn); } .h-dot-ok { background: var(--ok); }
  .h-dot-none { background: var(--muted); }
  .h-cal-btn { display: grid; place-items: center; flex: none; width: 36px; height: 36px; padding: 0; border: 1px solid var(--border);
               border-radius: 10px; background: var(--surface); color: var(--text); cursor: pointer; }
  .h-cal-btn:hover, .h-cal-btn[aria-expanded="true"] { border-color: var(--accent); }
  .h-cal-btn svg { width: 18px; height: 18px; }
  .h-cal { position: absolute; top: calc(100% + 8px); left: 0; z-index: 60; width: 296px; padding: 14px; background: var(--surface);
           border: 1px solid var(--border); border-radius: 14px; box-shadow: var(--shadow-pop); }
  .h-cal[hidden] { display: none; }
  .h-cal-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; font-weight: 700; }
  .h-cal-head button { display: grid; place-items: center; width: 32px; height: 32px; padding: 0; border: 1px solid var(--border);
                       border-radius: 8px; background: var(--surface-2); color: var(--text); cursor: pointer; }
  .h-cal-head button:disabled { opacity: 0.4; cursor: default; }
  .h-cal-head svg { width: 14px; height: 14px; }
  .h-cal-grid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 2px; text-align: center; }
  .h-cal-grid .wd { padding: 4px 0; color: var(--muted); font-size: var(--fs-xs); font-weight: 600; }
  .h-cal-grid button { position: relative; height: 36px; padding: 0; border: 0; border-radius: 8px; background: none; color: var(--text);
                       font-weight: 700; font-variant-numeric: tabular-nums; cursor: pointer; }
  .h-cal-grid button:disabled { color: var(--muted); font-weight: 400; opacity: 0.45; cursor: default; }
  .h-cal-grid button:not(:disabled):hover { background: var(--surface-2); }
  .h-cal-grid button .h-dot { position: absolute; left: 50%; bottom: 3px; width: 6px; height: 6px; transform: translateX(-50%); }
  .h-cal-grid button[aria-pressed="true"] { background: var(--accent); color: var(--on-accent); }
  .h-cal-grid button[aria-pressed="true"] .h-dot { box-shadow: 0 0 0 1.5px var(--on-accent); }
  /* 점검 이력에서는 날짜를 위 날짜 줄에서 고른다: 사이드바의 측정 세션 제목·세션·측정 시간(가장 최근 점검)은 숨긴다 */
  .app:has(#page-history:not([hidden])) .session h2,
  .app:has(#page-history:not([hidden])) .session dl > :nth-child(-n+4) { display: none; }
  .h-tools { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 12px 16px; margin: 16px 0 6px; }
  .h-filters { display: flex; flex-wrap: wrap; gap: 8px 10px; min-width: 0; }
  .h-f { display: grid; gap: 4px; min-width: 0; color: var(--muted); font-size: var(--fs-xs); font-weight: 600; }
  .h-f select { min-width: 120px; max-width: 100%; padding: 8px 30px 8px 10px; border: 1px solid var(--border); border-radius: 10px;
                background: var(--surface) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M1 1l4 4 4-4' fill='none' stroke='%2393A1BC' stroke-width='1.6'/%3E%3C/svg%3E") no-repeat right 11px center;
                color: var(--text); font: 600 var(--fs-small) var(--font); appearance: none; cursor: pointer; }
  .h-f select:hover { border-color: var(--border-hi); }
  .h-f select.on { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }
  .h-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
  .h-actions .btn { display: inline-flex; align-items: center; gap: 6px; color: var(--text); text-decoration: none; font-size: var(--fs-small); }
  .h-actions .btn.primary { color: var(--on-accent); }
  .h-actions .btn[hidden] { display: none; }  /* 신고서 열기: 가장 최근 날짜에서만 */
  .h-actions .btn svg { width: 16px; height: 16px; }
  .h-note { margin: 4px 0 0; color: var(--muted); font-size: var(--fs-xs); text-align: right; }
  .h-reset { padding: 8px 10px; border: 0; background: none; color: var(--accent); font-size: var(--fs-small); font-weight: 600; cursor: pointer; }
  .h-reset:hover { text-decoration: underline; }
  /* KPI 아래: 왼쪽 지도(약 60%) + 오른쪽 종류별 판정, 그 아래 전체 폭 지점 목록. 1259px 이하는 세로로 */
  .h-grid { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 16px; margin: 16px 0; }
  @media (max-width: 1259px) { .h-grid { grid-template-columns: minmax(0, 1fr); } }
  .h-mapcard { display: block; --h-route: #4F8BFF; }
  .h-mapbox { position: relative; isolation: isolate; height: 440px; overflow: hidden; border: 1px solid var(--border);
              border-radius: 12px; background: var(--map-bg); }
  #h-map, #h-plane { position: absolute; inset: 0; }
  #h-plane svg { display: block; width: 100%; height: 100%; }
  #h-plane .ev:focus { outline: none; }
  #h-plane .ev:focus-visible .hit { stroke: var(--m-focus); stroke-width: 2; }
  #h-map path.h-route-casing { stroke: #FFFFFF; stroke-opacity: 0.95; }
  #h-map path.h-route-line { stroke: var(--h-route); }
  .h-route-btn { position: absolute; top: 12px; left: 12px; z-index: 600; display: inline-flex; align-items: center; gap: 7px;
                 padding: 6px 12px 6px 10px; border: 1px solid var(--ctl-border); border-radius: 10px; background: var(--ctl-bg);
                 color: var(--ctl-text); font-size: var(--fs-small); font-weight: 650; box-shadow: var(--ctl-shadow); cursor: pointer; }
  .h-route-btn:hover { background: var(--ctl-hover); }
  .h-route-btn .sw { width: 18px; height: 4px; border-radius: 2px; background: var(--h-route); box-shadow: 0 0 0 1.5px #FFFFFF; }
  .h-route-btn[aria-pressed="true"] { border-color: var(--h-route); box-shadow: inset 0 0 0 1px var(--h-route), var(--ctl-shadow); }
  .h-route-btn[aria-pressed="false"] { color: var(--ctl-muted); }
  .h-route-btn[aria-pressed="false"] .sw { opacity: 0.35; }
  /* 경로 눈금(100 m마다)·출발·도착: 원 + 글자 상자 (클릭되지 않음) */
  .h-pin { overflow: visible; pointer-events: none; }
  .h-tick, .h-end { position: absolute; left: 0; top: 0; }
  .h-tick i { position: absolute; left: -4px; top: -4px; width: 8px; height: 8px; box-sizing: border-box; border-radius: 50%;
              background: #FFFFFF; border: 2px solid var(--h-route); }
  .h-tick b, .h-end b { position: absolute; padding: 0 5px; border: 1px solid var(--ctl-border); border-radius: 6px; background: var(--ctl-bg);
                        color: var(--ctl-text); white-space: nowrap; box-shadow: var(--ctl-shadow); }
  .h-tick b { font: 650 10.5px/16px var(--font); }
  .h-tick.s-r b { left: 9px; top: -9px; }
  .h-tick.s-t b { left: 0; bottom: 15px; transform: translateX(-50%); }
  .h-end i { position: absolute; left: -7px; top: -7px; width: 14px; height: 14px; box-sizing: border-box; border-radius: 50%;
             border: 3px solid #FFFFFF; box-shadow: 0 0 0 1.5px #0B1220; }
  .h-end.start i { background: var(--h-route); }
  .h-end.finish i { background: #0B1220; }
  .h-end b { font: 750 11.5px/18px var(--font); }
  .h-end.s-r b { left: 12px; top: -10px; } .h-end.s-l b { right: 12px; top: -10px; }
  .h-end.s-t b { left: 0; bottom: 12px; transform: translateX(-50%); } .h-end.s-b b { left: 0; top: 12px; transform: translateX(-50%); }
  .h-card { min-width: 0; padding: 20px 24px; background: var(--surface); border: 1px solid var(--border); border-radius: 16px; box-shadow: var(--shadow); }
  .h-card h2 { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
  .h-card h2 small { color: var(--muted); font-size: var(--fs-small); font-weight: 600; font-variant-numeric: tabular-nums; }
  .h-empty { padding: 20px 0; color: var(--muted); text-align: center; }
  /* 종류별 판정 누적 막대: 칸 사이 2px, 칸 안에 기호 + 숫자, 오른쪽에 글자 요약 (색만으로 구분하지 않음) */
  .h-bars { display: grid; gap: 14px; }
  .h-bar { display: grid; grid-template-columns: 76px minmax(0, 1fr); align-items: center; gap: 4px 12px; }
  .h-bar .k { display: inline-flex; align-items: center; gap: 6px; font-weight: 650; font-size: var(--fs-small); }
  .h-bar .track { display: flex; gap: 2px; height: 26px; min-width: 0; }
  .h-bar .seg { display: flex; align-items: center; justify-content: center; min-width: 0; overflow: hidden; border-radius: 4px;
                color: #0B1220; font-size: var(--fs-xs); font-weight: 750; white-space: nowrap; font-variant-numeric: tabular-nums;
                container-type: inline-size; }
  @container (max-width: 26px) { .h-bar .seg span { visibility: hidden; } }
  .h-bar .seg.danger { background: var(--danger); } .h-bar .seg.warn { background: var(--warn); } .h-bar .seg.ok { background: var(--ok); }
  .h-bar .zero { color: var(--muted); font-size: var(--fs-xs); line-height: 26px; }
  .h-bar .line { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .h-bar .tot { font-size: var(--fs-small); font-weight: 750; font-variant-numeric: tabular-nums; }
  .h-bar .sum { grid-column: 2; color: var(--muted); font-size: var(--fs-xs); font-variant-numeric: tabular-nums; }
  .h-bars-total { margin: 16px 0 0; padding-top: 12px; border-top: 1px solid var(--border); color: var(--muted); font-size: var(--fs-small);
                  font-variant-numeric: tabular-nums; }
  .h-bars-total b { color: var(--text); font-weight: 700; }
  .h-card .h-tools { margin: 0 0 12px; }
  .h-more { display: block; width: 100%; margin-top: 10px; padding: 10px; border: 1px dashed var(--border); border-radius: 10px;
            background: none; color: var(--accent); font-size: var(--fs-small); font-weight: 650; cursor: pointer; }
  .h-more:hover { background: var(--surface-2); }
  .h-more[hidden] { display: none; }
  .h-table tbody tr.hl { background: var(--surface-2); }
  .h-bar .sum b { color: var(--text); font-weight: 650; }
  /* 표: 길면 표 안에서만 스크롤, 머리줄 고정 */
  .h-table-wrap { max-height: 560px; overflow: auto; margin: 0 -8px; padding: 0 8px; }
  .h-table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: var(--fs-small); font-variant-numeric: tabular-nums; }
  .h-table th { position: sticky; top: 0; z-index: 1; padding: 0; background: var(--surface); color: var(--muted); font-weight: 650;
                text-align: left; white-space: nowrap; border-bottom: 1px solid var(--border); }
  .h-table th > span, .h-table th > button { display: flex; align-items: center; gap: 4px; width: 100%; padding: 10px 10px; }
  .h-table th > button { border: 0; background: none; color: inherit; font: inherit; text-align: left; cursor: pointer; }
  .h-table th > button:hover { color: var(--text); }
  .h-table th[aria-sort] > button { color: var(--text); }
  .h-table th .arr { width: 10px; color: var(--accent); }
  .h-table td { padding: 10px; border-bottom: 1px solid color-mix(in srgb, var(--border) 70%, transparent); vertical-align: middle; }
  .h-table td.num { text-align: right; }
  .h-table th.num > span, .h-table th.num > button { justify-content: flex-end; }
  .h-table tbody tr { transition: background 0.15s; }
  .h-table.clickable tbody tr { cursor: pointer; }
  .h-table.clickable tbody tr:hover { background: var(--surface-2); }
  .h-table .kind { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
  .h-table .crit { color: var(--muted); word-break: keep-all; min-width: 140px; }
  .h-table .ll, .h-table .tm { color: var(--muted); white-space: nowrap; }
  .h-table .go { color: var(--accent); font-weight: 650; text-decoration: none; white-space: nowrap; }
  .h-table .go:hover { text-decoration: underline; }

  /* ---------- 툴팁 · 묶음 고르기 (카드 스타일) ---------- */
  .tip { position: fixed; z-index: 3000; pointer-events: none; max-width: 280px; padding: 10px 12px; border-radius: 12px;
         background: var(--surface); color: var(--text); border: 1px solid var(--border); box-shadow: var(--shadow-pop); font-size: var(--fs-xs); }
  .tip b { display: block; margin-bottom: 2px; font-size: var(--fs-small); }
  .tip div { color: var(--muted); }
  .tip .tip-go { color: var(--accent); font-weight: 650; margin-top: 4px; }
  .tip .tip-photo { display: flex; align-items: center; gap: 4px; color: var(--text); margin-top: 3px; }
  .picker { position: fixed; z-index: 3001; width: 260px; max-height: 300px; overflow: auto; padding: 6px; border-radius: 12px;
            background: var(--surface); border: 1px solid var(--border); box-shadow: var(--shadow-pop); }
  .picker button { width: 100%; display: flex; align-items: center; gap: 8px; padding: 8px 10px; border: 0; border-radius: 8px;
                   background: none; text-align: left; cursor: pointer; }
  .picker button:hover { background: var(--surface-2); }
  .cam { width: 14px; height: 14px; flex: none; }

  /* ---------- 현장 사진 ---------- */
  .d-photo { margin: 2px 0 14px; }
  .ph-btn { display: block; width: 100%; padding: 0; border: 0; background: none; cursor: zoom-in; border-radius: 12px; }
  .ph { position: relative; width: min(100%, calc(var(--maxh) * var(--ar))); aspect-ratio: var(--ar); margin: 0 auto;
        overflow: hidden; border-radius: 12px; border: 1px solid var(--border); background: var(--surface-2); --maxh: 300px; }
  .ph img { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
  .ph .ph-mark { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
  .d-photo figcaption { display: grid; justify-items: center; gap: 2px; margin-top: 8px; color: var(--muted); font-size: var(--fs-xs); text-align: center; }
  .d-photo .ph-cap { color: var(--text); font-size: var(--fs-small); font-weight: 650; word-break: keep-all; }
  .d-photo .ph-hint { display: inline-flex; align-items: center; gap: 5px; }
  .dlg { width: min(94vw, 980px); max-height: 94vh; padding: 0; border: 1px solid var(--border); border-radius: 16px;
         background: var(--surface); color: var(--text); box-shadow: var(--shadow); }
  .dlg::backdrop { background: rgb(5 9 18 / 0.72); -webkit-backdrop-filter: blur(4px); backdrop-filter: blur(4px); }
  .dlg-head { display: flex; align-items: center; gap: 8px; padding: 14px 16px 14px 20px; border-bottom: 1px solid var(--border); }
  .dlg-head h2 { margin: 0; font-size: var(--fs-h2); flex: 1; min-width: 0; }
  .dlg-head button { border: 1px solid var(--border); background: var(--surface-2); border-radius: 10px; padding: 6px 12px; cursor: pointer; }
  .dlg-body { padding: 16px; }
  .dlg .ph { --maxh: calc(94vh - 140px); }
  .dlg-cap { margin: 10px 2px 0; color: var(--muted); font-size: var(--fs-small); word-break: keep-all; overflow-wrap: anywhere; }
  .dlg-cap-main { color: var(--text); font-weight: 650; }

  /* 1259px 이하: 상세 패널은 지도 아래 */
  @media (max-width: 1259px) {
    .home-grid { grid-template-columns: minmax(0, 1fr); }
  }
  /* 1260px 이상: 종합 현황을 화면 높이에 맞춘다. 지도는 남은 높이, 오른쪽 상세 패널(380px)은 지도+범례 높이(패널 안에서만 스크롤) */
  @media (min-width: 1260px) and (min-height: 700px) {
    .main:has(> #page-home:not([hidden])) { padding-bottom: 0; }
    #page-home:not([hidden]) { display: flex; flex-direction: column; height: 100vh; height: 100dvh; padding-bottom: 20px; }
    #page-home .home-grid { flex: 1 1 0; min-height: 0; grid-template-rows: minmax(0, 1fr) auto; row-gap: 12px; }
    #page-home .mapcard { display: contents; }  /* 지도·범례를 격자에 바로 놓는다 (지도 색 변수는 그대로 물려받음) */
    #page-home .mapbox { grid-column: 1; grid-row: 1; height: auto; min-height: 0; }
    #page-home .legend { grid-column: 1; grid-row: 2; }
    #page-home .dpanel { grid-column: 2; grid-row: 1 / 3; min-height: 0; }
  }
  /* ---------- 모바일: 사이드바 → 위쪽 탭 ---------- */
  @media (max-width: 760px) {
    :root { --fs-title: 20px; --fs-h2: 15px; }
    .app { grid-template-columns: minmax(0, 1fr); }
    .side { position: static; height: auto; gap: 12px; padding: 14px 16px 16px; border-right: 0; border-bottom: 1px solid var(--border); }
    .brand { display: flex; align-items: baseline; gap: 8px; padding: 0 2px; font-size: 18px; }
    .brand small { display: inline; }
    .nav { grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 4px; }
    .nav a { flex-direction: column; justify-content: center; gap: 3px; padding: 8px 2px; font-size: 12px; text-align: center; }
    .nav a[aria-current="page"] { box-shadow: inset 0 -3px 0 var(--accent); }
    .nav .full { display: none; }
    .nav .short { display: inline; }
    .session { margin: 0; padding: 12px 14px; font-size: var(--fs-xs); border-radius: 12px; }
    .session h2 { display: none; }
    .session dl { gap: 2px 10px; }
    .theme-btn { margin-top: 10px; padding: 6px 10px; font-size: 12px; }
    .main { padding: 0 16px 36px; }
    .page-head { position: static; margin: 0 -16px; padding: 12px 16px; }
    .page-head h1 { font-size: 19px; }
    .page-head .sub { flex-basis: 100%; text-align: left; white-space: normal; overflow-wrap: anywhere; }
    .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin: 14px 0; }  /* 모바일도 2×2 유지 */
    .kpi { grid-template-columns: 30px minmax(0, 1fr); column-gap: 10px; padding: 14px 16px; }
    .kpi-ico { width: 30px; height: 30px; }
    .kpi-ico svg { width: 16px; height: 16px; }
    .kpi .label { grid-column: 2; }
    .kpi .label small { display: none; }  /* 좁은 칸: 보조 라벨은 title(마우스 올림)로 */
    .kpi .value { font-size: 26px; }
    .kpi .sub { grid-column: 1 / 3; padding: 6px 0 0; }
    .mapbox { height: 380px; }
    :is(#map, #h-map) .leaflet-control-attribution { font-size: 10px; }
    .legend { padding: 10px 12px; gap: 6px 12px; }
    .v-detail { padding: 16px; }
    .v-big .num { font-size: 44px; }
    .v-cards { gap: 6px; }
    .v-card { padding: 9px 10px; }
    .v-card .v { font-size: 18px; }
    .fg { padding: 10px; }
    /* 점검 이력: 필터는 2열, 지점 표는 카드형 목록 */
    .h-tools { align-items: stretch; }
    .h-filters { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); width: 100%; }
    .h-f select { min-width: 0; width: 100%; }
    .h-actions { width: 100%; }
    .h-actions .btn { flex: 1 1 auto; justify-content: center; }
    .h-note { text-align: left; }
    .h-card { padding: 16px; }
    .h-bar { grid-template-columns: 64px minmax(0, 1fr); gap: 4px 8px; }
    .h-table-wrap { max-height: none; overflow: visible; margin: 0; padding: 0; }
    .h-points thead { display: none; }
    .h-points, .h-points tbody { display: block; }
    .h-points tbody { display: grid; gap: 8px; }
    .h-points tr { display: grid; grid-template-columns: auto auto minmax(0, 1fr); align-items: center; gap: 4px 8px; padding: 12px;
                   border: 1px solid var(--border); border-radius: 12px; background: var(--surface); }
    .h-points td { display: block; min-width: 0; padding: 0; border: 0; }
    .h-points td:nth-child(3) { justify-self: end; font-weight: 700; }
    .h-points td:nth-child(4) { grid-column: 1 / -1; min-width: 0; }
    .h-points td:nth-child(5), .h-points td:nth-child(6), .h-points td:nth-child(7) { color: var(--muted); font-size: var(--fs-xs); }
    .h-points td:nth-child(5)::before { content: "측정 "; }
    .h-points td:nth-child(6) { grid-column: 1 / 3; grid-row: 4; }
    .h-points td:nth-child(7) { grid-column: 2 / -1; grid-row: 3; justify-self: end; }
    .h-points td:nth-child(8) { grid-column: 3; grid-row: 4; justify-self: end; font-size: var(--fs-small); }
    .h-points .h-empty { grid-column: 1 / -1; }
  }
</style>
</head>
<body>
<div class="app">
  <aside class="side" aria-label="페이지와 측정 세션">
    <div class="brand">StepMap <small>보도 점검 대시보드</small></div>
    <nav class="nav" id="nav" aria-label="페이지">
      <a href="#home" data-page="home">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 11.5 12 5l8 6.5V19a1 1 0 0 1-1 1h-4.5v-5h-5v5H5a1 1 0 0 1-1-1z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>
        <span class="full">종합 현황</span><span class="short">종합</span></a>
      <a href="#visual" data-page="visual">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>
        <span class="full">외관 검사</span><span class="short">외관</span></a>
      <a href="#physical" data-page="physical">
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="1.8" stroke-dasharray="3 2.4"/><circle cx="12" cy="12" r="3.2" fill="currentColor"/></svg>
        <span class="full">물리적 안정성 검사</span><span class="short">안정성</span></a>
      <a href="#history" data-page="history">
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M12 7.5V12l3 2" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        <span class="full">점검 이력</span><span class="short">이력</span></a>
    </nav>
    <section class="session" aria-labelledby="session-title">
      <h2 id="session-title">측정 세션</h2>
      <dl>
        <dt>세션</dt><dd id="s-session"></dd>
        <dt>측정 시간</dt><dd id="s-time"></dd>
        <dt>구간</dt><dd id="s-area"></dd>
        <dt>로봇</dt><dd id="s-robot"></dd>
      </dl>
      <button type="button" class="theme-btn" id="theme-toggle"></button>
    </section>
  </aside>

  <main class="main" id="main">
    <section class="page" id="page-home" data-page="home" aria-labelledby="home-title">
      <header class="page-head"><h1 id="home-title">종합 현황</h1><p class="sub" id="home-sub"></p></header>
      <div class="kpis" aria-label="핵심 지표">
        <div class="kpi"><span class="kpi-ico" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M6 18.5c5 0 3.5-6.5 6-6.5s1-6.5 6-6.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="6" cy="18.5" r="2" fill="currentColor"/><circle cx="18" cy="5.5" r="2" fill="currentColor"/></svg></span><div class="label">점검 거리</div><div class="value" id="k-dist"></div><div class="sub" id="k-dist-sub"></div></div>
        <div class="kpi"><span class="kpi-ico warn" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/><circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="1.9"/></svg></span><div class="label">외관 이상 <small>카메라</small></div><div class="value" id="k-visual"></div><div class="sub" id="k-visual-sub"></div></div>
        <div class="kpi"><span class="kpi-ico warn" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="1.9" stroke-dasharray="3 2.4"/><circle cx="12" cy="12" r="3.2" fill="currentColor"/></svg></span><div class="label">흔들림 의심 <small>발 접촉</small></div><div class="value" id="k-loose"></div><div class="sub" id="k-loose-sub"></div></div>
        <div class="kpi"><span class="kpi-ico ok" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></span><div class="label">정상 지점</div><div class="value" id="k-ok"></div><div class="sub" id="k-ok-sub"></div></div>
      </div>
      <div class="home-grid">
        <div class="mapcard" id="mapcard" data-map="light">
          <div class="mapbox">
            <div id="map" role="application" aria-label="측정 지점 지도"></div>
            <div id="plane" role="group" aria-label="측정 지점 지도 (odom 좌표)" hidden></div>
            <div class="map-tools">
              <div class="map-seg" role="group" aria-label="지도 배경">
                <button type="button" data-map="light" aria-pressed="true">밝은 지도</button>
                <button type="button" data-map="dark" aria-pressed="false">어두운 지도</button>
              </div>
              <button type="button" class="retry" id="retry" hidden>지도 다시 불러오기</button>
            </div>
            <div class="map-empty" id="map-empty" role="status" hidden>표시할 지점이 없어요</div>
          </div>
          <div class="legend" id="legend" aria-label="범례">
            <div class="lv-filter" id="lv-filter" role="group" aria-label="판정별 지점 보기">__LEVEL_FILTER__</div>
          </div>
        </div>
        <aside class="dpanel" id="dpanel" aria-label="지점 상세"></aside>
      </div>
    </section>

    <section class="page" id="page-visual" data-page="visual" aria-labelledby="visual-title" hidden>
      <header class="page-head"><nav class="crumbs" aria-label="현재 위치"><a href="#home">종합 현황 지도</a> › <span id="v-crumb"></span></nav>
        <h1 id="visual-title">외관 검사</h1><p class="sub">카메라로 본 단차·경사·균열 (발로만 잡은 단차 포함)</p></header>
      <div class="v-tools">
        <div class="tabs" id="v-tabs" role="tablist" aria-label="종류"></div>
        <label class="toggle"><input type="checkbox" id="v-ok"> 정상 포함</label>
      </div>
      <div class="v-grid">
        <div class="v-list" id="v-list" role="listbox" aria-label="외관 검사 지점"></div>
        <article class="v-detail" id="v-detail" aria-live="polite"></article>
      </div>
    </section>
    <section class="page" id="page-physical" data-page="physical" aria-labelledby="physical-title" hidden>
      <header class="page-head"><nav class="crumbs" aria-label="현재 위치"><a href="#home">종합 현황 지도</a> › <span id="p-crumb"></span></nav>
        <h1 id="physical-title">물리적 안정성 검사</h1><p class="sub">발 접촉으로 찾은 흔들리는 블럭 (체중이 실린 뒤 추가 침하)</p></header>
      <div class="kpis" aria-label="물리적 안정성 지표">
        <div class="kpi"><span class="kpi-ico" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="1.9" stroke-dasharray="3 2.4"/><circle cx="12" cy="12" r="3.2" fill="currentColor"/></svg></span><div class="label">발로 확인한 지점</div><div class="value" id="p-k-all"></div><div class="sub">흔들림 측정</div></div>
        <div class="kpi"><span class="kpi-ico danger" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 4 21 19.5H3z" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/><path d="M12 10v4.2" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="16.8" r="1.1" fill="currentColor"/></svg></span><div class="label">흔들림 의심</div><div class="value" id="p-k-flag"></div><div class="sub" id="p-k-flag-sub"></div></div>
        <div class="kpi"><span class="kpi-ico warn" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/><circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="1.9"/><path d="M4 20 20 4" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/></svg></span><div class="label">그중 외관 정상 <small>메모에 "외관 정상"</small></div><div class="value" id="p-k-hidden"></div><div class="sub">카메라로 찾기 어려운 지점</div></div>
        <div class="kpi"><span class="kpi-ico ok" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></span><div class="label">정상</div><div class="value" id="p-k-ok"></div><div class="sub" id="p-k-ok-sub"></div></div>
      </div>
      <div class="v-grid">
        <div class="v-list" id="p-list" role="listbox" aria-label="흔들림 지점"></div>
        <article class="v-detail" id="p-detail" aria-live="polite"></article>
      </div>
    </section>
    <section class="page" id="page-history" data-page="history" aria-labelledby="history-title" hidden>
      <header class="page-head"><h1 id="history-title">점검 이력</h1><p class="sub" id="history-sub"></p></header>
      <div class="h-dates" id="h-dates">
        <div class="h-chips" id="h-chips" role="group" aria-label="점검 날짜">__DATE_CHIPS__</div>
        <button type="button" class="h-cal-btn" id="h-cal-btn" aria-label="달력에서 점검 날짜 고르기" aria-expanded="false" aria-controls="h-cal"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="5" width="17" height="15.5" rx="2" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M3.5 10h17M8 3v4M16 3v4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></button>
        <div class="h-cal" id="h-cal" role="dialog" aria-label="점검 날짜 달력" hidden></div>
      </div>
      <div class="kpis" aria-label="그날 점검 요약">
        <div class="kpi"><span class="kpi-ico" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M6 18.5c5 0 3.5-6.5 6-6.5s1-6.5 6-6.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="6" cy="18.5" r="2" fill="currentColor"/><circle cx="18" cy="5.5" r="2" fill="currentColor"/></svg></span><div class="label">점검 거리</div><div class="value" id="h-k-dist"></div><div class="sub" id="h-k-dist-sub"></div></div>
        <div class="kpi"><span class="kpi-ico danger" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 4 21 19.5H3z" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/><path d="M12 10v4.2" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="16.8" r="1.1" fill="currentColor"/></svg></span><div class="label">위험</div><div class="value" id="h-k-danger"></div><div class="sub" id="h-k-danger-sub"></div></div>
        <div class="kpi"><span class="kpi-ico warn" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="1.9"/><path d="M12 7.5v5.5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="16.2" r="1.1" fill="currentColor"/></svg></span><div class="label">주의</div><div class="value" id="h-k-warn"></div><div class="sub" id="h-k-warn-sub"></div></div>
        <div class="kpi"><span class="kpi-ico ok" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></span><div class="label">정상</div><div class="value" id="h-k-ok"></div><div class="sub" id="h-k-ok-sub"></div></div>
      </div>
      <div class="h-grid">
        <section class="h-card h-mapcard mapcard" data-map="light" aria-labelledby="h-map-title">
          <h2 id="h-map-title">이동경로와 측정 지점 <small id="h-map-sub"></small></h2>
          <div class="h-mapbox">
            <div id="h-map" role="application" aria-label="그날 이동경로와 측정 지점 지도"></div>
            <div id="h-plane" role="group" aria-label="그날 이동경로와 측정 지점 (odom 좌표)" hidden></div>
            <button type="button" class="h-route-btn" id="h-route-btn" aria-pressed="true"><span class="sw" aria-hidden="true"></span>이동경로</button>
          </div>
        </section>
        <section class="h-card" aria-labelledby="h-bars-title"><h2 id="h-bars-title">종류별 판정</h2><div class="h-bars" id="h-bars"></div>
          <p class="h-bars-total" id="h-bars-total"></p></section>
      </div>
      <section class="h-card" aria-labelledby="h-pts-title"><h2 id="h-pts-title">지점 목록 <small id="h-pts-count"></small></h2>
        <div class="h-tools">
          <div class="h-filters" role="group" aria-label="필터">
            <label class="h-f"><span>종류</span><select id="h-kind"></select></label>
            <label class="h-f"><span>판정</span><select id="h-level"></select></label>
            <label class="h-f"><span>측정 방식</span><select id="h-source"></select></label>
            <button type="button" class="h-reset" id="h-reset" hidden>필터 지우기</button>
          </div>
          <div class="h-actions">
            <button type="button" class="btn primary" id="h-csv"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v11m0 0l-4.5-4.5M12 15l4.5-4.5M5 19h14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>CSV 다운로드</button>
            <a class="btn" id="h-report" href="#" target="_blank" rel="noopener" hidden><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 3.5h7l4 4V20a.5.5 0 0 1-.5.5h-10A.5.5 0 0 1 7 20z M14 3.5V8h4 M9.5 12h5M9.5 15.5h5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/></svg>신고서 열기</a>
          </div>
        </div>
        <p class="h-note" id="h-report-note" hidden>신고서는 A4 인쇄용입니다. 인쇄 창에서 "PDF로 저장"을 고르면 PDF로 남길 수 있습니다.</p>
        <div class="h-table-wrap"><table class="h-table h-points clickable" id="h-points">
          <thead><tr id="h-points-head"></tr></thead><tbody></tbody></table></div>
        <button type="button" class="h-more" id="h-ok-toggle" aria-expanded="false" aria-controls="h-points" hidden></button></section>
    </section>
  </main>
</div>
<div class="tip" id="tip" role="tooltip" hidden></div>
<div class="picker" id="picker" role="dialog" aria-label="묶인 지점 고르기" hidden></div>
<dialog class="dlg" id="photo-dlg" aria-labelledby="photo-dlg-title">
  <div class="dlg-head"><h2 id="photo-dlg-title"></h2><button type="button" id="photo-dlg-close">닫기</button></div>
  <div class="dlg-body" id="photo-dlg-body"></div>
</dialog>

<script id="stepmap-data" type="application/json">__DATA__</script>
<script src="__LEAFLET_JS__" integrity="__LEAFLET_JS_SRI__" crossorigin=""></script>
<script>
(function () {
  const DATA = JSON.parse(document.getElementById("stepmap-data").textContent);
  const root = document.documentElement;
  const css = (name) => getComputedStyle(root).getPropertyValue(name).trim();
  // 지도 배경(밝은/어두운)에 따라 달라지는 색: 경로·격자·글자
  const mapCss = (name) => getComputedStyle($("mapcard")).getPropertyValue(name).trim();
  const $ = (id) => document.getElementById(id);
  const SVGNS = "http://www.w3.org/2000/svg";
  // 데이터 문자열은 항상 textContent / setAttribute 로만 넣는다
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };

  const LEVEL = {
    danger: { label: "위험", glyph: "‼", rank: 3, z: 300 },
    warn:   { label: "주의", glyph: "!",  rank: 2, z: 200 },
    ok:     { label: "정상", glyph: "✓",  rank: 1, z: 100 },
  };
  const LEVELS = ["danger", "warn", "ok"];
  const KINDS = ["step", "slope", "crack", "loose"];
  // 종류별 모양: 단차 ■ / 경사 ▲ / 균열 ✕ / 흔들림 점선 고리 + 점  (색만으로 구분하지 않음). r = 2px 바탕색 테두리
  const KIND = {
    step:  { label: "단차",  shape: (c, r) => `<rect x="5" y="5" width="14" height="14" rx="1.5" style="fill:${c};stroke:${r};stroke-width:4;paint-order:stroke"/>` },
    slope: { label: "경사",  shape: (c, r) => `<polygon points="12,3.5 21,19.5 3,19.5" style="fill:${c};stroke:${r};stroke-width:4;stroke-linejoin:round;paint-order:stroke"/>` },
    crack: { label: "균열",  shape: (c, r) => `<path d="M6 6L18 18M18 6L6 18" style="fill:none;stroke:${r};stroke-width:8;stroke-linecap:round"/><path d="M6 6L18 18M18 6L6 18" style="fill:none;stroke:${c};stroke-width:4;stroke-linecap:round"/>` },
    loose: { label: "흔들림", shape: (c, r) =>
      `<circle cx="12" cy="12" r="9.6" style="fill:none;stroke:${r};stroke-width:4.6"/>` +
      `<circle cx="12" cy="12" r="9.6" style="fill:none;stroke:${c};stroke-width:2.2;stroke-dasharray:3.4 2.4"/>` +
      `<circle cx="12" cy="12" r="4.6" style="fill:${c};stroke:${r};stroke-width:3;paint-order:stroke"/>` },
  };
  const LEG = { FR: "앞 오른발", FL: "앞 왼발", RR: "뒤 오른발", RL: "뒤 왼발" };
  const UNIT = { cm: "cm", deg: "°", mm: "mm", score: "" };
  const CLUSTER_PX = 16;  // 마커가 실제로 겹치는 거리(화면 16px 이내)일 때만 묶는다
  const PIN_GAP = 28;     // 선택한 지점 둘레에서 다른 표시를 비켜 그리는 거리

  const fmtNum = (v, unit) => unit === "score" ? Number(v).toFixed(2) : Number(v).toFixed(1);
  const fmtValue = (e) => `${fmtNum(e.value, e.unit)}${UNIT[e.unit]}`;
  const fmtFoot = (e) => `${fmtNum(e.value_foot, e.unit)}${UNIT[e.unit]}`;
  const KST = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
                                                   hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
  const tparts = (t) => Object.fromEntries(KST.formatToParts(new Date(t * 1000)).map((p) => [p.type, p.value]));
  const fmtDateTime = (t) => { const p = tparts(t); return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}`; };
  const fmtHM = (t) => { const p = tparts(t); return `${p.hour}:${p.minute}`; };

  // 판정 기준 문구: Python events.criterion_text가 만든 것 (신고서와 같은 함수)
  const criterion = (e) => e.criterion;

  // ---------------------------------------------------------------- 페이지
  const PAGES = {
    home:     { title: "종합 현황" },
    visual:   { title: "외관 검사" },
    physical: { title: "물리적 안정성 검사" },
    history:  { title: "점검 이력" },
  };
  // 흔들림(발 접촉)은 물리적 안정성, 나머지(단차·경사·균열)는 외관 검사
  const pageFor = (e) => (e.kind === "loose" ? "physical" : "visual");
  const detailHref = (e) => `#${pageFor(e)}/${e.id}`;
  // 종합 현황 지도에서 마커를 누르면 페이지를 옮기지 않고 옆 패널에 상세를 연다 (#home/<id>: 새로고침해도 유지)
  const pick = (e) => {
    if (state.sel && state.sel.id === e.id) return;  // 같은 지점: 주소가 그대로라 hashchange가 오지 않는다
    state.pickedOnMap = true;
    location.replace(`#home/${e.id}`);
  };

  // ---------------------------------------------------------------- 작은 표시 요소
  function svgIcon(kind, level) {
    const s = document.createElementNS(SVGNS, "svg");
    s.setAttribute("viewBox", "0 0 24 24");
    s.setAttribute("class", "ico");
    s.setAttribute("aria-hidden", "true");
    s.innerHTML = KIND[kind].shape(level ? `var(--${level})` : "currentColor", "var(--surface)");
    return s;
  }
  function lvBadge(level) {
    const b = el("span", `lv lv-${level}`);
    b.append(el("span", "sw", LEVEL[level].glyph), el("span", null, LEVEL[level].label));
    return b;
  }
  // 지도 마커: 판정색·테두리는 지도 배경에 맞춘 값 (밝은 지도: 진한 판정색 + 진한 네이비 테두리 2px)
  const markerInner = (e, sel) =>
    (sel ? `<circle cx="12" cy="12" r="14.5" style="fill:var(--map-bg);stroke:#0B1220;stroke-width:5"/>` +
           `<circle cx="12" cy="12" r="14.5" style="fill:none;stroke:#FFFFFF;stroke-width:3"/>` : "") +
    KIND[e.kind].shape(`var(--m-${e.level})`, "var(--m-ring)");
  // 묶음 배지: 가장 심한 판정의 색 + 그 판정 기호(작게) + 개수
  function pill(members, sel) {
    const worst = members[0].level;
    const n = members.length;
    const w = n < 10 ? 26 : 33;
    const ring = sel ? "var(--m-focus)" : "var(--m-ring)";
    // 글자: 어두운 지도는 짙은 네이비(판정색 위 5.8:1 이상), 밝은 지도는 흰색(진한 판정색 위 4.9:1 이상)
    return { w, svg:
      `<rect x="2" y="2" width="${w - 4}" height="20" rx="10" style="fill:var(--m-${worst});stroke:${ring};stroke-width:4;paint-order:stroke"/>` +
      `<text x="${w / 2}" y="16" text-anchor="middle" style="fill:var(--m-ink);font:700 11.5px system-ui,sans-serif;letter-spacing:-0.3px">` +
      `<tspan style="font-size:8px">${LEVEL[worst].glyph}</tspan><tspan dx="0.5">${n}</tspan></text>` };
  }
  const countBy = (list) => LEVELS.map((l) => list.filter((e) => e.level === l).length);
  // 사진 아이콘 (고정 마크업)
  const CAMERA = '<path d="M4 7.5h3l1.8-2.3h6.4L17 7.5h3a1 1 0 0 1 1 1V18a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8.5a1 1 0 0 1 1-1z" ' +
                 'style="fill:none;stroke:currentColor;stroke-width:1.8;stroke-linejoin:round"/>' +
                 '<circle cx="12" cy="13" r="3.4" style="fill:none;stroke:currentColor;stroke-width:1.8"/>';
  function cameraIcon() {
    const s = document.createElementNS(SVGNS, "svg");
    s.setAttribute("viewBox", "0 0 24 24");
    s.setAttribute("class", "cam");
    s.setAttribute("aria-hidden", "true");
    s.innerHTML = CAMERA;
    return s;
  }
  const photoNote = (members) => {
    const n = members.filter((e) => e.photo).length;
    return !n ? "" : members.length === 1 ? "사진 있음" : `사진 ${n}장`;
  };

  // ---------------------------------------------------------------- 툴팁
  // lines: [제목, 설명...], hint: 클릭 안내 (강조), photo: 사진 표시
  function tipContent(members) {
    if (members.length === 1) {
      const e = members[0];
      return {
        lines: [`${KIND[e.kind].label} ${fmtValue(e)} · ${LEVEL[e.level].label}`, `기준 ${criterion(e)}`,
                e.source === "camera+foot" ? `발 ${fmtFoot(e)}` : "", e.note || "", e.id].filter(Boolean),
        hint: "클릭 → 상세 보기",
      };
    }
    const c = countBy(members);
    return {
      lines: [`${members.length}개 지점`, LEVELS.map((l, i) => `${LEVEL[l].label} ${c[i]}`).filter((_, i) => c[i]).join(" · ")],
      hint: state.mode !== "tiles" ? "클릭 → 지점 고르기"
          : state.map && state.map.getZoom() >= state.map.getMaxZoom() ? "클릭 → 펼치기" : "클릭 → 확대",
    };
  }
  const tip = $("tip");
  function showTip(content, rect, photo) {
    tip.replaceChildren(el("b", null, content.lines[0]), ...content.lines.slice(1).map((t) => el("div", null, t)));
    if (photo) { const p = el("div", "tip-photo"); p.append(cameraIcon(), el("span", null, photo)); tip.append(p); }
    if (content.hint) tip.append(el("div", "tip-go", content.hint));
    tip.hidden = false;
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    let x = rect.left + rect.width / 2 - tw / 2, y = rect.top - th - 8;
    if (y < 4) y = rect.bottom + 8;
    x = Math.max(4, Math.min(x, innerWidth - tw - 4));
    tip.style.left = `${x}px`;
    tip.style.top = `${y}px`;
  }
  const hideTip = () => { tip.hidden = true; };
  addEventListener("scroll", hideTip, { passive: true });

  // 마커 공통: 호버/포커스 툴팁 + 접근성 이름
  function wire(node, content, activate, photo = "") {
    node.setAttribute("aria-label", [...content.lines, photo, content.hint].filter(Boolean).join(", "));
    node.addEventListener("mouseenter", () => showTip(content, node.getBoundingClientRect(), photo));
    node.addEventListener("mouseleave", hideTip);
    node.addEventListener("focus", () => showTip(content, node.getBoundingClientRect(), photo));
    node.addEventListener("blur", hideTip);
    if (activate) {
      node.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); activate(); }
      });
    }
  }

  // ---------------------------------------------------------------- 상태
  const byId = Object.fromEntries(DATA.events.map((e) => [e.id, e]));
  const state = { mode: null, map: null, gen: 0, sel: null, page: null, tiles: { loaded: 0, failed: 0 }, themeHooks: [] };
  window.stepmap = state;
  const isSel = (e) => !!state.sel && state.sel.id === e.id;
  // 종합 현황 지도의 판정 필터: 처음 상태는 HTML의 aria-pressed (위험만 켬). 이 페이지 안에서만 기억한다
  const levelBtns = [...document.querySelectorAll("#lv-filter .lv-btn")];
  const shown = Object.fromEntries(levelBtns.map((b) => [b.dataset.level, b.getAttribute("aria-pressed") === "true"]));
  const shownEvents = () => DATA.events.filter((e) => shown[e.level]);
  const narrow = matchMedia("(max-width: 900px)");
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");

  // 묶음 고르기 (평면 지도는 확대가 없으므로 묶인 지점을 목록으로 고른다)
  const picker = $("picker");
  function showPicker(members, rect) {
    hideTip();
    picker.replaceChildren();
    const list = [...members].sort((a, b) => LEVEL[b.level].rank - LEVEL[a.level].rank || a.t - b.t);
    for (const e of list) {
      const b = el("button");
      b.type = "button";
      b.append(svgIcon(e.kind, e.level), el("span", null, `${KIND[e.kind].label} ${fmtValue(e)}`), lvBadge(e.level));
      b.addEventListener("click", () => { hidePicker(); pick(e); });
      picker.append(b);
    }
    picker.hidden = false;
    const pw = picker.offsetWidth, ph = picker.offsetHeight;
    picker.style.left = `${Math.max(4, Math.min(rect.left + rect.width / 2 - pw / 2, innerWidth - pw - 4))}px`;
    picker.style.top = `${rect.bottom + 8 + ph < innerHeight ? rect.bottom + 8 : Math.max(4, rect.top - ph - 8)}px`;
    picker.querySelector("button")?.focus();
  }
  const hidePicker = () => { picker.hidden = true; };
  addEventListener("scroll", hidePicker, { passive: true });
  document.addEventListener("click", (ev) => { if (!picker.hidden && !picker.contains(ev.target) && !ev.target.closest("#plane .ev")) hidePicker(); });
  // Esc: 묶음 고르기가 열려 있으면 그것만 닫고, 아니면 종합 현황의 선택을 푼다 (사진 크게 보기 창은 스스로 닫힌다)
  addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    if (!picker.hidden) { hidePicker(); return; }
    if (state.page === "home" && state.sel && !document.querySelector("dialog[open]")) closePanel();
  });

  // 화면 좌표가 가까운 지점은 묶는다 (가장 심한 판정이 대표).
  // 선택한 지점은 묶지 않고 제자리에 그리며, 그 둘레 PIN_GAP 안의 표시는 바깥으로 비켜
  // (dx, dy) 그리고 원래 위치까지 짧은 연결선을 긋는다.
  const groupSelected = (g) => !!state.sel && !!state.sel.ids && g.members.some((e) => state.sel.ids.includes(e.id));
  function clusterize(items) {
    const sorted = [...items].sort((a, b) => LEVEL[b.e.level].rank - LEVEL[a.e.level].rank || a.e.t - b.e.t);
    const pin = sorted.find((it) => isSel(it.e));
    const groups = [];
    for (const it of sorted) {
      if (it === pin) continue;
      const g = groups.find((g) => Math.hypot(g.x - it.x, g.y - it.y) < CLUSTER_PX);
      if (g) g.members.push(it.e); else groups.push({ x: it.x, y: it.y, dx: 0, dy: 0, members: [it.e] });
    }
    if (pin) {
      for (const g of groups) {
        const vx = g.x - pin.x, vy = g.y - pin.y, len = Math.hypot(vx, vy);
        if (len >= PIN_GAP) continue;
        const ux = len < 1 ? 0 : vx / len, uy = len < 1 ? -1 : vy / len;
        g.dx = pin.x + ux * PIN_GAP - g.x;
        g.dy = pin.y + uy * PIN_GAP - g.y;
      }
      groups.push({ x: pin.x, y: pin.y, dx: 0, dy: 0, members: [pin.e], pinned: true });
    }
    // 덜 심한 것부터 그려서 위험·선택이 위로
    const rank = (g) => (g.pinned || groupSelected(g) ? 10 : 0) + LEVEL[g.members[0].level].rank;
    state.groups = groups;
    return groups.sort((a, b) => rank(a) - rank(b));
  }
  // 비켜 그린 표시 → 원래 위치 연결선 (cx, cy: 표시 중심, 표시 좌표계 기준)
  const leader = (g, cx, cy) => (g.dx || g.dy)
    ? `<line x1="${cx}" y1="${cy}" x2="${cx - g.dx}" y2="${cy - g.dy}" style="stroke:var(--map-leader);stroke-width:1.5;opacity:0.7"/>` +
      `<circle cx="${cx - g.dx}" cy="${cy - g.dy}" r="2.5" style="fill:var(--map-leader);stroke:var(--map-bg);stroke-width:1.5"/>`
    : "";

  // ---------------------------------------------------------------- 배경 지도 (Leaflet + OpenTopoMap)
  let markerLayer = null;
  function startTiles() {
    const gen = ++state.gen;
    const map = L.map("map", { zoomControl: true });
    state.map = map;
    state.mode = "tiles";
    map.attributionControl.setPosition("bottomright");

    // 타일 색은 CSS(--tile-filter)가 지도 배경(밝은: 옅은 회청색 / 어두운: 반전 네이비)에 맞춘다
    const tiles = L.tileLayer("__TILE_URL__", {
      subdomains: "abc",
      maxNativeZoom: __TILE_MAX_NATIVE_ZOOM__,
      maxZoom: 19,
      attribution: '__TILE_ATTRIBUTION__',
    });
    tiles.on("tileload", () => { state.tiles.loaded++; });
    tiles.on("tileerror", () => {
      state.tiles.failed++;
      // 한 장도 받지 못한 채 실패가 이어지면 odom 평면 지도로 전환
      if (state.tiles.loaded === 0 && state.tiles.failed >= 4) fallback("tileerror");
    });
    tiles.addTo(map);

    // 이동 경로는 그리지 않는다. 지도 범위는 전체 측정 지점 기준으로 처음 한 번만 맞춘다
    // (판정 필터를 바꿔도 움직이지 않는다). 지점이 없을 때만 경로 범위를 쓴다
    const bounds = L.latLngBounds(DATA.events.length ? DATA.events.map((e) => [e.lat, e.lon]) : DATA.trajectory);
    // 처음 열면 지점 전체 + 주변 동네가 보이게 여백을 둔다
    map.fitBounds(bounds.pad(0.35));
    // 데스크톱: 한 단계 더 확대해도 지점 전체가 들어가면 확대해 개별 마커가 보이게 한다
    if (!narrow.matches) {
      const fit = map.getBoundsZoom(bounds, false, L.point(40, 40));
      if (fit > map.getZoom()) map.setZoom(map.getZoom() + 1, { animate: false });
    }
    map.on("zoomstart", () => { state.spider = null; });
    map.on("click", () => { if (state.spider) { state.spider = null; renderMap(); } });  // 빈 곳을 누르면 접는다
    map.on("zoomend", renderMap);
    renderMap();

    // <img> 타일은 오류 상태(403 "Access blocked")나 대체 이미지("API KEY REQUIRED" 워터마크,
    // 200 응답)를 그대로 그려 tileerror가 나지 않는다. 화면 중심과 그 옆 타일을 직접 받아
    // 상태코드를 보고, 두 장의 내용이 똑같으면 실제 지도가 아닌 대체 이미지로 판단한다.
    const z = Math.min(map.getZoom(), __TILE_MAX_NATIVE_ZOOM__), c = map.project(map.getCenter(), z).divideBy(256).floor();
    const tileUrl = (x, y) => L.Util.template("__TILE_URL__", { s: "a", z, x, y });
    const same = (a, b) => {
      if (a.byteLength !== b.byteLength) return false;
      const u = new Uint8Array(a), w = new Uint8Array(b);
      for (let i = 0; i < u.length; i++) if (u[i] !== w[i]) return false;
      return true;
    };
    Promise.all([fetch(tileUrl(c.x, c.y)), fetch(tileUrl(c.x + 1, c.y))])
      .then(async ([a, b]) => {
        if (gen !== state.gen) return;
        state.tiles.probe = a.ok ? b.status : a.status;
        if (!a.ok || !b.ok) return fallback(`http ${state.tiles.probe}`);
        if (same(await a.arrayBuffer(), await b.arrayBuffer())) fallback("placeholder");
      })
      .catch(() => { if (gen !== state.gen) return; state.tiles.probe = "network"; fallback("network"); });

    // 응답이 아예 없는 경우(네트워크 차단 등)도 전환
    setTimeout(() => { if (gen === state.gen && state.mode === "tiles" && state.tiles.loaded === 0) fallback("timeout"); }, 10000);
  }

  function leafletMarkers() {
    const map = state.map;
    if (!map) return;
    if (markerLayer) markerLayer.remove();
    markerLayer = L.layerGroup().addTo(map);
    const items = shownEvents().map((e) => {
      const p = map.latLngToLayerPoint([e.lat, e.lon]);
      return { e, x: p.x, y: p.y };
    });
    for (const g of clusterize(items)) {
      const lead = g.members[0];
      if (g.members.length > 1 && state.spider === lead.id) { spiderfy(g); continue; }
      let m;
      if (g.members.length === 1) {
        const sel = isSel(lead);
        m = L.marker([lead.lat, lead.lon], {
          icon: L.divIcon({ className: "ev-marker", iconSize: [24, 24], iconAnchor: [12 - g.dx, 12 - g.dy],
                            html: `<svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">${leader(g, 12, 12)}${markerInner(lead, sel)}</svg>` }),
          zIndexOffset: sel ? 1000 : LEVEL[lead.level].z,
        });
        m.on("click", () => pick(lead));
      } else {
        const p = pill(g.members, groupSelected(g));
        m = L.marker([lead.lat, lead.lon], {
          icon: L.divIcon({ className: "ev-cluster", iconSize: [p.w, 24], iconAnchor: [p.w / 2 - g.dx, 12 - g.dy],
                            html: `<svg width="${p.w}" height="24" viewBox="0 0 ${p.w} 24" aria-hidden="true">${leader(g, p.w / 2, 12)}${p.svg}</svg>` }),
          zIndexOffset: LEVEL[lead.level].z + 50,
        });
        const members = g.members;
        m.on("click", () => {
          hideTip();
          if (map.getZoom() >= map.getMaxZoom()) { state.spider = lead.id; renderMap(); return; }  // 더 확대할 수 없으면 펼친다
          map.fitBounds(L.latLngBounds(members.map((e) => [e.lat, e.lon])), { padding: [60, 60], maxZoom: 19, animate: !reduceMotion.matches });
        });
      }
      m.addTo(markerLayer);
      const node = m.getElement();
      node.setAttribute("role", "button");
      wire(node, tipContent(g.members), null, photoNote(g.members));  // Enter 키는 Leaflet이 click으로 바꿔 준다
    }
  }

  // 최대 확대에서도 묶인 지점: 묶음 자리 둘레로 부채꼴처럼 펼치고, 각 마커에서 실제 위치까지 연결선을 긋는다
  function spiderfy(g) {
    const map = state.map, n = g.members.length;
    const R = 34 + Math.max(0, n - 4) * 6;
    const span = n <= 4 ? 140 : n <= 7 ? 220 : 330;  // 위쪽으로 펼치는 각도 (많으면 거의 한 바퀴)
    g.members.forEach((e, i) => {
      const a = (-90 - span / 2 + (n === 1 ? span / 2 : (span * i) / (n - 1))) * Math.PI / 180;
      const p = map.latLngToLayerPoint([e.lat, e.lon]);
      const one = { x: p.x, y: p.y, dx: g.x + R * Math.cos(a) - p.x, dy: g.y + R * Math.sin(a) - p.y, members: [e] };
      const m = L.marker([e.lat, e.lon], {
        icon: L.divIcon({ className: "ev-marker", iconSize: [24, 24], iconAnchor: [12 - one.dx, 12 - one.dy],
                          html: `<svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">${leader(one, 12, 12)}${markerInner(e, isSel(e))}</svg>` }),
        zIndexOffset: 2000 + LEVEL[e.level].z,
      });
      m.on("click", () => pick(e));
      m.addTo(markerLayer);
      const node = m.getElement();
      node.setAttribute("role", "button");
      wire(node, tipContent([e]), null, photoNote([e]));
    });
  }

  function fallback(reason) {
    if (state.mode === "plane") return;
    state.reason = reason;
    if (state.map) { state.map.remove(); state.map = null; markerLayer = null; }
    document.getElementById("map").hidden = true;
    startPlane();
  }

  // 평면 지도 상태에서 타일 다시 시도
  $("retry").addEventListener("click", () => {
    if (state.mode !== "plane") return;
    $("plane").hidden = true;
    $("retry").hidden = true;
    $("map").hidden = false;
    state.mode = null;
    state.reason = null;
    state.tiles = { loaded: 0, failed: 0 };
    startTiles();
  });

  // ---------------------------------------------------------------- odom (x, y) 평면 SVG 지도
  let planeDraw = null;
  function startPlane() {
    state.mode = "plane";
    const box = document.getElementById("plane");
    box.hidden = false;
    $("retry").hidden = false;
    if (planeDraw) { planeDraw(); return; }
    const NS = "http://www.w3.org/2000/svg";
    // 범위: 전체 측정 지점 기준 (판정 필터와 무관). 지점이 없을 때만 경로 범위
    const pts = DATA.events.length ? DATA.events.map((e) => [e.x, e.y]) : DATA.trajectory_xy;
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);

    function niceStep(raw) {
      const p = Math.pow(10, Math.floor(Math.log10(raw)));
      for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= raw) return m * p;
      return 10 * p;
    }

    function draw() {
      if (state.mode !== "plane") return;
      // 위쪽은 지도 배경 전환·다시 불러오기 버튼 자리만큼 더 비운다
      const W = box.clientWidth, H = box.clientHeight, pad = 48, padT = 72;
      if (W <= 2 * pad || H <= pad + padT) return;  // 크기가 잡히기 전(레이아웃 전환 중)에는 건너뛴다
      const s = Math.min((W - 2 * pad) / Math.max(maxX - minX, 1), (H - pad - padT) / Math.max(maxY - minY, 1));
      const ox = (W - (maxX - minX) * s) / 2, oy = padT + (H - pad - padT - (maxY - minY) * s) / 2;
      const X = (x) => ox + (x - minX) * s;            // x·y 같은 비율
      const Y = (y) => oy + (maxY - y) * s;            // y 위쪽
      const step = niceStep(60 / s);                    // 격자 간격: 화면에서 60px 이상

      let g = "";
      const x0 = minX - (ox / s), x1 = minX + (W - ox) / s;
      const y0 = maxY - (H - oy) / s, y1 = maxY + oy / s;
      for (let gx = Math.ceil(x0 / step) * step; gx <= x1; gx += step)
        g += `<line x1="${X(gx)}" y1="0" x2="${X(gx)}" y2="${H}"/>`;
      for (let gy = Math.ceil(y0 / step) * step; gy <= y1; gy += step)
        g += `<line x1="0" y1="${Y(gy)}" x2="${W}" y2="${Y(gy)}"/>`;

      const barM = niceStep(120 / s), barPx = barM * s;
      const bar = `<g transform="translate(16,${H - 24})" fill="${mapCss("--map-text")}" font-size="12">` +
                  `<rect width="${barPx}" height="4" y="-4"/><text y="-10">${barM} m</text></g>` +
                  `<text x="16" y="24" fill="${mapCss("--map-text")}" font-size="12">odom 좌표 · 격자 ${step} m</text>`;

      box.innerHTML = `<svg xmlns="${NS}" width="${W}" height="${H}">` +
        `<g stroke="${mapCss("--map-grid")}" stroke-width="1">${g}</g>` + bar + `</svg>`;

      // 마커는 DOM으로 만든다 (이름·툴팁은 textContent/setAttribute)
      const layer = document.createElementNS(NS, "g");
      const items = shownEvents().map((e) => ({ e, x: X(e.x), y: Y(e.y) }));
      for (const grp of clusterize(items)) {
        const node = document.createElementNS(NS, "g");
        node.setAttribute("class", "ev");
        node.setAttribute("tabindex", "0");
        node.setAttribute("role", "button");
        let activate;
        if (grp.members.length === 1) {
          const e = grp.members[0];
          node.setAttribute("transform", `translate(${(grp.x + grp.dx - 12).toFixed(1)},${(grp.y + grp.dy - 12).toFixed(1)})`);
          node.innerHTML = leader(grp, 12, 12) + `<rect class="hit" x="-2" y="-2" width="28" height="28" rx="6" fill="transparent"/>` + markerInner(e, isSel(e));
          activate = () => pick(e);
        } else {
          const p = pill(grp.members, groupSelected(grp));
          node.setAttribute("transform", `translate(${(grp.x + grp.dx - p.w / 2).toFixed(1)},${(grp.y + grp.dy - 12).toFixed(1)})`);
          node.innerHTML = leader(grp, p.w / 2, 12) + `<rect class="hit" x="-2" y="-2" width="${p.w + 4}" height="28" rx="8" fill="transparent"/>` + p.svg;
          const members = grp.members;
          activate = () => showPicker(members, node.getBoundingClientRect());
        }
        node.addEventListener("click", activate);
        wire(node, tipContent(grp.members), activate, photoNote(grp.members));
        layer.append(node);
      }
      box.firstElementChild.append(layer);
    }

    planeDraw = draw;
    draw();
    let pending = 0;
    addEventListener("resize", () => { cancelAnimationFrame(pending); pending = requestAnimationFrame(draw); });
    state.themeHooks.push(() => { if (state.mode === "plane") draw(); });
  }

  function renderMap() {
    hideTip();  // 마커를 다시 그리면 mouseleave가 오지 않으므로 먼저 닫는다
    if (state.mode === "tiles") leafletMarkers();
    else if (state.mode === "plane" && planeDraw) planeDraw();
  }

  // 지도는 종합 현황이 처음 보일 때 만든다 (숨겨진 상자는 크기가 0이라 지도 맞춤이 깨진다)
  function showMap() {
    if (!state.mode) {
      // Leaflet 자체를 불러오지 못했으면(오프라인 등) 바로 평면 지도
      if (window.L) startTiles(); else fallback("leaflet");
    } else if (state.mode === "tiles" && state.map) {
      state.map.invalidateSize({ animate: false });
      renderMap();
    } else if (state.mode === "plane" && planeDraw) {
      planeDraw();
    }
  }

  // ---------------------------------------------------------------- 테마 (다크 기본)
  function applyTheme(t) {
    root.dataset.theme = t;
    const btn = $("theme-toggle");
    btn.textContent = t === "dark" ? "라이트 테마로 보기" : "다크 테마로 보기";
    btn.setAttribute("aria-pressed", String(t === "light"));
    for (const f of state.themeHooks) f();
  }
  $("theme-toggle").addEventListener("click", () => {
    const next = root.dataset.theme === "light" ? "dark" : "light";
    try { localStorage.setItem("stepmap-theme", next); } catch (e) { /* 저장 못 해도 이번 화면에는 적용 */ }
    applyTheme(next);
  });
  applyTheme(root.dataset.theme === "light" ? "light" : "dark");

  // ---------------------------------------------------------------- 지도 배경 (밝은 지도 기본, 페이지 테마와 따로)
  const MAP_KEY = "stepmap-map";
  function applyMapStyle(m) {
    $("mapcard").dataset.map = m;
    for (const b of document.querySelectorAll(".map-seg button")) b.setAttribute("aria-pressed", String(b.dataset.map === m));
    for (const f of state.themeHooks) f();  // 평면 지도는 색을 직접 칠하므로 다시 칠한다 (마커는 CSS 변수라 그대로 바뀐다)
  }
  for (const b of document.querySelectorAll(".map-seg button")) {
    b.addEventListener("click", () => {
      try { localStorage.setItem(MAP_KEY, b.dataset.map); } catch (e) { /* 저장 못 해도 이번 화면에는 적용 */ }
      applyMapStyle(b.dataset.map);
    });
  }
  let savedMap = null;
  try { savedMap = localStorage.getItem(MAP_KEY); } catch (e) { /* 저장소를 못 쓰면 기본값 */ }
  applyMapStyle(savedMap === "dark" ? "dark" : "light");

  // ---------------------------------------------------------------- 측정 세션 정보
  $("s-session").textContent = DATA.session || "—";
  $("s-session").setAttribute("title", DATA.session || "");  // 말줄임으로 잘리면 마우스를 올려 전체를 본다
  $("s-time").textContent = DATA.t0 != null ? `${fmtDateTime(DATA.t0)} ~ ${fmtHM(DATA.t1)}` : "—";
  $("s-area").textContent = DATA.area || "—";
  $("s-robot").textContent = DATA.robot || "—";
  $("home-sub").textContent = [DATA.session, DATA.area, DATA.t0 != null ? fmtDateTime(DATA.t0) : ""].filter(Boolean).join(" · ");

  // ---------------------------------------------------------------- KPI 공용 계산 (종합 현황 · 점검 이력이 같은 함수를 쓴다)
  const countLevel = (list, lv) => list.filter((e) => e.level === lv).length;
  // 점검 거리: 반올림은 화면에서 한 번만 (신고서와 같은 값). meters가 없으면 —
  function putDistance(node, meters) {
    node.replaceChildren();
    if (meters == null) { node.textContent = "—"; return; }
    node.textContent = Math.round(meters).toLocaleString("ko-KR");
    node.append(el("small", null, "m"));
  }
  // 위험·주의 배지 + 개수
  function putLevelBadges(box, list, levels = ["danger", "warn"]) {
    box.replaceChildren();
    for (const lv of levels) {
      const s = el("span"); s.append(lvBadge(lv), document.createTextNode(` ${countLevel(list, lv)}`)); box.append(s);
    }
  }
  for (const l of document.querySelectorAll(".kpi .label")) l.setAttribute("title", l.textContent.replace(/\s+/g, " ").trim());

  // ---------------------------------------------------------------- 종합 현황: KPI
  {
    const visualEv = DATA.events.filter((e) => e.kind !== "loose");
    const looseEv = DATA.events.filter((e) => e.kind === "loose");
    putDistance($("k-dist"), DATA.distance_m);
    $("k-dist-sub").textContent = `측정 지점 ${DATA.events.length}개`;
    $("k-visual").textContent = countLevel(visualEv, "danger") + countLevel(visualEv, "warn");
    putLevelBadges($("k-visual-sub"), visualEv);
    $("k-loose").textContent = countLevel(looseEv, "danger") + countLevel(looseEv, "warn");
    putLevelBadges($("k-loose-sub"), looseEv);
    $("k-ok").textContent = countLevel(DATA.events, "ok");
    $("k-ok-sub").textContent = `전체 ${DATA.events.length}개 중`;
  }

  // ---------------------------------------------------------------- 종합 현황: 범례 (판정 필터 버튼 + 종류별 모양)
  function setShown(lv, on) {
    shown[lv] = on;
    if (!on && state.page === "home" && state.sel && byId[state.sel.id].level === lv) closePanel();  // 선택된 지점을 숨기면 패널도 닫는다
    for (const b of levelBtns) b.setAttribute("aria-pressed", String(shown[b.dataset.level]));
    $("map-empty").hidden = LEVELS.some((l) => shown[l]);
    state.spider = null;  // 펼친 묶음은 구성이 바뀌므로 접는다. 지도 범위는 그대로
    renderMap();
  }
  {
    const box = $("legend");
    for (const b of levelBtns) b.addEventListener("click", () => setShown(b.dataset.level, !shown[b.dataset.level]));
    $("map-empty").hidden = LEVELS.some((l) => shown[l]);
    box.append(el("span", "sep"));
    for (const k of KINDS) {
      const it = el("span", "item");
      it.append(svgIcon(k, null), el("span", null, k === "loose" ? "흔들림 (점선 고리)" : KIND[k].label));
      box.append(it);
    }
  }

  // ---------------------------------------------------------------- 현장 사진 (외관 검사·물리적 안정성 페이지에서 사용)
  // 위치 표시(동그라미·라벨)는 Python photos.overlay_svg가 만든 SVG (신고서와 같은 함수)
  function photoView(e, onMissing, thumb = false) {
    const p = e.photo;
    const overlay = thumb ? p.overlay_thumb : p.overlay;  // 썸네일: 라벨 글씨 화면 최소 11px
    const wrap = el("div", "ph");
    wrap.style.setProperty("--ar", `${p.w} / ${p.h}`);
    const img = el("img");
    img.src = p.src;
    img.alt = `${KIND[e.kind].label} ${fmtValue(e)} 현장 사진`;
    img.addEventListener("error", onMissing);  // 사진 파일이 없으면 영역을 숨긴다
    wrap.append(img);
    if (overlay) {
      const holder = el("div");
      holder.innerHTML = overlay;
      wrap.append(holder.firstElementChild);
    }
    return wrap;
  }
  function photoFigure(e) {
    const fig = el("figure", "d-photo");
    const btn = el("button", "ph-btn");
    btn.type = "button";
    btn.setAttribute("aria-label", "사진 크게 보기");
    btn.append(photoView(e, () => fig.remove(), true));
    btn.addEventListener("click", () => openPhoto(e));
    const cap = el("figcaption");
    if (e.photo.caption) cap.append(el("span", "ph-cap", e.photo.caption));  // 종류별 자동 설명 (흔들림)
    const hint = el("span", "ph-hint");
    hint.append(cameraIcon(), el("span", null, "누르면 크게 보기"));
    cap.append(hint);
    fig.append(btn, cap);
    return fig;
  }
  const dlg = $("photo-dlg");
  function openPhoto(e) {
    hideTip();
    $("photo-dlg-title").textContent = `${KIND[e.kind].label} ${fmtValue(e)} · ${LEVEL[e.level].label}`;
    const body = $("photo-dlg-body");
    body.replaceChildren(photoView(e, () => dlg.close()));
    if (e.photo.caption) body.append(el("p", "dlg-cap dlg-cap-main", e.photo.caption));
    if (e.note) body.append(el("p", "dlg-cap", e.note));
    dlg.showModal();
  }
  state.openPhoto = (id) => openPhoto(byId[id]);
  state.photoFigure = (id) => photoFigure(byId[id]);
  $("photo-dlg-close").addEventListener("click", () => dlg.close());
  dlg.addEventListener("click", (ev) => { if (ev.target === dlg) dlg.close(); });  // 바깥(배경) 누르면 닫기

  // ---------------------------------------------------------------- 외관 검사
  // 대상: 흔들림을 뺀 모든 지점. 정렬은 종합 현황 목록과 같다 (위험 먼저, 같은 판정 안에서는 ratio 큰 순)
  const V = { kind: "all", withOk: false, scrollToDetail: false };
  const V_KINDS = ["all", "step", "slope", "crack"];
  const byIssueOrder = (a, b) => LEVEL[b.level].rank - LEVEL[a.level].rank || b.ratio - a.ratio || a.t - b.t;
  const visualAll = DATA.events.filter((e) => e.kind !== "loose").sort(byIssueOrder);
  const visualShown = (kind = V.kind) => visualAll.filter((e) => (kind === "all" || e.kind === kind) && (V.withOk || e.level !== "ok"));
  // 측정 근거: 측정 방법 (종류 + 측정 센서)
  const METHOD = {
    step:  { camera: "깊이 카메라 바닥 평면 대비 높이 차", foot: "발 접지 높이 차 (다른 발 대비)",
             "camera+foot": "깊이 카메라 바닥 평면 대비 높이 차 + 발 접지 높이 차 (교차 측정)" },
    slope: { camera: "깊이 카메라 바닥 평면 기울기" },
    crack: { camera: "RGB 영상 균열 검출 점수 (0~1)" },
  };
  const methodText = (e) => {
    const m = (METHOD[e.kind] || {})[e.source] || e.source;
    return e.leg && e.source !== "camera" ? `${m} · ${LEG[e.leg] || e.leg}(${e.leg})` : m;
  };
  const kindValue = (e) => `${KIND[e.kind].label} ${fmtValue(e)}`;
  const legName = (leg) => (leg ? `${LEG[leg] || leg}(${leg})` : "");
  const fmtDateTimeS = (t) => { const p = tparts(t); return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second}`; };

  function selectVisual(id) {
    V.scrollToDetail = narrow.matches;  // 모바일: 목록 아래 상세로 내려간다
    location.replace(`#visual/${id}`);  // 같은 페이지 안 선택은 방문 기록을 쌓지 않는다
  }
  function renderVisualTabs() {
    const box = $("v-tabs");
    box.replaceChildren();
    for (const k of V_KINDS) {
      const b = el("button");
      b.type = "button";
      b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", String(V.kind === k));
      if (k !== "all") b.append(svgIcon(k, null));
      b.append(el("span", null, k === "all" ? "전체" : KIND[k].label), el("span", "n", String(visualShown(k).length)));
      b.addEventListener("click", () => { V.kind = k; refreshVisualSelection(); });
      box.append(b);
    }
  }
  // 탭·필터를 바꾼 뒤: 선택이 목록에서 빠졌으면 첫 지점을 고른다
  function refreshVisualSelection() {
    const list = visualShown();
    if (state.sel && list.some((e) => e.id === state.sel.id)) renderVisual();
    else if (list.length) selectVisual(list[0].id);
    else { state.sel = null; renderVisual(); }
  }
  $("v-ok").addEventListener("change", (ev) => { V.withOk = ev.target.checked; refreshVisualSelection(); });

  function renderVisualList() {
    const box = $("v-list");
    box.replaceChildren();
    const list = visualShown();
    if (!list.length) { box.append(el("div", "v-empty", "조건에 맞는 지점이 없습니다")); return; }
    for (const e of list) {
      const b = el("button", "v-row");
      b.type = "button";
      b.setAttribute("role", "option");
      b.setAttribute("aria-selected", String(isSel(e)));
      const th = el("span", "v-thumb");
      if (e.photo) {
        const img = el("img");
        img.src = e.photo.src;
        img.alt = "";
        img.loading = "lazy";
        img.addEventListener("error", () => th.replaceChildren(svgIcon(e.kind, e.level)));
        th.append(img);
      } else {
        th.append(svgIcon(e.kind, e.level));
      }
      const body = el("span");
      const l1 = el("span", "l1");
      l1.append(lvBadge(e.level), el("span", null, KIND[e.kind].label), el("span", "val", fmtValue(e)));
      body.append(l1);
      if (e.note) body.append(el("span", "nt", e.note));
      body.append(el("span", "tm", `${fmtDateTimeS(e.t).slice(11)} · ${e.id}`));
      for (const s of body.children) s.style.display = s.classList.contains("l1") ? "" : "block";
      b.append(th, body);
      b.setAttribute("aria-label", `${LEVEL[e.level].label} ${kindValue(e)}${e.note ? `, ${e.note}` : ""}`);
      b.addEventListener("click", () => selectVisual(e.id));
      box.append(b);
    }
  }

  function card(k, v, s, cls) {
    const c = el("div", `v-card${cls ? ` ${cls}` : ""}`);
    c.append(el("div", "k", k), el("div", "v", v));
    if (s) c.append(el("div", "s", s));
    return c;
  }
  function renderVisualDetail() {
    const box = $("v-detail");
    box.replaceChildren();
    const e = state.sel && byId[state.sel.id];
    if (!e) { box.append(el("p", "v-empty", "목록에서 지점을 고르세요")); return; }
    const head = el("div", "v-head");
    const kind = el("span", "kind");
    kind.append(svgIcon(e.kind, e.level), el("span", null, KIND[e.kind].label), lvBadge(e.level));
    const inReport = e.level !== "ok";
    head.append(kind, el("span", `rep${inReport ? " in" : ""}`, inReport ? "신고서에 포함됨" : "신고서 대상 아님 (정상)"));
    box.append(head);

    // 사진 크게 (누르면 크게 보기). 없으면 사진 자리에 안내만
    if (e.photo) box.append(photoFigure(e));
    else { const np = el("div", "no-photo"); np.append(svgIcon(e.kind, null), el("span", null, "사진 없음")); box.append(np); }

    const big = el("div", "v-big");
    big.append(el("span", "num", fmtNum(e.value, e.unit)), el("span", "unit", e.unit === "score" ? "균열 점수 (0~1)" : UNIT[e.unit]));
    const crit = el("p", "v-crit");
    crit.append(el("span", "k", "기준 "), document.createTextNode(criterion(e)));
    if (e.kind !== "crack") crit.append(el("span", "x", ` · 기준의 ${Number(e.ratio).toFixed(1)}배`));  // 균열 점수는 배수 표시 안 함
    box.append(big, crit);

    if (e.source === "camera+foot") {
      const d = Number(e.value_foot) - Number(e.value);
      const cards = el("div", "v-cards");
      cards.append(card("카메라", fmtValue(e)),
                   card(`발 · ${legName(e.leg)}`, fmtFoot(e)),
                   card("두 측정 차이", `${Math.abs(d).toFixed(1)}${UNIT[e.unit]}`, d === 0 ? "두 값 같음" : `발 측정이 ${d > 0 ? "더 큼" : "더 작음"}`, "diff"));
      box.append(cards);
    }

    const basis = el("section", "v-basis");
    basis.append(el("h2", null, "측정 근거"));
    const dl = el("dl");
    const row = (k, v) => dl.append(el("dt", null, k), el("dd", null, v));
    row("측정 방법", methodText(e));
    row("위도·경도", `${Number(e.lat).toFixed(6)}, ${Number(e.lon).toFixed(6)}`);
    row("측정 시각", fmtDateTimeS(e.t));
    row("메모", e.note || "—");
    row("신뢰도", Number(e.confidence).toFixed(2));
    row("ID", e.id);
    basis.append(dl);
    box.append(basis);

    const act = el("div", "v-actions");
    const toMap = el("button", "btn primary", "지도에서 위치 보기");
    toMap.type = "button";
    toMap.addEventListener("click", () => { location.hash = `#home/${e.id}`; });
    act.append(toMap);
    box.append(act);
  }
  function renderVisual() {
    $("v-ok").checked = V.withOk;
    renderVisualTabs();
    renderVisualList();
    renderVisualDetail();
    const e = state.sel && byId[state.sel.id];
    $("v-crumb").textContent = e ? `${kindValue(e)} (${e.id})` : "외관 검사";
    const row = document.querySelector('#v-list .v-row[aria-selected="true"]');
    if (row) row.scrollIntoView({ block: "nearest" });
    if (V.scrollToDetail && e) $("v-detail").scrollIntoView({ block: "start", behavior: reduceMotion.matches ? "auto" : "smooth" });
    V.scrollToDetail = false;
  }

  // ---------------------------------------------------------------- 물리적 안정성 검사
  // 대상: 흔들림(발 접촉) 지점. 정렬은 종합 현황 목록과 같다
  const physicalAll = DATA.events.filter((e) => e.kind === "loose").sort(byIssueOrder);
  const P = { scrollToDetail: false, redraw: null };
  {
    const n = (lv) => physicalAll.filter((e) => e.level === lv).length;
    $("p-k-all").textContent = physicalAll.length;
    $("p-k-flag").textContent = n("danger") + n("warn");
    for (const lv of ["danger", "warn"]) {
      const s = el("span"); s.append(lvBadge(lv), document.createTextNode(` ${n(lv)}`)); $("p-k-flag-sub").append(s);
    }
    $("p-k-hidden").textContent = physicalAll.filter((e) => e.level !== "ok" && (e.note || "").includes("외관 정상")).length;
    $("p-k-ok").textContent = n("ok");
    $("p-k-ok-sub").textContent = `추가 침하 ${DATA.thresholds.loose[0]}mm 미만`;
  }
  function selectPhysical(id) {
    P.scrollToDetail = narrow.matches;
    location.replace(`#physical/${id}`);
  }
  function renderPhysicalList() {
    const box = $("p-list");
    box.replaceChildren();
    for (const e of physicalAll) {
      const b = el("button", "v-row");
      b.type = "button";
      b.setAttribute("role", "option");
      b.setAttribute("aria-selected", String(isSel(e)));
      const th = el("span", "v-thumb");
      if (e.photo) {
        const img = el("img");
        img.src = e.photo.src;
        img.alt = "";
        img.loading = "lazy";
        img.addEventListener("error", () => th.replaceChildren(svgIcon(e.kind, e.level)));
        th.append(img);
      } else {
        th.append(svgIcon(e.kind, e.level));
      }
      const body = el("span");
      const l1 = el("span", "l1");
      l1.append(lvBadge(e.level), el("span", "val", fmtValue(e)), el("span", null, legName(e.leg)));
      body.append(l1);
      if (e.note) body.append(el("span", "nt", e.note));
      body.append(el("span", "tm", `${fmtDateTimeS(e.t).slice(11)} · ${e.id}`));
      for (const s of body.children) s.style.display = s.classList.contains("l1") ? "" : "block";
      b.append(th, body);
      b.setAttribute("aria-label", `${LEVEL[e.level].label} ${kindValue(e)} ${legName(e.leg)}${e.note ? `, ${e.note}` : ""}`);
      b.addEventListener("click", () => selectPhysical(e.id));
      box.append(b);
    }
  }

  // 발끝 높이 그래프 (docs/ref/foot_graph_ref.png 형식): 회색 띠 = 평소 걸음 범위, 점선 = 평소 걸음 평균,
  // 빨간 실선 = 이번 걸음, 접지 순간 세로 점선, 위험 기준선, 왼쪽 아래 값 상자, 오른쪽 위 범례
  function footGraph(e) {
    const fig = el("figure", "fg");
    const tr = e.trace;
    if (!tr) { fig.append(el("div", "fg-empty", "발끝 기록 없음")); return fig; }
    const box = el("div", "fg-box");
    const danger = DATA.thresholds.loose[1];
    const flagged = e.level !== "ok";
    const fmt1 = (v) => (Math.round(v * 10) / 10).toFixed(1);
    const signed = (v) => `${v > 0.05 ? "+" : v < -0.05 ? "−" : "±"}${fmt1(Math.abs(v))}`;
    // 글자 폭 어림값 (한글 0.95em, 공백 0.3em, 그 밖 0.6em) — 범례·값 상자 폭 계산용
    const textW = (str, fs) => [...str].reduce((w, c) => w + (c.charCodeAt(0) >= 0x1100 ? 0.95 : c === " " ? 0.3 : 0.6), 0) * fs;
    const draw = () => {
      const W = Math.max(300, Math.round(box.clientWidth || 600));
      const small = W < 520;
      const H = small ? Math.round(W * 1.0) : Math.round(Math.min(470, W * 0.62));
      const fs = small ? 11 : 12.5;
      const L = small ? 44 : 54, R = 12, T = small ? 30 : 34, B = small ? 42 : 46;
      const PW = W - L - R, PH = H - T - B;
      const ts = tr.t, x0 = ts[0], x1 = ts[ts.length - 1];
      const X = (t) => L + ((t - x0) / (x1 - x0)) * PW;

      // 값 상자 (참고 그림의 빨간 테두리 상자)와 범례: 그래프 위쪽 여백 띠에 두어 데이터를 가리지 않는다
      const vb1 = `접지 높이: 평소보다 ${signed(tr.contact)} mm`, vb2 = `체중이 실린 뒤 추가 침하: ${fmt1(tr.extra)} mm`;
      const vw = Math.ceil(Math.max(textW(vb1, fs), textW(vb2, fs)) * 1.04 + 22), vh = Math.round(fs * 2 + 18);
      const items = [[`평소 걸음 범위 (${tr.n}걸음)`, "band"], ["평소 걸음 평균", "mean"], [`이번 걸음 (${flagged ? "흔들림 의심" : "정상 범위"})`, "step"]];
      const lh = Math.round(fs + 9), legH = items.length * lh + 8;
      const lw = Math.ceil(Math.max(...items.map(([t]) => textW(t, fs))) * 1.04 + 48);
      const oneRow = vw + lw + 24 <= PW;
      const vx = L + 8, vy = T + 6;
      const lx = oneRow ? W - R - lw - 8 : L + 8, ly = oneRow ? T + 6 : vy + vh + 6;
      const strip = (oneRow ? Math.max(vh, legH) : vh + 6 + legH) + 14;

      // 세로축: 위쪽 여백 띠만큼 늘려 데이터가 띠 아래에 오게 한다
      const lowest = Math.min(...tr.lo, ...tr.step, -danger) - 1.5;
      const highest = Math.max(...tr.hi, ...tr.step) + 1;
      const r = strip / PH;
      let y0 = Math.floor(lowest), y1 = Math.ceil((highest - r * y0) / (1 - r));
      // 위험 기준선 아래에 기준 글자가 들어갈 자리를 남긴다 (화면 px 기준)
      for (let k = 0; k < 3; k++) {
        const room = ((-danger - y0) / (y1 - y0)) * PH, need = fs + 8;
        if (room >= need) break;
        y0 = Math.floor(y0 - ((need - room) / PH) * (y1 - y0) - 0.5);
        y1 = Math.ceil((highest - r * y0) / (1 - r));
      }
      const Y = (z) => T + ((y1 - z) / (y1 - y0)) * PH;
      const pts = (arr) => arr.map((z, i) => `${X(ts[i]).toFixed(1)},${Y(z).toFixed(1)}`).join(" ");
      const ystep = [2, 5, 10, 20].find((st) => (y1 - y0) / st <= (small ? 8 : 10)) || 20;
      let grid = "", ticks = "";
      for (let t = -0.2; t <= x1 + 1e-9; t += 0.2) {
        const x = X(t).toFixed(1), lab = (Math.abs(t) < 1e-9 ? 0 : t).toFixed(1);
        grid += `<line x1="${x}" y1="${T}" x2="${x}" y2="${H - B}"/>`;
        ticks += `<text x="${x}" y="${H - B + fs + 4}" text-anchor="middle">${lab}</text>`;
      }
      for (let z = Math.ceil(y0 / ystep) * ystep; z <= y1; z += ystep) {
        const y = Y(z).toFixed(1);
        grid += `<line x1="${L}" y1="${y}" x2="${W - R}" y2="${y}"/>`;
        ticks += `<text x="${L - 6}" y="${(+y + fs * 0.35).toFixed(1)}" text-anchor="end">${z === 0 ? 0 : z}</text>`;
      }
      const band = `${pts(tr.hi)} ${tr.lo.map((z, i) => `${X(ts[i]).toFixed(1)},${Y(z).toFixed(1)}`).reverse().join(" ")}`;
      const title = `${flagged ? "흔들림 감지" : "발끝 높이 기록"} — ${legName(tr.leg)}, ${fmtDateTimeS(e.t).slice(11)}`;
      let legend = `<rect x="${lx}" y="${ly}" width="${lw}" height="${legH}" rx="10" style="fill:var(--surface);stroke:var(--border)"/>`;
      items.forEach(([label, k], i) => {
        const yy = ly + 4 + i * lh + lh / 2, kx = lx + 8;
        legend += k === "band" ? `<rect x="${kx}" y="${yy - 5}" width="24" height="10" style="fill:var(--band)"/>`
          : `<line x1="${kx}" y1="${yy}" x2="${kx + 24}" y2="${yy}" style="stroke:var(--${k});stroke-width:${k === "step" ? 3 : 2};${k === "mean" ? "stroke-dasharray:6 4" : ""}"/>`;
        legend += `<text x="${kx + 32}" y="${yy + fs * 0.35}">${label}</text>`;
      });
      const valueBox = `<rect x="${vx}" y="${vy}" width="${vw}" height="${vh}" rx="10" style="fill:var(--surface);stroke:var(--step);stroke-width:1.6"/>` +
        `<text x="${vx + 10}" y="${vy + fs + 5}" style="font-weight:600">${vb1}</text>` +
        `<text x="${vx + 10}" y="${vy + 2 * fs + 11}" style="font-weight:600">${vb2}</text>`;
      const contactY = T + strip + fs;  // "접지" 글자: 여백 띠 바로 아래 (접지 순간 근처는 높이가 낮아 비어 있다)
      box.innerHTML =
        `<svg xmlns="${SVGNS}" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${title}. ${vb1}, ${vb2}" ` +
        `style="font:${fs}px var(--font);fill:var(--text)">` +
        `<rect x="${L}" y="${T}" width="${PW}" height="${PH}" style="fill:var(--surface)"/>` +
        `<g style="stroke:var(--grid);stroke-width:1">${grid}</g>` +
        `<polygon points="${band}" style="fill:var(--band)"/>` +
        `<line x1="${L}" y1="${Y(0)}" x2="${W - R}" y2="${Y(0)}" style="stroke:var(--muted);stroke-width:1"/>` +
        `<line x1="${L}" y1="${Y(-danger)}" x2="${W - R}" y2="${Y(-danger)}" style="stroke:var(--danger);stroke-width:1.5;stroke-dasharray:2 4"/>` +
        `<text x="${L + 6}" y="${Y(-danger) + fs + 3}" style="fill:var(--danger-ink);font-weight:600">위험 기준 −${danger}mm</text>` +  // 접지 전(왼쪽)은 높이가 높아 기준선 아래가 비어 있다
        `<line x1="${X(0)}" y1="${T}" x2="${X(0)}" y2="${H - B}" style="stroke:var(--muted);stroke-width:1.3;stroke-dasharray:5 4"/>` +
        `<text x="${X(0) + 5}" y="${contactY}" style="fill:var(--muted)">접지</text>` +
        `<polyline points="${pts(tr.mean)}" style="fill:none;stroke:var(--mean);stroke-width:2;stroke-dasharray:6 4;stroke-linejoin:round"/>` +
        `<polyline points="${pts(tr.step)}" style="fill:none;stroke:var(--step);stroke-width:3;stroke-linejoin:round"/>` +
        `<rect x="${L}" y="${T}" width="${PW}" height="${PH}" style="fill:none;stroke:var(--muted);stroke-width:1"/>` +
        `<g style="fill:var(--muted)">${ticks}</g>` + legend + valueBox +
        `<text x="${W / 2}" y="${T - 12}" text-anchor="middle" style="font-weight:700;font-size:${fs + 2}px">${title}</text>` +
        `<text x="${(L + W - R) / 2}" y="${H - 8}" text-anchor="middle">발이 땅에 닿은 뒤 시간 [초]</text>` +
        `<text transform="translate(${small ? 12 : 15},${(T + H - B) / 2}) rotate(-90)" text-anchor="middle">발끝 높이 [mm]</text>` +
        `</svg>`;
    };
    fig.append(box, el("figcaption", null,
      `높이 0mm = 평소 걸음이 딛고 있을 때의 평균 높이. 추가 침하는 접지 직후 내려오는 구간을 빼고, 발이 멈춘 뒤(접지 후 ${tr.t_settle.toFixed(2)}초)부터 계산`));
    P.redraw = draw;
    requestAnimationFrame(draw);
    return fig;
  }
  addEventListener("resize", () => { if (state.page === "physical" && P.redraw) requestAnimationFrame(P.redraw); });

  function renderPhysicalDetail() {
    const box = $("p-detail");
    box.replaceChildren();
    P.redraw = null;
    const e = state.sel && byId[state.sel.id];
    if (!e) { box.append(el("p", "v-empty", "목록에서 지점을 고르세요")); return; }
    const head = el("div", "v-head");
    const kind = el("span", "kind");
    kind.append(svgIcon(e.kind, e.level), el("span", null, KIND[e.kind].label), lvBadge(e.level));
    const inReport = e.level !== "ok";
    head.append(kind, el("span", `rep${inReport ? " in" : ""}`, inReport ? "신고서에 포함됨" : "신고서 대상 아님 (정상)"));
    box.append(head);

    // 사진 (image_mark 점선 동그라미 + "외관 정상, 발 접촉으로 확인" 설명은 기존 함수). 없으면 안내만
    if (e.photo) box.append(photoFigure(e));
    else { const np = el("div", "no-photo"); np.append(svgIcon(e.kind, null), el("span", null, "사진 없음")); box.append(np); }

    const big = el("div", "v-big");
    big.append(el("span", "num", fmtNum(e.value, e.unit)), el("span", "unit", UNIT[e.unit]));
    const crit = el("p", "v-crit");
    crit.append(el("span", "k", "기준 "), document.createTextNode(criterion(e)), el("span", "x", ` · 기준의 ${Number(e.ratio).toFixed(1)}배`));
    box.append(big, crit, footGraph(e));

    const basis = el("section", "v-basis");
    basis.append(el("h2", null, "측정 근거"));
    const dl = el("dl");
    const row = (k, v) => dl.append(el("dt", null, k), el("dd", null, v));
    row("측정 방법", "관절 각도 → 발끝 위치(정기구학), IMU 중력 정렬, 평소 걸음 대비");
    row("측정 다리", legName(e.leg) || "—");
    row("평소 걸음 수", e.trace ? `${e.trace.n}걸음` : "—");
    row("위도·경도", `${Number(e.lat).toFixed(6)}, ${Number(e.lon).toFixed(6)}`);
    row("측정 시각", fmtDateTimeS(e.t));
    if (e.note) row("메모", e.note);
    row("ID", e.id);
    basis.append(dl);
    box.append(basis);

    // 외관 검사 비교: 1m 안의 외관 이상 지점
    const near = el("section", "p-near");
    near.append(el("h2", null, "외관 검사 비교"));
    const ids = e.near_visual || [];
    if (!ids.length) near.append(el("p", null, "1m 안에 외관 이상 지점 없음 · 카메라로는 이상 없음"));
    else {
      const ul = el("ul");
      for (const i of ids) {
        const o = byId[i], a = el("a", null, `${kindValue(o)} · ${LEVEL[o.level].label} (${o.id})`);
        a.href = `#visual/${o.id}`;
        const li = el("li"); li.append(a); ul.append(li);
      }
      near.append(el("p", null, "1m 안의 외관 이상 지점:"), ul);
    }
    box.append(near);

    const act = el("div", "v-actions");
    const toMap = el("button", "btn primary", "지도에서 위치 보기");
    toMap.type = "button";
    toMap.addEventListener("click", () => { location.hash = `#home/${e.id}`; });
    act.append(toMap);
    box.append(act);
  }
  function renderPhysical() {
    renderPhysicalList();
    renderPhysicalDetail();
    const e = state.sel && byId[state.sel.id];
    $("p-crumb").textContent = e ? `${kindValue(e)} (${e.id})` : "물리적 안정성 검사";
    const row = document.querySelector('#p-list .v-row[aria-selected="true"]');
    if (row) row.scrollIntoView({ block: "nearest" });
    if (P.scrollToDetail && e) $("p-detail").scrollIntoView({ block: "start", behavior: reduceMotion.matches ? "auto" : "smooth" });
    P.scrollToDetail = false;
  }

  // ---------------------------------------------------------------- 종합 현황: 지도 옆 상세 패널
  // 측정 방식 (events.csv source)
  const SOURCE_LABEL = { camera: "카메라", foot: "발 접촉", "camera+foot": "카메라 + 발 접촉" };
  const CLOSE_ICON = '<path d="M6 6l12 12M18 6 6 18" style="fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round"/>';
  function closePanel() { location.replace("#home"); }
  function renderPanel() {
    const box = $("dpanel");
    box.replaceChildren();
    const e = state.sel && byId[state.sel.id];
    if (!e) {
      const p = el("p", "dp-empty");
      p.append(svgIcon("loose", null), document.createTextNode("지도에서 지점을 누르면 사진과 근거가 여기에 표시돼요"));
      box.append(p);
      return;
    }
    const close = el("button", "dp-close");
    close.type = "button";
    close.setAttribute("aria-label", "상세 닫기");
    close.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${CLOSE_ICON}</svg>`;
    close.addEventListener("click", closePanel);

    // a. 판정 배지 + 종류 + 지점 id
    const head = el("div", "dp-head");
    const kind = el("span", "kind");
    kind.append(svgIcon(e.kind, e.level), el("span", null, KIND[e.kind].label));
    head.append(lvBadge(e.level), kind, el("span", "id", e.id));
    box.append(close, head);

    const ok = e.level === "ok";
    // b. 사진 (흔들림 image_mark는 점선 동그라미를 겹친다). 정상 지점은 사진·근거 대신 "기준 이내"
    if (!ok) {
      const noPhoto = () => { const np = el("div", "no-photo"); np.append(svgIcon(e.kind, null), el("span", null, "사진 없음")); return np; };
      if (e.photo) {
        const btn = el("button", "ph-btn");
        btn.type = "button";
        btn.setAttribute("aria-label", "사진 크게 보기");
        btn.append(photoView(e, () => btn.replaceWith(noPhoto()), true));
        btn.addEventListener("click", () => openPhoto(e));
        box.append(btn);
      } else {
        box.append(noPhoto());
      }
    }
    // c. 측정값
    const big = el("div", "v-big");
    big.append(el("span", "num", fmtNum(e.value, e.unit)), el("span", "unit", e.unit === "score" ? "균열 점수 (0~1)" : UNIT[e.unit]));
    box.append(big);
    // d. 근거: criterion_text + exceed_ratio (외관 검사 상세와 같은 문구, 균열 점수는 배수 표시 안 함)
    const crit = el("p", "v-crit");
    if (ok) crit.textContent = "기준 이내";
    else {
      crit.append(el("span", "k", "기준 "), document.createTextNode(criterion(e)));
      if (e.kind !== "crack") crit.append(el("span", "x", ` · 기준의 ${Number(e.ratio).toFixed(1)}배`));
    }
    box.append(crit);
    // e·f. 위치, 측정 시각·방식
    const info = el("section", "v-basis");
    const dl = el("dl");
    const row = (k, v) => dl.append(el("dt", null, k), el("dd", null, v));
    row("위치", `${Number(e.lat).toFixed(6)}, ${Number(e.lon).toFixed(6)}`);
    if (!ok) {
      row("측정 시각", fmtDateTimeS(e.t));
      row("측정 방식", `${SOURCE_LABEL[e.source] || e.source}${e.leg ? ` · ${legName(e.leg)}` : ""}`);
    }
    info.append(dl);
    box.append(info);
    // g. 자세히 보기: 흔들림은 물리적 안정성, 나머지는 외관 검사
    const act = el("div", "dp-actions");
    const more = el("a", "btn primary", "자세히 보기");
    more.href = detailHref(e);
    more.setAttribute("aria-label", `자세히 보기 (${PAGES[pageFor(e)].title})`);
    act.append(more);
    box.append(act);
  }

  // 종합 현황 지도에서 지점 위치 보기 (#home/<id>): 확대하고 선택 표시
  function focusOnMap(e) {
    if (!shown[e.level]) setShown(e.level, true);  // 꺼진 판정의 지점이면 그 판정을 켠다
    if (state.mode === "tiles" && state.map) state.map.setView([e.lat, e.lon], state.map.getMaxZoom(), { animate: false });
    renderMap();
  }

  // ---------------------------------------------------------------- 주소 해시로 페이지·선택 지점 (뒤로 가기 동작)
  // ---------------------------------------------------------------- 점검 이력
  const SOURCE = { camera: "카메라", foot: "발", "camera+foot": "교차" };
  // 점검 날짜 (최신순). 날짜를 고르면(#history/<YYYY-MM-DD>) KPI·막대·지점 표·CSV가 그날 데이터로 바뀐다.
  // 가장 최근 날짜 = 종합 현황 데이터 (DATA.events). 지난 날짜의 지점은 상세 페이지가 없어 표에서 이동하지 않는다
  const DATES = DATA.dates;
  const DATE_BY = Object.fromEntries(DATES.map((d) => [d.date, d]));
  const NEWEST = DATES.length ? DATES[0].date : null;
  const H = { date: NEWEST, kind: "all", level: "all", source: "all", sort: { key: "level", dir: -1 }, showOk: false };
  const H_FILTERS = ["kind", "level", "source"];
  const dateEvents = (date) => (DATE_BY[date] && DATE_BY[date].events) || DATA.events;
  const worstOf = (date) => LEVELS.find((lv) => dateEvents(date).some((e) => e.level === lv));
  const WEEKDAY = "일월화수목금토";
  const ymd = (date) => date.split("-").map(Number);
  const weekday = (date) => { const [y, m, d] = ymd(date); return WEEKDAY[new Date(Date.UTC(y, m - 1, d)).getUTCDay()]; };
  const chipLabel = (date) => { const [, m, d] = ymd(date); return `${String(m).padStart(2, "0")}.${String(d).padStart(2, "0")}`; };
  const fmtMDHMS = (t) => { const p = tparts(t); return `${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second}`; };
  const historyShown = () => dateEvents(H.date).filter((e) =>
    (H.kind === "all" || e.kind === H.kind) && (H.level === "all" || e.level === H.level) && (H.source === "all" || e.source === H.source));

  // ---- 날짜 칩 + 달력
  const chips = [...document.querySelectorAll("#h-chips .h-chip")];
  const cal = $("h-cal"), calBtn = $("h-cal-btn");
  const MONTHS = DATES.map((d) => d.date.slice(0, 7));
  let calMonth = null;  // 달력에 보이는 달 "YYYY-MM"
  const addMonth = (ym, n) => { const [y, m] = ymd(ym); const d = new Date(Date.UTC(y, m - 1 + n, 1)); return d.toISOString().slice(0, 7); };
  function selectDate(date) {
    closeCal();
    if (date !== H.date) location.replace(`#history/${date}`);  // 같은 페이지 안 선택은 방문 기록을 쌓지 않는다
  }
  for (const c of chips) c.addEventListener("click", () => selectDate(c.dataset.date));
  const ARROW = (d) => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${d}" style="fill:none;stroke:currentColor;stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round"/></svg>`;
  function renderCal() {
    const [y, m] = ymd(calMonth);
    cal.replaceChildren();
    const head = el("div", "h-cal-head");
    const nav = (label, path, n, off) => {
      const b = el("button");
      b.type = "button";
      b.setAttribute("aria-label", label);
      b.innerHTML = ARROW(path);
      b.disabled = off;
      b.addEventListener("click", () => {
        calMonth = addMonth(calMonth, n);
        renderCal();
        const again = cal.querySelector(`.h-cal-head [aria-label="${label}"]`);  // 다시 그린 같은 버튼 (끝 달이면 첫 점검 날)
        (again.disabled ? cal.querySelector(".h-cal-grid button:not(:disabled)") || calBtn : again).focus();
      });
      return b;
    };
    const title = el("span", null, `${y}년 ${m}월`);
    title.setAttribute("aria-live", "polite");
    head.append(nav("이전 달", "M15 5l-7 7 7 7", -1, calMonth <= MONTHS[MONTHS.length - 1]), title,
                nav("다음 달", "M9 5l7 7-7 7", 1, calMonth >= MONTHS[0]));
    const grid = el("div", "h-cal-grid");
    for (const w of WEEKDAY) grid.append(el("span", "wd", w));
    const first = new Date(Date.UTC(y, m - 1, 1)).getUTCDay(), days = new Date(Date.UTC(y, m, 0)).getUTCDate();
    for (let i = 0; i < first; i++) grid.append(el("span"));
    for (let d = 1; d <= days; d++) {
      const date = `${calMonth}-${String(d).padStart(2, "0")}`;
      const b = el("button", null, String(d));
      b.type = "button";
      if (DATE_BY[date]) {
        const worst = worstOf(date);
        const dot = el("span", `h-dot h-dot-${worst || "none"}`);
        dot.setAttribute("aria-hidden", "true");
        b.append(dot);
        b.setAttribute("aria-pressed", String(date === H.date));
        b.setAttribute("aria-label", `${m}월 ${d}일 (${weekday(date)}) 점검${worst ? `, 가장 높은 판정 ${LEVEL[worst].label}` : ""}`);
        b.addEventListener("click", () => { selectDate(date); calBtn.focus(); });
      } else {
        b.disabled = true;
        b.setAttribute("aria-label", `${m}월 ${d}일, 점검 없음`);
      }
      grid.append(b);
    }
    cal.append(head, grid);
  }
  function openCal() {
    calMonth = (H.date || NEWEST).slice(0, 7);
    renderCal();
    cal.hidden = false;
    calBtn.setAttribute("aria-expanded", "true");
    cal.style.left = `${Math.max(0, calBtn.offsetLeft + calBtn.offsetWidth - cal.offsetWidth)}px`;  // 달력 버튼 오른쪽 끝에 맞춘다
    (cal.querySelector('.h-cal-grid button[aria-pressed="true"]') || cal.querySelector(".h-cal-grid button:not(:disabled)"))?.focus();
  }
  function closeCal(focusBtn = false) {
    if (cal.hidden) return;
    cal.hidden = true;
    calBtn.setAttribute("aria-expanded", "false");
    if (focusBtn) calBtn.focus();
  }
  calBtn.addEventListener("click", () => (cal.hidden ? openCal() : closeCal()));
  // 바깥을 누르면 닫는다 (달력 안 버튼은 누르면 다시 그려져 문서에서 빠지므로 composedPath로 확인)
  document.addEventListener("click", (ev) => { const path = ev.composedPath(); if (!cal.hidden && !path.includes(cal) && !path.includes(calBtn)) closeCal(); });
  addEventListener("keydown", (ev) => { if (ev.key === "Escape" && !cal.hidden) closeCal(true); });
  $("h-dates").hidden = !DATES.length;

  {
    const fill = (id, opts) => {
      const sel = $(id);
      for (const [v, label] of opts) { const o = el("option", null, label); o.value = v; sel.append(o); }
      sel.addEventListener("change", () => { H[id.slice(2)] = sel.value; renderHistory(); });
    };
    fill("h-kind", [["all", "전체 종류"], ...KINDS.map((k) => [k, KIND[k].label])]);
    fill("h-level", [["all", "전체 판정"], ...LEVELS.map((l) => [l, LEVEL[l].label])]);
    fill("h-source", [["all", "전체 방식"], ...Object.entries(SOURCE)]);
    $("h-reset").addEventListener("click", () => {
      for (const k of H_FILTERS) { H[k] = "all"; $(`h-${k}`).value = "all"; }
      renderHistory();
    });
    if (DATA.report) $("h-report").setAttribute("href", DATA.report);
    $("h-ok-toggle").addEventListener("click", () => { H.showOk = !H.showOk; renderHistory(); });
    $("h-route-btn").addEventListener("click", toggleRoute);  // 신고서는 가장 최근 점검만 (날짜를 고르면 보이기·숨기기)
    $("h-csv").addEventListener("click", downloadCsv);
  }

  // 현재 필터 결과를 events.csv와 같은 열·형식으로 (BOM: 엑셀에서 한글이 깨지지 않게). 순서는 events.csv 순서
  function csvText(list) {
    const q = (v) => (/[",\r\n]/.exec(v) ?`"${v.replace(/"/g, '""')}"` : v);
    const lines = [DATA.csv_columns, ...list.map((e) => e.csv)].map((r) => r.map(q).join(","));
    return "\ufeff" + lines.join("\r\n") + "\r\n";
  }
  function downloadCsv() {
    const list = historyShown();
    const tag = [H.date, ...H_FILTERS.filter((k) => H[k] !== "all").map((k) => H[k])].filter(Boolean).map((v) => v.replace(/[^\w+-]/g, "")).join("_");
    const a = el("a");
    a.href = URL.createObjectURL(new Blob([csvText(list)], { type: "text/csv;charset=utf-8" }));
    a.download = tag ? `events_${tag}.csv` : "events.csv";
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // 지점 표 정렬 (기본: 위험 먼저, 같은 판정 안에서는 기준 대비 큰 순 = 종합 현황 목록·신고서와 같은 순서)
  const H_COLS = [
    { key: "level",  label: "판정",      cmp: byIssueOrder },
    { key: "kind",   label: "종류",      cmp: (a, b) => KINDS.indexOf(a.kind) - KINDS.indexOf(b.kind) || byIssueOrder(a, b) },
    { key: "value",  label: "값",        cmp: (a, b) => KINDS.indexOf(a.kind) - KINDS.indexOf(b.kind) || a.value - b.value, num: true },
    { key: "crit",   label: "기준",      cmp: (a, b) => a.criterion.localeCompare(b.criterion, "ko") },
    { key: "source", label: "측정 방식", cmp: (a, b) => SOURCE[a.source].localeCompare(SOURCE[b.source], "ko") },
    { key: "latlon", label: "위도·경도", cmp: (a, b) => a.lat - b.lat || a.lon - b.lon },
    { key: "t",      label: "시각",      cmp: (a, b) => a.t - b.t },
    { key: "go",     label: "보기" },
  ];
  function renderHistoryHead() {
    const tr = $("h-points-head");
    tr.replaceChildren();
    for (const c of H_COLS) {
      const th = el("th");
      th.scope = "col";
      if (c.num) th.className = "num";
      if (!c.cmp) { th.append(el("span", null, c.label)); tr.append(th); continue; }
      const b = el("button");
      b.type = "button";
      const on = H.sort.key === c.key;
      if (on) th.setAttribute("aria-sort", H.sort.dir < 0 ? "descending" : "ascending");
      b.append(el("span", null, c.label), el("span", "arr", on ? (H.sort.dir < 0 ? "▼" : "▲") : ""));
      b.addEventListener("click", () => {
        // 판정은 처음 누르면 위험 먼저(내림), 나머지는 오름차순부터
        H.sort = on ? { key: c.key, dir: -H.sort.dir } : { key: c.key, dir: c.key === "level" ? -1 : 1 };
        renderHistory();
      });
      th.append(b);
      tr.append(th);
    }
  }

  // ---- 그날 지도: 이동경로(accent 선) + 100 m 눈금 + 출발·도착 + 그날 지점 마커 (종합 현황 지도와 따로)
  // 경로·눈금은 Python route_payload (path_length와 같은 1 m 규칙). 지도 범위는 날짜가 바뀔 때 그날 경로에 맞춘다.
  // 마커·행을 누르면 상세 페이지로 (방문 기록에 남겨 뒤로 가기 → #history/<날짜>). 상세 페이지는 가장 최근 점검만 있다
  const HM = { mode: null, map: null, layers: null, routeLayer: null, markers: {}, hover: null, showRoute: true, fitted: null,
               tiles: { loaded: 0, failed: 0 } };
  const dateRoute = (date) => (DATE_BY[date] && DATE_BY[date].route) || { ll: [], xy: [], ticks: [], total: 0 };
  const dateMeters = (date) => (DATE_BY[date] ? DATE_BY[date].meters : 0);  // display_meters (KPI 점검 거리와 같은 값)
  const hOpen = (e) => { hideTip(); location.hash = detailHref(e); };
  const hTip = (e, newest) => ({
    lines: [`${KIND[e.kind].label} ${fmtValue(e)} · ${LEVEL[e.level].label}`, `기준 ${criterion(e)}`, e.id],
    hint: newest ? `클릭 → ${PAGES[pageFor(e)].title}` : "상세 페이지는 가장 최근 점검만",
  });
  // 경로 위 글자 자리 (마커와 겹치지 않게 경로 바깥쪽). d: 화면 방향 [오른쪽, 위쪽]
  // 눈금: 가로 구간이면 위, 세로 구간이면 오른쪽. 출발·도착: 경로가 이어지는 반대쪽
  const tickSide = (d) => (Math.abs(d[0]) >= Math.abs(d[1]) ? "t" : "r");
  const endSide = (d) => (Math.abs(d[0]) >= Math.abs(d[1]) ? (d[0] > 0 ? "l" : "r") : (d[1] > 0 ? "b" : "t"));
  const llDir = (a, b) => [(b[1] - a[1]) * Math.cos(a[0] * Math.PI / 180), b[0] - a[0]];
  const xyDir = (a, b) => [b[0] - a[0], b[1] - a[1]];
  const routeDirs = (pts, dir, ticks) => {
    const n = pts.length, k = Math.min(15, n - 1);  // 끝에서 약 15 m 안쪽 점 쪽으로
    return { start: endSide(dir(pts[0], pts[k])), end: endSide(dir(pts[n - 1], pts[n - 1 - k])),
             ticks: ticks.map((t) => tickSide(dir(pts[t.i], pts[Math.min(t.i + 1, n - 1)]))) };
  };
  const hMarkerSvg = (e) => `<svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">${markerInner(e, e.id === HM.hover)}</svg>`;

  function startHMap() {
    if (HM.mode) return;
    // Leaflet이 없거나 종합 현황 지도가 이미 타일을 못 받았으면 바로 평면 지도
    if (!window.L || state.mode === "plane") { HM.mode = "plane"; return; }
    HM.mode = "tiles";
    const map = L.map("h-map", { zoomControl: false });
    L.control.zoom({ position: "topright" }).addTo(map);  // 왼쪽 위는 "이동경로" 버튼 자리
    map.attributionControl.setPosition("bottomright");
    const tiles = L.tileLayer("__TILE_URL__", { subdomains: "abc", maxNativeZoom: __TILE_MAX_NATIVE_ZOOM__, maxZoom: 19,
                                                attribution: '__TILE_ATTRIBUTION__' });
    tiles.on("tileload", () => { HM.tiles.loaded++; });
    tiles.on("tileerror", () => { HM.tiles.failed++; if (!HM.tiles.loaded && HM.tiles.failed >= 4) hPlane(); });
    tiles.addTo(map);
    HM.map = map;
    setTimeout(() => { if (HM.mode === "tiles" && !HM.tiles.loaded) hPlane(); }, 10000);
  }
  function hPlane() {
    if (HM.mode === "plane") return;
    if (HM.map) { HM.map.remove(); HM.map = null; }
    HM.mode = "plane";
    drawHMap();
  }
  function drawHMap() {
    if ($("page-history").hidden) return;  // 숨겨진 상자는 크기가 0이라 지도 맞춤이 깨진다
    startHMap();
    const r = dateRoute(H.date), evs = dateEvents(H.date);
    $("h-map-sub").textContent = `${dateMeters(H.date).toLocaleString("ko-KR")} m · 지점 ${evs.length}개`;
    $("h-map").hidden = HM.mode !== "tiles";
    $("h-plane").hidden = HM.mode !== "plane";
    if (HM.mode === "plane") { drawHPlane(); return; }
    const map = HM.map, newest = H.date === NEWEST;
    map.invalidateSize({ animate: false });
    if (HM.fitted !== H.date) {  // 범위를 먼저 정해야 마커를 올릴 수 있다
      const pts = r.ll.length ? r.ll : evs.map((e) => [e.lat, e.lon]);
      if (pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.05)); else map.setView([33.4886, 126.4890], 16);
      HM.fitted = H.date;
    }
    if (HM.layers) HM.layers.remove();
    if (HM.routeLayer) HM.routeLayer.remove();
    HM.layers = L.layerGroup().addTo(map);
    HM.routeLayer = L.layerGroup();
    if (r.ll.length > 1) {
      L.polyline(r.ll, { className: "h-route-casing", weight: 6, opacity: 1, interactive: false }).addTo(HM.routeLayer);
      L.polyline(r.ll, { className: "h-route-line", weight: 3, opacity: 1, interactive: false }).addTo(HM.routeLayer);
      const pin = (ll, html, z) => L.marker(ll, { icon: L.divIcon({ className: "h-pin", iconSize: [0, 0], html }), interactive: false,
                                                  keyboard: false, zIndexOffset: z }).addTo(HM.routeLayer);
      const sd = routeDirs(r.ll, llDir, r.ticks);
      r.ticks.forEach((t, j) => pin(t.ll, `<span class="h-tick s-${sd.ticks[j]}"><i></i><b>${t.m} m</b></span>`, -800));
      pin(r.ll[0], `<span class="h-end start s-${sd.start}"><i></i><b>출발</b></span>`, -600);
      pin(r.ll[r.ll.length - 1], `<span class="h-end finish s-${sd.end}"><i></i><b>도착 ${dateMeters(H.date).toLocaleString("ko-KR")} m</b></span>`, -600);
    }
    if (HM.showRoute) HM.routeLayer.addTo(map);
    HM.markers = {};
    for (const e of [...evs].sort((a, b) => LEVEL[a.level].rank - LEVEL[b.level].rank)) {
      const m = L.marker([e.lat, e.lon], { icon: L.divIcon({ className: "ev-marker", iconSize: [24, 24], html: hMarkerSvg(e) }),
                                           zIndexOffset: LEVEL[e.level].z, keyboard: newest });
      if (newest) m.on("click", () => hOpen(e));
      m.addTo(HM.layers);
      HM.markers[e.id] = { m, e };
      decorateHMarker(HM.markers[e.id], newest);
    }
  }
  function decorateHMarker(x, newest) {
    const node = x.m.getElement();
    if (newest) node.setAttribute("role", "button"); else node.style.cursor = "default";
    wire(node, hTip(x.e, newest));
  }
  // 지점 목록 행에 마우스를 올리면 지도 마커를 강조 (흰색 링, 맨 위로)
  function setHover(id) {
    if (HM.hover === id) return;
    const prev = HM.hover;
    HM.hover = id;
    if (HM.mode === "plane") { drawHPlane(); return; }
    for (const k of [prev, id]) {
      const x = k && HM.markers[k];
      if (!x) continue;
      x.m.setIcon(L.divIcon({ className: "ev-marker", iconSize: [24, 24], html: hMarkerSvg(x.e) }));
      x.m.setZIndexOffset(k === id ? 3000 : LEVEL[x.e.level].z);
      decorateHMarker(x, H.date === NEWEST);  // 아이콘을 바꾸면 요소가 새로 만들어진다
    }
  }
  function toggleRoute() {
    HM.showRoute = !HM.showRoute;
    $("h-route-btn").setAttribute("aria-pressed", String(HM.showRoute));
    if (HM.mode === "tiles" && HM.routeLayer) { if (HM.showRoute) HM.routeLayer.addTo(HM.map); else HM.routeLayer.remove(); }
    else if (HM.mode === "plane") drawHPlane();
  }

  // 인터넷이 없을 때: odom (x, y) 평면 SVG (경로·눈금·출발·도착·마커). 범위는 그날 경로
  function drawHPlane() {
    const box = $("h-plane"), W = box.clientWidth, Ht = box.clientHeight;
    if (W < 120 || Ht < 120) return;
    const r = dateRoute(H.date), evs = dateEvents(H.date), newest = H.date === NEWEST;
    const pts = r.xy.length ? r.xy : evs.map((e) => [e.x, e.y]);
    box.replaceChildren();
    if (!pts.length) return;
    const xs = pts.map((q) => q[0]), ys = pts.map((q) => q[1]);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    const pad = 40, padT = 60;
    const k = Math.min((W - 2 * pad) / Math.max(maxX - minX, 1), (Ht - pad - padT) / Math.max(maxY - minY, 1));
    const ox = (W - (maxX - minX) * k) / 2, oy = padT + (Ht - pad - padT - (maxY - minY) * k) / 2;
    const X = (x) => ox + (x - minX) * k, Y = (y) => oy + (maxY - y) * k;
    // 글자 상자: 한글은 글자 크기만큼, 그 밖은 0.6배 폭으로 어림
    // side: 점(cx, cy)에서 gap만큼 떨어진 글자 자리 (t 위 / b 아래 / l 왼쪽 / r 오른쪽)
    const tag = (cx, cy, side, gap, text, fs, bold) => {
      const w = [...text].reduce((a, ch) => a + (ch.charCodeAt(0) >= 0x1100 ? fs : fs * 0.6), 0) + 10, h = fs + 7;
      const x = side === "r" ? cx + gap : side === "l" ? cx - gap - w : cx - w / 2;
      const y = side === "t" ? cy - gap - h : side === "b" ? cy + gap : cy - h / 2;
      return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${w.toFixed(1)}" height="${h}" rx="6" style="fill:var(--ctl-bg);stroke:var(--ctl-border)"/>` +
             `<text x="${(x + 5).toFixed(1)}" y="${(y + h / 2 + fs * 0.36).toFixed(1)}" style="fill:var(--ctl-text);font:${bold} ${fs}px var(--font)">${text}</text>`;
    };
    let out = `<svg xmlns="${SVGNS}" width="${W}" height="${Ht}">` +
              `<text x="16" y="${Ht - 14}" style="fill:var(--map-text);font:12px var(--font)">odom 좌표</text>`;
    if (HM.showRoute && r.xy.length > 1) {
      const line = r.xy.map((q) => `${X(q[0]).toFixed(1)},${Y(q[1]).toFixed(1)}`).join(" ");
      out += `<polyline points="${line}" style="fill:none;stroke:#FFFFFF;stroke-width:6;stroke-linejoin:round;stroke-linecap:round"/>` +
             `<polyline points="${line}" style="fill:none;stroke:var(--h-route);stroke-width:3;stroke-linejoin:round;stroke-linecap:round"/>`;
      const sd = routeDirs(r.xy, xyDir, r.ticks);
      r.ticks.forEach((t, j) => {
        const x = X(t.xy[0]), y = Y(t.xy[1]);
        out += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3" style="fill:#FFFFFF;stroke:var(--h-route);stroke-width:2"/>` +
               tag(x, y, sd.ticks[j], sd.ticks[j] === "t" ? 15 : 9, `${t.m} m`, 10.5, 650);
      });
      const end = (q, side, fill, text) => {
        const x = X(q[0]), y = Y(q[1]);
        return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="5.5" style="fill:${fill};stroke:#FFFFFF;stroke-width:3"/>` +
               `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="7.5" style="fill:none;stroke:#0B1220;stroke-width:1.5"/>` + tag(x, y, side, 12, text, 11.5, 750);
      };
      out += end(r.xy[0], sd.start, "var(--h-route)", "출발") +
             end(r.xy[r.xy.length - 1], sd.end, "#0B1220", `도착 ${dateMeters(H.date).toLocaleString("ko-KR")} m`);
    }
    box.innerHTML = out + "</svg>";
    const layer = document.createElementNS(SVGNS, "g");
    for (const e of [...evs].sort((a, b) => LEVEL[a.level].rank - LEVEL[b.level].rank || (a.id === HM.hover) - (b.id === HM.hover))) {  // 강조한 지점은 맨 위
      const node = document.createElementNS(SVGNS, "g");
      node.setAttribute("class", "ev");
      node.setAttribute("transform", `translate(${(X(e.x) - 12).toFixed(1)},${(Y(e.y) - 12).toFixed(1)})`);
      const sel = e.id === HM.hover;
      node.innerHTML = `<rect class="hit" x="-2" y="-2" width="28" height="28" rx="6" fill="transparent"/>` + markerInner(e, sel);
      if (newest) {
        node.setAttribute("tabindex", "0");
        node.setAttribute("role", "button");
        node.style.cursor = "pointer";
        node.addEventListener("click", () => hOpen(e));
      }
      wire(node, hTip(e, newest), newest ? () => hOpen(e) : null);
      layer.append(node);
    }
    box.firstElementChild.append(layer);
  }
  {
    let pending = 0;
    addEventListener("resize", () => {
      if (HM.mode !== "plane" || $("page-history").hidden) return;
      cancelAnimationFrame(pending);
      pending = requestAnimationFrame(drawHPlane);
    });
  }

  function renderHistory() {
    const all = dateEvents(H.date), list = historyShown(), newest = H.date === NEWEST;
    for (const k of H_FILTERS) $(`h-${k}`).classList.toggle("on", H[k] !== "all");
    $("h-reset").hidden = H_FILTERS.every((k) => H[k] === "all");
    for (const c of chips) c.setAttribute("aria-pressed", String(c.dataset.date === H.date));
    chips.find((c) => c.dataset.date === H.date)?.scrollIntoView({ block: "nearest", inline: "nearest" });
    $("history-sub").textContent = [H.date ? `${H.date} (${weekday(H.date)}) 점검` : "", DATA.area, "필터는 지점 목록에 적용"].filter(Boolean).join(" · ");
    $("h-report").hidden = $("h-report-note").hidden = !(DATA.report && newest);

    // 그날 KPI (종합 현황 KPI와 같은 카드·함수). 점검 거리는 display_meters, 판정 개수는 필터와 상관없이 그날 전체
    const i = DATES.findIndex((d) => d.date === H.date), prev = i >= 0 ? DATES[i + 1] : null;
    putDistance($("h-k-dist"), i >= 0 ? DATES[i].meters : DATA.distance_m);
    $("h-k-dist-sub").textContent = `측정 지점 ${all.length}개`;
    for (const lv of LEVELS) {
      const n = countLevel(all, lv);
      $(`h-k-${lv}`).textContent = n;
      if (!prev) { $(`h-k-${lv}-sub`).textContent = i >= 0 ? "첫 점검" : ""; continue; }
      const diff = n - countLevel(dateEvents(prev.date), lv);
      $(`h-k-${lv}-sub`).textContent = `${chipLabel(prev.date)} 대비 ${diff > 0 ? `+${diff}` : diff === 0 ? "변화 없음" : diff}`;
    }

    // 종류별 판정 누적 막대: 그날 전체 지점 (필터와 무관, 합계 = KPI 위험·주의·정상). 길이는 가장 많은 종류 기준
    const bars = $("h-bars");
    bars.replaceChildren();
    const per = KINDS.map((k) => ({ k, c: LEVELS.map((lv) => all.filter((e) => e.kind === k && e.level === lv).length) }));
    const maxTotal = Math.max(1, ...per.map((r) => r.c[0] + r.c[1] + r.c[2]));
    for (const { k, c } of per) {
      const total = c[0] + c[1] + c[2];
      const row = el("div", "h-bar");
      const name = el("span", "k"); name.append(svgIcon(k, null), el("span", null, KIND[k].label));
      const track = el("div", "track");
      track.style.width = `calc((100% - 40px) * ${total / maxTotal})`;  // 오른쪽에 합계 숫자 자리
      track.setAttribute("role", "img");
      const desc = LEVELS.map((lv, i) => `${LEVEL[lv].label} ${c[i]}`).join(", ");
      track.setAttribute("aria-label", `${KIND[k].label}: ${desc}`);
      LEVELS.forEach((lv, i) => {
        if (!c[i]) return;
        const seg = el("span", `seg ${lv}`);
        seg.append(el("span", null, `${LEVEL[lv].glyph}${c[i]}`));
        seg.style.flex = `${c[i]} 1 0`;
        seg.title = `${KIND[k].label} · ${LEVEL[lv].label} ${c[i]}`;
        track.append(seg);
      });
      const line = el("div", "line");
      line.append(total ? track : el("span", "zero", "없음"), el("b", "tot", String(total)));
      row.append(name, line);
      const sum = el("div", "sum");
      LEVELS.forEach((lv, i) => {
        if (i) sum.append(document.createTextNode(" · "));
        sum.append(document.createTextNode(`${LEVEL[lv].glyph} ${LEVEL[lv].label} `), el("b", null, String(c[i])));
      });
      sum.append(document.createTextNode(` (계 ${total})`));
      row.append(sum);
      bars.append(row);
    }
    {
      const tot = $("h-bars-total"), c = LEVELS.map((lv) => per.reduce((a, r) => a + r.c[LEVELS.indexOf(lv)], 0));
      tot.replaceChildren(document.createTextNode("합계 "));
      LEVELS.forEach((lv, j) => {
        if (j) tot.append(document.createTextNode(" · "));
        tot.append(document.createTextNode(`${LEVEL[lv].glyph} ${LEVEL[lv].label} `), el("b", null, String(c[j])));
      });
      tot.append(document.createTextNode(` (계 ${c[0] + c[1] + c[2]})`));
    }

    // 지점 목록 표
    renderHistoryHead();
    const col = H_COLS.find((c) => c.key === H.sort.key);
    const sorted = [...list].sort((a, b) => H.sort.dir * (H.sort.key === "level" ? -1 : 1) * col.cmp(a, b) || byIssueOrder(a, b));
    // 정상은 기본으로 접어 둔다 (판정 필터로 정상만 고르면 그대로 보인다)
    const fold = !H.showOk && H.level !== "ok", nOk = sorted.filter((e) => e.level === "ok").length;
    const rows = fold ? sorted.filter((e) => e.level !== "ok") : sorted;
    $("h-pts-count").textContent = rows.length === sorted.length ? `${sorted.length}개` : `${sorted.length}개 중 ${rows.length}개 표시`;
    const more = $("h-ok-toggle");
    more.hidden = !nOk || H.level === "ok";
    more.textContent = H.showOk ? `정상 ${nOk}건 접기` : `정상 ${nOk}건 보기`;
    more.setAttribute("aria-expanded", String(H.showOk));
    $("h-points").classList.toggle("clickable", newest);
    const body = $("h-points").tBodies[0];
    body.replaceChildren();
    const cell = (label, cls, ...kids) => { const td = el("td", cls); td.dataset.label = label; td.append(...kids); return td; };
    for (const e of rows) {
      const tr = el("tr");
      const kind = el("span", "kind"); kind.append(svgIcon(e.kind, e.level), el("span", null, KIND[e.kind].label));
      const target = pageFor(e);
      // 상세 페이지는 가장 최근 점검만: 지난 날짜는 이동 링크 없이 "—"
      const go = newest ? el("a", "go", `${PAGES[target].title} →`) : el("span", "tm", "—");
      if (newest) go.href = `#${target}/${e.id}`;
      const tm = el("span", null, fmtMDHMS(e.t));
      tm.title = `${fmtDateTimeS(e.t)} · ${e.id}`;
      tr.append(cell("판정", null, lvBadge(e.level)), cell("종류", null, kind), cell("값", "num", el("span", null, fmtValue(e))),
                cell("기준", "crit", el("span", null, criterion(e))), cell("측정 방식", null, el("span", null, SOURCE[e.source] || e.source)),
                cell("위도·경도", "ll", el("span", null, `${e.lat.toFixed(6)}, ${e.lon.toFixed(6)}`)),
                cell("시각", "tm", tm), cell("보기", null, go));
      if (newest) tr.addEventListener("click", (ev) => { if (!ev.target.closest("a")) go.click(); });
      tr.addEventListener("mouseenter", () => { tr.classList.add("hl"); setHover(e.id); });
      tr.addEventListener("mouseleave", () => { tr.classList.remove("hl"); setHover(null); });
      go.addEventListener("focus", () => setHover(e.id));
      go.addEventListener("blur", () => setHover(null));
      body.append(tr);
    }
    if (!rows.length) {
      const tr = el("tr"), td = el("td", "h-empty", sorted.length ? "위험·주의로 판정된 곳이 없습니다" : "조건에 맞는 지점이 없습니다");
      td.colSpan = H_COLS.length; tr.append(td); body.append(tr);
    }
    drawHMap();
  }
  renderHistory();

  function route() {
    const [rawPage, rawId] = location.hash.replace(/^#/, "").split("/");
    const page = Object.prototype.hasOwnProperty.call(PAGES, rawPage) ? rawPage : "home";
    let id = rawId && byId[rawId] ? rawId : null;
    if (page === "visual") {
      if (id && byId[id].kind === "loose") id = null;  // 흔들림은 외관 검사 대상이 아니다
      if (id) {
        // 고른 지점이 탭·필터에 걸려 안 보이면 보이게 맞춘다
        const e = byId[id];
        if (V.kind !== "all" && V.kind !== e.kind) V.kind = "all";
        if (e.level === "ok") V.withOk = true;
      } else {
        const first = visualShown()[0] || visualAll[0];  // 선택 없이 들어오면 목록 첫 지점
        if (first) { if (first.level === "ok") V.withOk = true; location.replace(`#visual/${first.id}`); return; }
      }
    }
    if (page === "physical" && !(id && byId[id].kind === "loose")) {
      if (physicalAll.length) { location.replace(`#physical/${physicalAll[0].id}`); return; }  // 선택 없이 들어오면 첫 지점
      id = null;
    }
    if (page === "history" && NEWEST && !DATE_BY[rawId]) { location.replace(`#history/${NEWEST}`); return; }
    const changed = page !== state.page;
    const fromOtherPage = !!state.page && state.page !== "home";  // 외관·물리적 안정성의 "지도에서 위치 보기"
    state.page = page;
    state.sel = id ? { id } : null;
    hideTip();
    hidePicker();
    for (const sec of document.querySelectorAll(".page")) sec.hidden = sec.dataset.page !== page;
    for (const a of document.querySelectorAll("#nav a")) {
      if (a.dataset.page === page) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    }
    document.title = `${PAGES[page].title} · StepMap${DATA.session ? ` · ${DATA.session}` : ""}`;
    if (page === "home") {
      // 다른 페이지에서 온 선택만 그 지점으로 확대한다. 지도에서 누른 선택·새로고침은 지도 범위를 그대로 둔다
      // (선택된 지점은 묶음에서 빠져 따로 그려지므로 전체 범위에서도 보인다)
      if (changed) state.spider = null;
      showMap();
      if (id && fromOtherPage && !state.pickedOnMap) focusOnMap(byId[id]);
      else if (id && !shown[byId[id].level]) setShown(byId[id].level, true);
      renderPanel();
      if (state.map) state.map.invalidateSize({ animate: false });  // 패널 높이·배치가 바뀌면 지도 크기를 다시 잰다
    }
    state.pickedOnMap = false;
    if (page === "visual") renderVisual();
    if (page === "physical") renderPhysical();
    if (page === "history") { H.date = rawId || NEWEST; closeCal(); renderHistory(); }
    if (changed) scrollTo(0, 0);
  }
  addEventListener("hashchange", route);
  route();
})();
</script>
</body>
</html>
"""
