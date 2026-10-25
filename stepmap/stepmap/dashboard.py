"""HTML 대시보드 생성 (계획서 8장).

하나의 HTML 안에서 왼쪽 사이드바로 4페이지를 전환한다
(주소 해시: #home/<id>, #detail/<id>, #history/<YYYY-MM-DD>. 예전 #visual/<id>, #physical/<id>는 #detail/<id>로 연다).
- 종합 현황: 화면 전체 지도 위에 유리 카드 (판정 필터·모양 범례, 화면 아래 블록 줄: 로봇 카드 + 지점을 누르면 사진·측정값/기준 대비·근거 블록)
- 검사 결과: 요약 한 줄(위험·주의·밟은 블록 수) + 지점 목록(탭: 전체/노면 형상/흔들림, 판정 칩) + 상세
  (공통: 사진·측정값·근거·위치·시각·방식, 노면 형상: 교차 측정, 흔들림: 발끝 높이 그래프·밟은 횟수·확정/의심) + 위치 지도
- 점검 이력: 점검 날짜 고르기(칩 + 달력), 그날의 KPI 4개(점검 거리·위험·주의·정상), 그날 지도(이동경로 + 100 m 눈금 +
  출발·도착 + 마커, 경로 켜고 끄기) + 종류별 판정 누적 막대, 지점 표(필터·정렬·이동, 정상은 접어 둠),
  현재 필터 결과 CSV 다운로드(events.csv와 같은 열·형식, BOM),
  같은 폴더의 report.html 열기. 지난 날짜는 events.csv 폴더의 history/<YYYY-MM-DD>/에서 읽는다
- 지도: 최대 확대에서도 묶인 마커는 누르면 부채꼴로 펼친다
- 위쪽 가운데 떠 있는 pill 메뉴(1259px 이하는 아래 탭바), 왼쪽 위 로고, 오른쪽 위 테마 전환·마지막 점검 날짜.
  라이트(차콜 강조) 기본, 다크(차콜 계열) 전환 가능. 글꼴: Inter Tight(영문·숫자) + Pretendard(한글)
- 배경: Leaflet + 벡터 지도(MapLibre GL, OpenFreeMap positron 색 덮어쓰기). 못 받으면 래스터(CARTO light_all →
  OpenTopoMap + 회색 필터) → odom 평면 지도. 지도 배경은 페이지 테마와 따로 고른다
  (밝은 지도 기본 / 어두운 지도: 반전 톤). 판정 색이 배경 도로 색과 섞이지 않게 하기 위함이다.
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

from .events import (BLOCK_SIZE_M, DEFAULT_THRESHOLDS, EVENT_COLUMNS, PATH_MIN_STEP_M, _fmt, block_index, count_stepped_blocks,
                     criterion_text, display_meters, exceed_ratio, extra_sink, group_foot_traces, loose_confirmation, path_length,
                     read_blocks, read_events, read_foot_traces, read_trajectory)
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

# 지도 타일: 밝은 회색 CARTO light_all을 먼저 쓰고, 못 받거나 대체 이미지면(키 없는 요청에 "API KEY REQUIRED"
# 워터마크를 줄 때가 있다) OpenTopoMap + 회색 필터, 그것도 안 되면 odom 평면 지도로 바꾼다.
# OSM 공식 타일 서버는 Referer 없는 요청(file://로 연 HTML)에 403 "Access blocked" 이미지를 주므로 쓰지 않는다.
TILE_URL = "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
TILE_SUBDOMAINS = "abcd"
TILE_MAX_NATIVE_ZOOM = 20  # 그 위는 확대 표시
TILE_ATTRIBUTION = ('&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors '
                    '&copy; <a href="https://carto.com/attributions">CARTO</a>')
TILE_FALLBACK_URL = "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png"
TILE_FALLBACK_SUBDOMAINS = "abc"
TILE_FALLBACK_MAX_NATIVE_ZOOM = 17
TILE_FALLBACK_ATTRIBUTION = ('&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, SRTM | '
                             '&copy; <a href="https://opentopomap.org">OpenTopoMap</a> '
                             '(<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA</a>)')
# 벡터 바탕 지도: Leaflet 위에 MapLibre GL(벡터 타일)을 깐다 (@maplibre/maplibre-gl-leaflet). 버전 고정 + SRI.
# maplibre-gl 6.x는 ES 모듈과 별도 워커 파일만 있어 file://로 연 HTML에서 쓸 수 없으므로 UMD가 있는 5.x 마지막 판을 쓴다.
MAPLIBRE_VERSION = "5.24.0"
MAPLIBRE_JS = f"https://unpkg.com/maplibre-gl@{MAPLIBRE_VERSION}/dist/maplibre-gl.js"
MAPLIBRE_JS_SRI = "sha384-5+cfbwT0iiub6VsQAdn6yz16nr6sDiQoHx6tm4O8OVYXHYOxcffFmCJBL0dgdvGp"
MAPLIBRE_CSS = f"https://unpkg.com/maplibre-gl@{MAPLIBRE_VERSION}/dist/maplibre-gl.css"
MAPLIBRE_CSS_SRI = "sha384-uTttxo/aOKbdE5RlD/SPzSDoDmNvGlUYPjONi2MN/b7c9HPSvW07OIuyP7uL6jxK"
MAPLIBRE_LEAFLET_VERSION = "0.1.4"
MAPLIBRE_LEAFLET_JS = f"https://unpkg.com/@maplibre/maplibre-gl-leaflet@{MAPLIBRE_LEAFLET_VERSION}/leaflet-maplibre-gl.js"
MAPLIBRE_LEAFLET_JS_SRI = "sha384-tXYNKOHx4T02jMP7YYCtBxPIv1B5gaA5mcVPBzqMp6d7VzWzxJgI2aWF/nJLrQdS"
# OpenFreeMap (키 없음) positron 스타일을 받아 아래 색으로 덮어쓴다 (dashboard JS recolorStyle)
VECTOR_STYLE_URL = "https://tiles.openfreemap.org/styles/positron"
VECTOR_ATTRIBUTION = ('&copy; <a href="https://openfreemap.org">OpenFreeMap</a> &copy; <a href="https://www.openmaptiles.org/">OpenMapTiles</a> '
                      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors')
VECTOR_PALETTE = {
    # 땅·배경, 건물(아주 옅게), 도로(모든 등급) · 도로 테두리, 공원·녹지, 숲·잔디(+투명도), 물, 지명 글자
    "light": {"land": "#EDEDED", "building": "#E4E4E4", "road": "#FFFFFF", "casing": "#E2E2E2", "park": "#BFEBD6",
              "wood": "#A5D48C", "wood_opacity": 0.7, "water": "#D3E2E4", "label": "#A09CA2"},
    "dark": {"land": "#1F1C1F", "building": "#262226", "road": "#3A363A", "casing": "#2E2A2E", "park": "#2C3B33",
             "wood": "#2C3B33", "wood_opacity": 0.7, "water": "#26303A", "label": "#A09CA2"},
}
# 영문·숫자 글꼴 Inter Tight (Google Fonts 400/500/600). 한글은 Pretendard, 인터넷이 없으면 시스템 글꼴
INTER_CSS = "https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600&display=swap"

_EVENT_FIELDS = ["id", "t", "x", "y", "kind", "value", "unit", "source", "leg", "confidence",
                 "level", "note", "value_foot", "lat", "lon"]


class MissingLatLon(ValueError):
    pass


REPORT_NAME = "report.html"  # stepmap report 기본 출력 이름
ROBOT_PHOTO = "robot.png"    # 종합 현황 로봇 카드 사진 (events.csv와 같은 폴더). 없으면 직접 그린 로봇개 그림
ROBOT_SENSORS = ("LiDAR", "깊이 카메라", "발 접촉")  # config.yaml robot.sensors 기본값
HISTORY_DIR = "history"      # 지난 점검: <events.csv 폴더>/history/<YYYY-MM-DD>/events.csv, trajectory.csv
ROUTE_TICK_M = 100           # 점검 이력 지도: 경로를 따라 이 간격마다 누적 거리 눈금
KST = timezone(timedelta(hours=9))
WEEKDAYS = "월화수목금토일"
NEAR_VISUAL_M = 1.0  # 흔들림 상세의 "주변 노면 형상" 비교 반경


def near_visual_issues(e: dict, events: list[dict], radius: float = NEAR_VISUAL_M) -> list[str]:
    """흔들림 지점 radius m 안의 노면 형상 이상(단차·경사·균열의 위험·주의) 지점 id, 가까운 순."""
    near = [(math.hypot(o["x"] - e["x"], o["y"] - e["y"]), o["id"]) for o in events
            if o["kind"] != "loose" and o["level"] != "ok"]
    return [i for d, i in sorted(near) if d <= radius + 1e-9]


def trace_payload(trace: dict | None) -> dict | None:
    """걸음 하나의 발끝 기록 + 추가 침하 계산 결과 (그래프와 값 상자가 쓰는 값)."""
    if not trace:
        return None
    r = extra_sink(trace)
    return {"leg": trace["leg"], "n": trace["n_normal"], "t": trace["t"], "step": trace["z_step"],
            "mean": trace["z_mean"], "lo": trace["z_lo"], "hi": trace["z_hi"],
            "extra": round(r["extra_mm"], 2), "contact": round(r["contact_diff_mm"], 2),
            "t_settle": r["t_settle_step"]}


def _battery(v) -> int | None:
    """config robot.battery (0~100 %). 비었거나 숫자가 아니면 None (로봇 카드의 배터리 줄을 숨긴다)."""
    try:
        return max(0, min(100, round(float(v))))
    except (TypeError, ValueError):
        return None


def build_payload(events: list[dict], traj: list[dict], thresholds: dict | None = None,
                  photos: dict | None = None, meta: dict | None = None, traces: dict | None = None,
                  report_href: str | None = None, history: list[tuple[list[dict], list[dict]]] | None = None,
                  stepped_blocks: int | None = None, blocks: dict | None = None) -> dict:
    """photos: prepare_photos 결과 {id: {src, w, h, mark, overlay}}. 사진이 없는 지점은 photo=None.
    meta: 세션 정보 {"area": 구간, "robot": 로봇 이름, "model": 모델, "sensors": [센서], "robot_photo": 사진 상대 경로}
          (config.yaml의 report.area, robot.name·model·sensors. robot_photo는 write_dashboard가 채운다).
    report_href: 점검 이력의 "신고서 열기" 주소 (없으면 버튼을 숨긴다).
    각 지점의 csv: events.csv에 쓰는 것과 같은 형식의 칸 문자열 (점검 이력 CSV 다운로드가 그대로 이어 붙인다).
    history: 지난 점검 [(events, trajectory)] (점검 이력 페이지만 쓴다). 가장 최근 날짜와 같은 날은 건너뛴다.
    stepped_blocks: 발로 밟아 확인한 블록 수 (events.count_stepped_blocks, blocks.csv·발끝 기록이 모두 없으면 None).
    blocks: 위치 지도에 그릴 밟은 블록 칸 (blocks_payload)."""
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
        # 로봇 카드: 모델(config robot.model, 없으면 이름), 센서(robot.sensors), 사진(<HTML 폴더>/photos/robot.png 사본)
        "robot_model": (meta or {}).get("model") or (meta or {}).get("robot") or "",
        "robot_sensors": list((meta or {}).get("sensors") or ROBOT_SENSORS),
        "robot_photo": (meta or {}).get("robot_photo"),
        "robot_battery": _battery((meta or {}).get("battery")),  # config robot.battery (%), 없으면 None → 줄 숨김
        # 국토교통부 VWorld 인증키 (config map.vworld_key 또는 환경변수 STEPMAP_VWORLD_KEY). 있으면 한국 지도·위성 지도
        "vworld_key": (meta or {}).get("vworld_key") or "",
        "meters": display_meters(path_length(traj)),  # 로봇 카드 이동 거리 (신고서와 같은 반올림)
        "distance_m": path_length(traj),  # 1m 미만 흔들림은 거른다. 반올림은 화면에서 한 번만
        "thresholds": {k: list(v) for k, v in th.items()},
        "trajectory": [[round(p["lat"], 7), round(p["lon"], 7)] for p in traj],
        "trajectory_xy": [[round(p["x"], 2), round(p["y"], 2)] for p in traj],
        "report": report_href,
        "stepped_blocks": stepped_blocks,
        "home": home_cards(events, th),
        "blocks": blocks,
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
    """지점 하나의 화면용 값. events: 같은 날 지점 전체 (흔들림의 주변 노면 형상 비교용)."""
    return {**{k: e[k] for k in _EVENT_FIELDS}, "session": e["session"],
            "csv": [_fmt(c, e.get(c)) for c in EVENT_COLUMNS],
            "criterion": criterion_text(e["kind"], e["level"], th),
            "ratio": round(exceed_ratio(e["kind"], e["level"], e["value"], th), 4),  # 신고서와 같은 정렬 기준
            "photo": (photos or {}).get(e["id"]),
            **(loose_payload(e, events, th, (traces or {}).get(e["id"])) if e["kind"] == "loose" else {})}


def loose_payload(e: dict, events: list[dict], th: dict, steps: list[dict] | None) -> dict:
    """흔들림 지점의 상세 값. trace: 그래프에 그리는 첫 걸음(지점의 다리·시각, 추가 침하 = value),
    steps: 같은 블록을 밟은 걸음들 {leg, t_event, extra}, confirm: "확정"/"의심"/None (events.loose_confirmation).
    발끝 기록이 없으면 지점 자체(한 걸음)로 판정한다."""
    steps = steps or []
    first = next((s for s in steps if s["leg"] == e["leg"]), steps[0] if steps else None)
    extras = [extra_sink(s)["extra_mm"] for s in steps]
    return {"trace": trace_payload(first),
            "steps": [{"leg": s["leg"], "t_event": s["t_event"], "extra": round(x, 2)} for s, x in zip(steps, extras)],
            "confirm": loose_confirmation(extras or [e["value"]], th),
            "near_visual": near_visual_issues(e, events)}


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


def blocks_payload(blocks: list[dict] | None, size: float = BLOCK_SIZE_M) -> dict | None:
    """검사 결과 위치 지도의 밟은 블록 칸: 격자 칸 번호 ij와 크기, 칸 모서리(odom x·y)를 위도·경도로 바꾸는 식.
    geo: lat = a0 + a1·x + a2·y, lon = b0 + b1·x + b2·y — blocks.csv의 칸 가운데(x, y, lat, lon)에 최소제곱으로 맞춘다
    (출발점 기준 평면 근사라 1~2 km 안에서는 1차식으로 충분). 위도·경도가 없으면 geo 없이 평면 지도에만 그린다."""
    if not blocks:
        return None
    pts = [b for b in blocks if b["lat"] is not None]
    return {"size": size, "ij": [list(block_index(b["x"], b["y"], size)) for b in blocks],
            "geo": _fit_affine(pts, "lat") + _fit_affine(pts, "lon") if len(pts) >= 3 else None}


def _fit_affine(pts: list[dict], key: str) -> list[float]:
    """key ≈ c0 + c1·x + c2·y 최소제곱 (정규방정식 3×3, 크라머 공식). x·y는 평균을 빼서 수치 오차를 줄인다."""
    mx, my = sum(p["x"] for p in pts) / len(pts), sum(p["y"] for p in pts) / len(pts)
    rows = [(1.0, p["x"] - mx, p["y"] - my, p[key]) for p in pts]
    a = [[sum(r[i] * r[j] for r in rows) for j in range(3)] for i in range(3)]
    v = [sum(r[i] * r[3] for r in rows) for i in range(3)]

    def det(m):
        return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
    d = det(a)
    c = [det([[v[r] if col == k else a[r][col] for col in range(3)] for r in range(3)]) / d for k in range(3)]
    return [c[0] - c[1] * mx - c[2] * my, c[1], c[2]]


def home_cards(events: list[dict], th: dict) -> dict:
    """종합 현황 손상 정보 카드.
    order: 위험→주의, 같은 판정은 exceed_ratio 큰 순(같으면 이른 시각). 카드의 "다음" 두 줄은 이 순서로 지금 지점 다음.
    default: 로봇이 가장 최근에 찾은 위험 지점 (위험이 없으면 주의, 둘 다 없으면 None). 아무것도 고르지 않았을 때 카드 내용."""
    rank = {"danger": 2, "warn": 1}
    issues = sorted((e for e in events if e["level"] in rank),
                    key=lambda e: (-rank[e["level"]], -exceed_ratio(e["kind"], e["level"], e["value"], th), e["t"]))
    default = next((max(c, key=lambda e: e["t"])["id"] for lv in ("danger", "warn")
                    if (c := [e for e in events if e["level"] == lv])), None)
    return {"order": [e["id"] for e in issues], "default": default}


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
               report_href: str | None = None, history: list[tuple[list[dict], list[dict]]] | None = None,
               stepped_blocks: int | None = None, blocks: dict | None = None) -> str:
    payload = build_payload(events, traj, thresholds, photos, meta, traces, report_href, history, stepped_blocks, blocks)
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
            .replace("__INTER_CSS__", INTER_CSS)
            .replace("__MAPLIBRE_JS_SRI__", MAPLIBRE_JS_SRI)
            .replace("__MAPLIBRE_JS__", MAPLIBRE_JS)
            .replace("__MAPLIBRE_CSS_SRI__", MAPLIBRE_CSS_SRI)
            .replace("__MAPLIBRE_CSS__", MAPLIBRE_CSS)
            .replace("__MAPLIBRE_LEAFLET_JS_SRI__", MAPLIBRE_LEAFLET_JS_SRI)
            .replace("__MAPLIBRE_LEAFLET_JS__", MAPLIBRE_LEAFLET_JS)
            .replace("__VECTOR_STYLE__", VECTOR_STYLE_URL)
            .replace("__VECTOR_ATTRIBUTION__", VECTOR_ATTRIBUTION)
            .replace("__MAP_COLORS__", json.dumps(VECTOR_PALETTE))
            .replace("__TILE_FALLBACK_URL__", TILE_FALLBACK_URL)
            .replace("__TILE_FALLBACK_SUBDOMAINS__", TILE_FALLBACK_SUBDOMAINS)
            .replace("__TILE_FALLBACK_MAX_NATIVE_ZOOM__", str(TILE_FALLBACK_MAX_NATIVE_ZOOM))
            .replace("__TILE_FALLBACK_ATTRIBUTION__", TILE_FALLBACK_ATTRIBUTION)
            .replace("__TILE_URL__", TILE_URL)
            .replace("__TILE_SUBDOMAINS__", TILE_SUBDOMAINS)
            .replace("__TILE_MAX_NATIVE_ZOOM__", str(TILE_MAX_NATIVE_ZOOM))
            .replace("__TILE_ATTRIBUTION__", TILE_ATTRIBUTION)
            .replace("__LEVEL_FILTER__", level_filter_html(events))
            .replace("__DATE_CHIPS__", date_chips_html(payload["dates"], events))
            .replace("__DATA__", data))


def copy_robot_photo(src: Path, out_dir: Path, max_side: int = 640) -> str | None:
    """로봇 사진을 현장 사진처럼 <HTML 폴더>/photos/robot.png로 복사한다 (긴 변 max_side 이하, 투명 배경 유지).
    돌려주는 값: HTML 기준 상대 경로. 사진이 없거나 읽을 수 없거나 투명한 곳이 없는(배경이 있는) 그림이면 None
    (화면은 직접 그린 그림으로 대체, 지난번 사본은 지운다)."""
    from PIL import Image, UnidentifiedImageError

    from .photos import PHOTO_DIR
    dst = out_dir / PHOTO_DIR / ROBOT_PHOTO
    if not src.is_file():
        return None
    try:
        with Image.open(src) as im:
            im = im.convert("RGBA")
            if im.getchannel("A").getextrema()[0] == 255:  # 투명 배경이 아니다 (카드 캡처 등)
                dst.unlink(missing_ok=True)
                return None
            im = im.crop(im.getchannel("A").getbbox())  # 투명 여백을 잘라 로봇이 칸을 채우게
            im.thumbnail((max_side, max_side))
            (out_dir / PHOTO_DIR).mkdir(parents=True, exist_ok=True)
            im.save(dst, "PNG", optimize=True)
    except (OSError, UnidentifiedImageError):
        return None
    return f"{PHOTO_DIR}/{ROBOT_PHOTO}"


def write_dashboard(events_path: str | Path, traj_path: str | Path, out_path: str | Path,
                    thresholds: dict | None = None, meta: dict | None = None,
                    traces_path: str | Path | None = None, history_dir: str | Path | None = None,
                    blocks_path: str | Path | None = None, block_size: float = BLOCK_SIZE_M) -> Path:
    """traces_path: 발끝 기록 (기본: events.csv와 같은 폴더의 foot_traces.csv). 없으면 그래프 자리에 "발끝 기록 없음".
    history_dir: 지난 점검 폴더 (기본: events.csv와 같은 폴더의 history/). 없으면 점검 이력에 가장 최근 날짜만.
    blocks_path: 밟은 블록 요약 (기본: events.csv와 같은 폴더의 blocks.csv). 없으면 밟은 블록 수는 발끝 기록 기준.
    block_size: blocks.csv를 만든 격자 크기 (config.yaml block.size_m).
    같은 폴더에 report.html이 있으면 점검 이력에 "신고서 열기" 버튼을 넣는다 (file://로 연 HTML은 옆 파일이
    있는지 브라우저가 확인할 수 없어서 만들 때 확인한다. 신고서를 나중에 만들었다면 map을 다시 실행)."""
    events = read_events(events_path)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    photos = prepare_photos(events, Path(events_path).parent, out.parent)  # 사본: <HTML 폴더>/photos/
    traces_path = Path(traces_path) if traces_path else Path(events_path).parent / "foot_traces.csv"
    trace_rows = read_foot_traces(traces_path) if traces_path.is_file() else []
    traces = group_foot_traces(trace_rows)
    report_href = REPORT_NAME if (out.parent / REPORT_NAME).is_file() else None
    meta = {**(meta or {}), "robot_photo": copy_robot_photo(Path(events_path).parent / ROBOT_PHOTO, out.parent)}
    history = read_history(history_dir if history_dir else Path(events_path).parent / HISTORY_DIR)
    blocks_path = Path(blocks_path) if blocks_path else Path(events_path).parent / "blocks.csv"
    blocks = read_blocks(blocks_path) if blocks_path.is_file() else None
    stepped = count_stepped_blocks(blocks, trace_rows) if blocks is not None or trace_rows else None
    traj = read_trajectory(traj_path)
    page = build_html(events, traj, thresholds, photos, meta, traces, report_href, history,
                      stepped, blocks_payload(blocks, block_size))
    out.write_text(page, encoding="utf-8")
    if meta.get("vworld_key"):  # VWorld 3D 지도 (대시보드의 '3D 지도' 버튼이 띄운다)
        from .map3d import MAP3D_NAME, build_map3d_html
        (out.parent / MAP3D_NAME).write_text(build_map3d_html(events, traj, meta["vworld_key"]), encoding="utf-8")
    return out


_TEMPLATE = r"""<!doctype html>
<html lang="ko" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link rel="stylesheet" href="__LEAFLET_CSS__" integrity="__LEAFLET_CSS_SRI__" crossorigin="">
<link rel="stylesheet" href="__MAPLIBRE_CSS__" integrity="__MAPLIBRE_CSS_SRI__" crossorigin="anonymous">
<link rel="stylesheet" href="__FONT_CSS__" integrity="__FONT_CSS_SRI__" crossorigin="anonymous" media="print" onload="this.media='all'">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="__INTER_CSS__" media="print" onload="this.media='all'">
<style>
  /* ---------- 색 토큰: 라이트 (기본) ----------
     브랜드·선택 = 차콜 #363236 (선택된 메뉴·주 버튼·탭·칩·날짜: 차콜 배경 + 흰 글자).
     등급 색(--danger·--warn·--ok)은 마커·배지 바탕·그래프·KPI 아이콘에만 쓰고, 글자에는 진한 변형(--*-ink)을 쓴다.
     -ink는 흰 카드·배경(#EDEDED)·배지 바탕(등급 색 20%) 모두에서 4.5:1 이상. 등급 색 바탕 위 글자는 --on-grade */
  :root {
    color-scheme: light;
    --font: "Inter Tight", "Pretendard Variable", Pretendard, system-ui, -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo",
            "Malgun Gothic", "Noto Sans KR", sans-serif;
    --bg: #EDEDED; --surface: #FFFFFF; --surface-2: #F9F8FA;
    --border: #E4E2E6; --border-hi: #363236; --head-bg: rgb(237 237 237 / 0.86);
    --text: #363236; --muted: #75707A; --muted-strong: #68636C;  /* muted-strong: 배경(#EDEDED) 위 보조 글자 */
    --accent: #363236; --on-accent: #FFFFFF; --focus: #363236;
    --grid: #E4E2E6;
    --danger: #EF6461; --warn: #F7B558; --ok: #A5D48C;
    --danger-ink: #B4232A; --warn-ink: #935600; --ok-ink: #367324; --on-grade: #1F1C1F;
    --shadow: 0 1px 2px rgb(54 50 54 / 0.06), 0 8px 24px rgb(54 50 54 / 0.06);
    --shadow-pop: 0 2px 6px rgb(54 50 54 / 0.12), 0 12px 32px rgb(54 50 54 / 0.16);
    --band: #E4E2E6; --mean: #75707A; --step: #EF6461;
    --radius: 18px; --topbar-h: 72px;
    --fs-title: 24px; --fs-h2: 16px; --fs-body: 14px; --fs-small: 12.5px; --fs-xs: 11.5px;
  }
  /* ---------- 다크: 차콜 계열 ---------- */
  :root[data-theme="dark"] {
    color-scheme: dark;
    --bg: #1F1C1F; --surface: #2A262A; --surface-2: #332E33;
    --border: #3D383D; --border-hi: #F2F0F2; --head-bg: rgb(31 28 31 / 0.86);
    --text: #F2F0F2; --muted: #ADA7B0; --muted-strong: #ADA7B0;
    --accent: #F2F0F2; --on-accent: #1F1C1F; --focus: #F2F0F2;
    --grid: #3D383D;
    --danger-ink: #F58A86; --warn-ink: #F7B558; --ok-ink: #A5D48C;
    --shadow: 0 1px 2px rgb(0 0 0 / 0.3), 0 8px 24px rgb(0 0 0 / 0.24);
    --shadow-pop: 0 2px 6px rgb(0 0 0 / 0.36), 0 12px 32px rgb(0 0 0 / 0.42);
    --band: #3D383D; --mean: #D9D5DA; --step: #F58A86;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; background: var(--bg); color: var(--text); font: var(--fs-body)/1.55 var(--font);
               -webkit-font-smoothing: antialiased; }
  button { font: inherit; color: inherit; }
  :focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
  h1 { font-size: var(--fs-title); font-weight: 600; letter-spacing: -0.02em; margin: 0; }
  h2 { font-size: var(--fs-h2); font-weight: 600; letter-spacing: -0.01em; margin: 0 0 12px; }
  a { color: var(--accent); text-underline-offset: 2px; }

  /* ---------- 뼈대: 위쪽 바(로고 · 가운데 떠 있는 pill 메뉴 · 테마 전환·마지막 점검) + 본문 ---------- */
  .app { min-height: 100vh; }
  .topbar { position: sticky; top: 0; z-index: 900; display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); align-items: center;
            gap: 12px; height: var(--topbar-h); padding: 0 28px; background: var(--head-bg);
            -webkit-backdrop-filter: blur(12px) saturate(1.2); backdrop-filter: blur(12px) saturate(1.2); }
  .logo { justify-self: start; display: inline-flex; align-items: center; gap: 10px; color: var(--text); text-decoration: none;
          font-size: 18px; font-weight: 600; letter-spacing: -0.02em; }
  .logo-mark { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 9px; background: var(--accent); color: var(--on-accent); }
  .logo-mark svg { width: 18px; height: 18px; }
  .nav { display: flex; gap: 4px; padding: 5px; border-radius: 999px; background: var(--surface); box-shadow: var(--shadow); }
  .nav a { display: inline-flex; align-items: center; gap: 8px; padding: 9px 18px 9px 14px; border-radius: 999px; color: var(--muted);
           text-decoration: none; font-weight: 600; white-space: nowrap; transition: background 0.15s, color 0.15s; }
  .nav a:hover { background: var(--surface-2); color: var(--text); }
  .nav a[aria-current="page"] { background: var(--accent); color: var(--on-accent); }
  .nav svg { width: 18px; height: 18px; flex: none; }
  .nav .short { display: none; }
  .tb-right { justify-self: end; display: flex; align-items: center; gap: 12px; min-width: 0; }
  .tb-date { min-width: 0; color: var(--muted-strong); font-size: var(--fs-small); font-variant-numeric: tabular-nums; white-space: nowrap;
             overflow: hidden; text-overflow: ellipsis; }
  .tb-date b { color: var(--text); font-weight: 600; }
  /* 아이콘 버튼: 36px 흰 원 */
  .icon-btn, .h-cal-btn { display: grid; place-items: center; flex: none; width: 36px; height: 36px; padding: 0; border: 0;
                                     border-radius: 50%; background: var(--surface); color: var(--text); box-shadow: var(--shadow); cursor: pointer; }
  .icon-btn:hover, .h-cal-btn:hover { background: var(--surface-2); }
  .icon-btn svg { width: 18px; height: 18px; }
  .main { min-width: 0; padding: 0 28px 48px; }
  /* 1259px 이하: 메뉴는 화면 아래 고정 탭바 */
  @media (max-width: 1259px) {
    /* 흐림(backdrop-filter)이 있으면 그 안의 fixed 요소가 위쪽 바 기준으로 놓이므로 끈다 (탭바를 화면 아래에 고정) */
    .topbar { grid-template-columns: minmax(0, 1fr) auto; background: var(--bg); -webkit-backdrop-filter: none; backdrop-filter: none; }
    .nav { position: fixed; left: 0; right: 0; bottom: 0; z-index: 950; justify-content: space-around; gap: 2px; border-radius: 18px 18px 0 0;
           padding: 6px 8px calc(6px + env(safe-area-inset-bottom)); box-shadow: 0 -1px 2px rgb(54 50 54 / 0.06), 0 -8px 24px rgb(54 50 54 / 0.08); }
    .nav a { flex: 1 1 0; flex-direction: column; justify-content: center; gap: 3px; padding: 8px 4px; font-size: 12px; }
    .main { padding-bottom: 96px; }
  }
  /* 제목줄: 한 줄로 얇게 (제목 + 오른쪽에 세션·구간·시각). 위쪽 바가 붙어 있으므로 제목줄은 함께 스크롤된다 */
  .page-head { display: flex; flex-wrap: wrap; align-items: baseline; column-gap: 16px; row-gap: 2px; padding: 4px 0 0; }
  .page-head h1 { flex: none; font-size: 22px; line-height: 1.3; }
  .page-head .sub { flex: 1 1 0; min-width: 0; margin: 0; color: var(--muted-strong); font-size: var(--fs-small); text-align: right;
                    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

  /* ---------- 판정 배지: 옅은 배경 + 진한 글자 + 기호 ---------- */
  .lv { display: inline-flex; align-items: center; gap: 4px; padding: 2px 9px 2px 7px; border-radius: 999px;
        background: color-mix(in srgb, var(--c) 20%, var(--surface)); color: var(--ink); font-size: var(--fs-small);
        font-weight: 600; line-height: 1.45; white-space: nowrap; }
  .lv .sw { min-width: 11px; text-align: center; font-size: var(--fs-xs); font-weight: 600; }
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
             background: color-mix(in srgb, var(--c, var(--accent)) 20%, transparent); color: var(--c, var(--accent)); }
  .kpi-ico svg { width: 18px; height: 18px; }
  .kpi-ico.ok { --c: var(--ok); } .kpi-ico.warn { --c: var(--warn); } .kpi-ico.danger { --c: var(--danger); }
  .kpi .label { grid-column: 2 / 4; min-width: 0; color: var(--muted); font-size: var(--fs-small); font-weight: 600; line-height: 1.35;
                white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .kpi .label small { margin-left: 4px; font-size: var(--fs-xs); font-weight: 500; }
  /* 큰 숫자: Inter Tight 500, 자간 -0.02em. 단위는 작게 보조 글자색 */
  .kpi .value { grid-column: 2; font-size: 30px; font-weight: 500; line-height: 1.1; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .kpi .value small { font-size: 14px; font-weight: 500; color: var(--muted); margin-left: 2px; letter-spacing: 0; }
  .kpi .sub { grid-column: 3; display: flex; flex-wrap: wrap; align-items: center; gap: 3px 8px; min-width: 0; padding-left: 4px;
              color: var(--muted); font-size: var(--fs-xs); line-height: 1.3; word-break: keep-all; }
  .kpi .sub > span { display: inline-flex; align-items: center; gap: 3px; color: var(--text); font-variant-numeric: tabular-nums; white-space: nowrap; }
  .kpi .sub .lv { padding: 0 6px 0 5px; font-size: var(--fs-xs); line-height: 1.4; }

  /* ---------- 지도 색 (종합 현황·점검 이력·검사 결과 위치 지도 공통) ---------- */
  .mapcard { min-width: 0; }
  /* 지도 배경은 페이지 테마와 따로 고른다 (밝은 지도 기본). 경로·마커·조작 버튼 색도 지도 배경에 맞춘다 */
  /* 밟은 지도(기본): CARTO light_all 그대로 (못 받아 OpenTopoMap이면 회색 필터). 평면 지도: #ECECEC 바탕, 흰 길(격자)
     마커: 등급 색 + 흰 테두리 2px + 옅은 그림자. 묶음: 흰 원 + 차콜 숫자 + 가장 높은 등급 색 테두리 */
  .mapcard[data-map="light"] {
    --map-bg: #EDEDED; --tile-filter: none; --tile-opacity: 1; --link: #363236;
    --map-grid: #FFFFFF; --map-park: #BFEBD6; --map-text: #363236; --map-leader: #363236;
    --m-danger: #EF6461; --m-warn: #F7B558; --m-ok: #A5D48C; --m-ink: #363236; --m-ring: #FFFFFF; --m-focus: #363236;
    --m-shadow: drop-shadow(0 1px 1.5px rgb(54 50 54 / 0.35));
    --ctl-bg: #FFFFFF; --ctl-hover: #F9F8FA; --ctl-text: #363236; --ctl-muted: #75707A; --ctl-border: #E4E2E6; --ctl-link: #363236;
    --ctl-on: #363236; --ctl-on-text: #FFFFFF; --ctl-shadow: 0 1px 2px rgb(54 50 54 / 0.1), 0 4px 12px rgb(54 50 54 / 0.1);
  }
  :root[data-tiles="topo"] .mapcard[data-map="light"] { --tile-filter: grayscale(1) contrast(0.85) brightness(1.05); --tile-opacity: 0.55; }
  :root[data-tiles="vworld"] .mapcard[data-map="light"] { --tile-filter: grayscale(1) contrast(0.8) brightness(1.1); --tile-opacity: 0.6; }
  /* 위성 지도는 타일 칸 밖(sat 칸)에 그려 회색 필터를 받지 않는다 */
  :root[data-tiles="vector"] .mapcard[data-map] { --tile-filter: none; --tile-opacity: 1; }  /* 벡터 지도는 어두운 지도도 스타일 색으로 */
  .mapcard[data-map="dark"] {
    --map-bg: #1F1C1F; --tile-filter: grayscale(1) invert(1) brightness(0.85) contrast(0.9);
    --tile-opacity: 1;
    --map-grid: #3A363A; --map-park: #2C3B33; --map-text: #F2F0F2; --map-leader: #F2F0F2; --link: #F2F0F2;
    --m-danger: #EF6461; --m-warn: #F7B558; --m-ok: #A5D48C; --m-ink: #363236; --m-ring: #1F1C1F; --m-focus: #F2F0F2;
    --m-shadow: drop-shadow(0 1px 1.5px rgb(0 0 0 / 0.5));
    --ctl-bg: #2A262A; --ctl-hover: #332E33; --ctl-text: #F2F0F2; --ctl-muted: #ADA7B0; --ctl-border: #3D383D; --ctl-link: #F2F0F2;
    --ctl-on: #F2F0F2; --ctl-on-text: #1F1C1F; --ctl-shadow: 0 1px 2px rgb(0 0 0 / 0.3), 0 4px 12px rgb(0 0 0 / 0.3);
  }
  .mapbox { position: relative; isolation: isolate; overflow: hidden; background: var(--map-bg); }
  #map, #plane { position: absolute; inset: 0; }
  :is(#map, #h-map, #d-map).leaflet-container { background: var(--map-bg); font: var(--fs-small) var(--font); }
  :is(#map, #h-map, #d-map) .leaflet-tile-pane { filter: var(--tile-filter); opacity: var(--tile-opacity); }
  :is(#map, #h-map, #d-map) .leaflet-bar { border: 1px solid var(--ctl-border); border-radius: 10px; overflow: hidden; box-shadow: var(--ctl-shadow); }
  :is(#map, #h-map, #d-map) .leaflet-bar a { width: 32px; height: 32px; line-height: 32px; background: var(--ctl-bg); color: var(--ctl-text); border-bottom: 1px solid var(--ctl-border); }
  :is(#map, #h-map, #d-map) .leaflet-bar a:hover { background: var(--ctl-hover); }
  :is(#map, #h-map, #d-map) .leaflet-bar a.leaflet-disabled { color: var(--ctl-muted); background: var(--ctl-bg); opacity: 0.6; }
  :is(#map, #h-map, #d-map) .leaflet-control-attribution { padding: 2px 8px; border-radius: 10px 0 0 0; color: var(--ctl-muted);
                                      background: color-mix(in srgb, var(--ctl-bg) 90%, transparent); }
  :is(#map, #h-map, #d-map) .leaflet-control-attribution a { color: var(--ctl-link); }
  /* 종합 현황 저작자 표시: 지도 밖 #map-attr로 옮겨 블록 줄보다 위 레이어에 한 줄로 (11px, 반투명 흰 배경) */
  .map-attr .leaflet-control-attribution { float: none; display: block; max-width: 100%; margin: 0; padding: 1px 6px; border-radius: 6px; background: rgb(255 255 255 / 0.86); color: #55505A;
                                           font-size: 11px; line-height: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .map-attr .leaflet-control-attribution a { color: #363236; text-decoration: none; }
  .map-attr .leaflet-control-attribution a:hover { text-decoration: underline; }
  .map-tools { position: absolute; top: 12px; right: 12px; z-index: 600; display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
  #plane svg { display: block; width: 100%; height: 100%; }
  .ev-marker, .ev-cluster { background: none; border: none; }
  .ev-marker svg, .ev-cluster svg { display: block; overflow: visible; filter: var(--m-shadow, none); }
  :is(#plane, #h-plane, #d-plane) .ev { filter: var(--m-shadow, none); }
  .ev-marker:focus-visible, .ev-cluster:focus-visible { outline: 2px solid var(--m-focus); outline-offset: 1px; border-radius: 50%; }
  #plane .ev { cursor: pointer; }
  #plane .ev:focus { outline: none; }
  #plane .ev:focus-visible .hit { stroke: var(--m-focus); stroke-width: 2; }
  .retry { padding: 6px 12px; font-size: var(--fs-small); font-weight: 600; border-radius: 10px;
           border: 1px solid var(--ctl-border); background: var(--ctl-bg); color: var(--ctl-text); cursor: pointer; box-shadow: var(--ctl-shadow); }
  .retry:hover { background: var(--ctl-hover); }
  .legend .item { display: inline-flex; align-items: center; gap: 6px; color: var(--text); }
  /* 모양 범례: 회색 (판정 색 필터 버튼과 헷갈리지 않게 색을 쓰지 않는다) */
  .shape-legend { display: inline-flex; flex-wrap: wrap; align-items: center; gap: 6px 14px; }
  .shape-legend .shp { width: 14px; height: 14px; flex: none; fill: var(--muted); }
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
  .lv-btn[aria-pressed="true"] { background: var(--accent); border-color: var(--accent); color: var(--on-accent); }
  .lv-btn[aria-pressed="true"] .dot { box-shadow: 0 0 0 1.5px var(--on-accent); }
  .lv-btn[aria-pressed="true"] .dot { opacity: 1; }
  .map-empty { position: absolute; left: 50%; top: 50%; z-index: 550; transform: translate(-50%, -50%); padding: 10px 16px;
               border: 1px solid var(--ctl-border); border-radius: 12px; background: var(--ctl-bg); color: var(--ctl-text);
               font-weight: 600; box-shadow: var(--ctl-shadow); pointer-events: none; white-space: nowrap; }
  .map-empty[hidden] { display: none; }

  /* ---------- 검사 결과 (노면 형상 + 흔들림): 요약 한 줄 + 왼쪽 목록(360px) + 오른쪽 상세 ---------- */
  .d-summary { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 14px; margin: 16px 0; padding: 12px 16px;
               background: var(--surface); border: 1px solid var(--border); border-radius: 12px; font-weight: 600;
               font-variant-numeric: tabular-nums; }
  .d-summary .sep { width: 1px; height: 16px; background: var(--border); }
  .d-summary .blk { display: inline-flex; align-items: center; gap: 6px; }
  .d-grid { display: grid; grid-template-columns: 360px minmax(0, 1fr); gap: 16px; align-items: start; }
  @media (max-width: 1259px) { .d-grid { grid-template-columns: minmax(0, 1fr); } }
  .d-left { display: grid; gap: 10px; min-width: 0; }
  .tabs { display: flex; flex-wrap: wrap; gap: 4px; padding: 4px; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; }
  .tabs button { display: inline-flex; flex: 1 1 auto; justify-content: center; align-items: center; gap: 6px; padding: 7px 10px; border: 0;
                 border-radius: 8px; background: none; color: var(--muted); font-weight: 600; cursor: pointer; }
  .tabs button:hover { color: var(--text); background: var(--surface-2); }
  .tabs button[aria-selected="true"] { background: var(--accent); color: var(--on-accent); }
  .tabs button[aria-selected="true"] .n { color: inherit; opacity: 0.8; }
  .tabs .n { color: var(--muted); font-weight: 600; font-variant-numeric: tabular-nums; }
  .d-list { display: grid; gap: 6px; max-height: calc(100vh - 360px); min-height: 200px; overflow: auto; padding: 2px; }
  @media (max-width: 1259px) { .d-list { max-height: 420px; } }
  .v-empty { padding: 28px 16px; color: var(--muted); text-align: center; border: 1px dashed var(--border); border-radius: 16px; }
  /* 행: [판정 색 점] [종류 모양 / 흔들림 ◆] 종류 값 [확정·의심] / 짧은 근거 */
  .d-row { width: 100%; display: grid; grid-template-columns: 10px 20px minmax(0, 1fr) auto; align-items: center; gap: 2px 8px;
           padding: 10px 12px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); text-align: left;
           cursor: pointer; transition: background 0.15s, border-color 0.15s; }
  .d-row:hover { background: var(--surface-2); }
  .d-row[aria-selected="true"] { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent);
                                 background: color-mix(in srgb, var(--accent) 8%, var(--surface)); }
  .d-row .lvd { width: 10px; height: 10px; border-radius: 50%; background: var(--c); box-shadow: 0 0 0 1px var(--ink); }
  .d-row .ico { width: 18px; height: 18px; }
  .d-row .what { display: flex; align-items: baseline; gap: 6px; min-width: 0; font-weight: 600; white-space: nowrap; }
  .d-row .val { font-variant-numeric: tabular-nums; }
  .d-row .why { grid-column: 3 / 5; min-width: 0; color: var(--muted); font-size: var(--fs-xs); white-space: nowrap; overflow: hidden;
                text-overflow: ellipsis; }
  .lv-c-danger { --c: var(--danger); --ink: var(--danger-ink); } .lv-c-warn { --c: var(--warn); --ink: var(--warn-ink); }
  .lv-c-ok { --c: var(--ok); --ink: var(--ok-ink); }
  .dia { display: inline-grid; place-items: center; width: 18px; color: var(--ink); font-size: 15px; line-height: 1; }
  /* 흔들림 확정(2걸음 이상 기준 초과) / 의심(1걸음) */
  .cf { padding: 1px 7px; border: 1px solid var(--border); border-radius: 8px; color: var(--muted); font-size: var(--fs-xs); font-weight: 600;
        white-space: nowrap; }
  .cf.sure { border-color: var(--danger-ink); color: var(--danger-ink); background: color-mix(in srgb, var(--danger) 12%, transparent); }
  .d-right { display: grid; gap: 16px; min-width: 0; }
  .d-loc { display: block; padding: 18px 20px 20px; border: 1px solid var(--border); border-radius: 16px; background: var(--surface); box-shadow: var(--shadow); }
  .d-loc h2 { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; font-size: 15px; margin: 0 0 10px; }
  .d-loc h2 small { color: var(--muted); font-size: var(--fs-small); font-weight: 600; }
  .d-mapbox { position: relative; isolation: isolate; height: 240px; overflow: hidden; border: 1px solid var(--border); border-radius: 12px;
              background: var(--map-bg); }
  #d-map, #d-plane { position: absolute; inset: 0; }
  #d-plane svg { display: block; width: 100%; height: 100%; }
  #d-map path.d-dot-danger { fill: var(--m-danger); } #d-map path.d-dot-warn { fill: var(--m-warn); } #d-map path.d-dot-ok { fill: var(--m-ok); }
  #d-map path.d-dot { stroke: var(--m-ring); stroke-width: 1.5; fill-opacity: 1; }
  /* 밟은 블록 (검사 범위): 옅은 회색 칸, 판정 마커보다 눈에 덜 띄게 */
  .d-blk { fill: #8F8A93; fill-opacity: 0.22; stroke: #8F8A93; stroke-opacity: 0.4; stroke-width: 0.6; }
  .v-detail { min-width: 0; padding: 24px; background: var(--surface); border: 1px solid var(--border); border-radius: 16px; box-shadow: var(--shadow); }
  .v-head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 12px; }
  .v-head .kind { display: inline-flex; align-items: center; gap: 8px; font-size: 18px; font-weight: 600; }
  .v-head .kind .ico { width: 22px; height: 22px; }
  .v-head .kind .id { color: var(--muted); font-size: var(--fs-small); font-weight: 600; font-variant-numeric: tabular-nums; }
  .v-head .kind .dia { width: 22px; font-size: 19px; }
  .rep { padding: 4px 12px; border-radius: 10px; border: 1px solid var(--border); color: var(--muted); font-size: var(--fs-small); font-weight: 600; }
  .rep.in { border-color: color-mix(in srgb, var(--accent) 60%, transparent); background: color-mix(in srgb, var(--accent) 12%, transparent); color: var(--text); }
  .v-detail .d-photo { margin: 18px 0 10px; }
  .v-detail .ph { --maxh: 380px; }
  .no-photo { display: grid; place-items: center; align-content: center; gap: 6px; height: 160px; margin: 18px 0 10px;
              border: 1px dashed var(--border); border-radius: 12px; background: var(--surface-2); color: var(--muted); }
  .no-photo .ico { width: 30px; height: 30px; opacity: 0.7; }
  .v-big { display: flex; align-items: baseline; gap: 8px; margin: 10px 0 2px; }
  .v-big .num { font-size: 56px; font-weight: 500; line-height: 1; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
  .v-big .unit { font-size: 18px; font-weight: 500; color: var(--muted); }
  .v-crit { margin: 8px 0 18px; font-weight: 600; }
  .v-crit .k, .v-crit .x { color: var(--muted); font-weight: 500; }
  .v-cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin: 0 0 18px; }
  .v-card { min-width: 0; padding: 12px 14px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface-2); }
  .v-card .k { color: var(--muted); font-size: var(--fs-small); overflow-wrap: anywhere; }
  .v-card .v { margin-top: 2px; font-size: 22px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .v-card .s { color: var(--muted); font-size: var(--fs-xs); }
  .v-card.diff { border-color: color-mix(in srgb, var(--accent) 55%, var(--border)); box-shadow: inset 3px 0 0 var(--accent); }
  .v-basis { margin-top: 6px; padding-top: 18px; border-top: 1px solid var(--border); }
  .v-basis h2 { font-size: 15px; margin: 0 0 10px; }
  .v-basis dl { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 8px 16px; margin: 0; }
  .v-basis dt { color: var(--muted); }
  .v-basis dd { margin: 0; word-break: keep-all; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
  .v-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 20px; }
  .btn { padding: 9px 16px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface-2); font-weight: 600; cursor: pointer; }
  .btn:hover { border-color: var(--border-hi); }
  .btn.primary { background: var(--accent); border-color: var(--accent); color: var(--on-accent); }
  .btn.primary:hover { filter: brightness(1.08); }
  /* 사이드바 248 + 본문 여백 56 + 스크롤바 + 4×220 + 3×16 = 약 1250px 미만 → 2×2 */
  @media (max-width: 1259px) {
    .kpis { grid-template-columns: repeat(2, minmax(220px, 1fr)); }
  }

  /* ---------- 흔들림 상세: 발끝 높이 그래프 ---------- */
  .fg { margin: 10px 0 18px; padding: 16px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface-2); }
  .fg-box { width: 100%; }
  .fg-box svg { display: block; width: 100%; height: auto; }
  .fg figcaption { margin-top: 8px; color: var(--muted); font-size: var(--fs-xs); word-break: keep-all; }
  .fg-empty { display: grid; place-items: center; height: 180px; border: 1px dashed var(--border); border-radius: 12px;
              background: var(--surface); color: var(--muted); }
  .d-near { margin: 18px 0 0; padding-top: 18px; border-top: 1px solid var(--border); }
  .d-near h2 { font-size: 15px; margin: 0 0 8px; }
  .d-near p { margin: 0; }
  .d-near ul { margin: 6px 0 0; padding-left: 18px; }
  .d-near a { color: var(--accent); font-weight: 600; }

  /* ---------- 점검 이력 ---------- */
  /* 날짜 고르기: 칩(최신순, 왼쪽 점 = 그날 가장 높은 판정) + 달력 */
  .h-dates { position: relative; display: flex; align-items: center; gap: 8px; min-width: 0; margin: 16px 0 0; }
  .h-dates[hidden] { display: none; }
  .h-chips { display: flex; gap: 8px; min-width: 0; padding: 2px; overflow-x: auto; scrollbar-width: thin; }
  .h-chip { display: inline-flex; align-items: center; gap: 7px; flex: none; padding: 7px 14px 7px 11px; border: 1px solid var(--border);
            border-radius: 999px; background: var(--surface); color: var(--text); font-size: var(--fs-small); font-weight: 600;
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
  .h-cal-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; font-weight: 600; }
  .h-cal-head button { display: grid; place-items: center; width: 32px; height: 32px; padding: 0; border: 1px solid var(--border);
                       border-radius: 8px; background: var(--surface-2); color: var(--text); cursor: pointer; }
  .h-cal-head button:disabled { opacity: 0.4; cursor: default; }
  .h-cal-head svg { width: 14px; height: 14px; }
  .h-cal-grid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 2px; text-align: center; }
  .h-cal-grid .wd { padding: 4px 0; color: var(--muted); font-size: var(--fs-xs); font-weight: 600; }
  .h-cal-grid button { position: relative; height: 36px; padding: 0; border: 0; border-radius: 8px; background: none; color: var(--text);
                       font-weight: 600; font-variant-numeric: tabular-nums; cursor: pointer; }
  .h-cal-grid button:disabled { color: var(--muted); font-weight: 400; opacity: 0.45; cursor: default; }
  .h-cal-grid button:not(:disabled):hover { background: var(--surface-2); }
  .h-cal-grid button .h-dot { position: absolute; left: 50%; bottom: 3px; width: 6px; height: 6px; transform: translateX(-50%); }
  .h-cal-grid button[aria-pressed="true"] { background: var(--accent); color: var(--on-accent); }
  .h-cal-grid button[aria-pressed="true"] .h-dot { box-shadow: 0 0 0 1.5px var(--on-accent); }
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
                 color: var(--ctl-text); font-size: var(--fs-small); font-weight: 600; box-shadow: var(--ctl-shadow); cursor: pointer; }
  .h-route-btn:hover { background: var(--ctl-hover); }
  .h-route-btn .sw { width: 18px; height: 4px; border-radius: 2px; background: var(--h-route); box-shadow: 0 0 0 1.5px #FFFFFF; }
  .h-route-btn[aria-pressed="true"] { background: var(--ctl-on); border-color: var(--ctl-on); color: var(--ctl-on-text); }
  .h-route-btn[aria-pressed="false"] { color: var(--ctl-muted); }
  .h-route-btn[aria-pressed="false"] .sw { opacity: 0.35; }
  /* 경로 눈금(100 m마다)·출발·도착: 원 + 글자 상자 (클릭되지 않음) */
  .h-pin { overflow: visible; pointer-events: none; }
  .h-tick, .h-end { position: absolute; left: 0; top: 0; }
  .h-tick i { position: absolute; left: -4px; top: -4px; width: 8px; height: 8px; box-sizing: border-box; border-radius: 50%;
              background: #FFFFFF; border: 2px solid var(--h-route); }
  .h-tick b, .h-end b { position: absolute; padding: 0 5px; border: 1px solid var(--ctl-border); border-radius: 6px; background: var(--ctl-bg);
                        color: var(--ctl-text); white-space: nowrap; box-shadow: var(--ctl-shadow); }
  .h-tick b { font: 600 10.5px/16px var(--font); }
  .h-tick.s-r b { left: 9px; top: -9px; }
  .h-tick.s-t b { left: 0; bottom: 15px; transform: translateX(-50%); }
  .h-end i { position: absolute; left: -7px; top: -7px; width: 14px; height: 14px; box-sizing: border-box; border-radius: 50%;
             border: 3px solid #FFFFFF; box-shadow: 0 0 0 1.5px #363236; }
  .h-end.start i { background: var(--h-route); }
  .h-end.finish i { background: #363236; }
  .h-end b { font: 600 11.5px/18px var(--font); }
  .h-end.s-r b { left: 12px; top: -10px; } .h-end.s-l b { right: 12px; top: -10px; }
  .h-end.s-t b { left: 0; bottom: 12px; transform: translateX(-50%); } .h-end.s-b b { left: 0; top: 12px; transform: translateX(-50%); }
  .h-card { min-width: 0; padding: 20px 24px; background: var(--surface); border: 1px solid var(--border); border-radius: 16px; box-shadow: var(--shadow); }
  .h-card h2 { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
  .h-card h2 small { color: var(--muted); font-size: var(--fs-small); font-weight: 600; font-variant-numeric: tabular-nums; }
  .h-empty { padding: 20px 0; color: var(--muted); text-align: center; }
  /* 종류별 판정 누적 막대: 칸 사이 2px, 칸 안에 기호 + 숫자, 오른쪽에 글자 요약 (색만으로 구분하지 않음) */
  .h-bars { display: grid; gap: 14px; }
  .h-bar { display: grid; grid-template-columns: 76px minmax(0, 1fr); align-items: center; gap: 4px 12px; }
  .h-bar .k { display: inline-flex; align-items: center; gap: 6px; font-weight: 600; font-size: var(--fs-small); }
  .h-bar .track { display: flex; gap: 2px; height: 26px; min-width: 0; }
  .h-bar .seg { display: flex; align-items: center; justify-content: center; min-width: 0; overflow: hidden; border-radius: 4px;
                color: var(--on-grade); font-size: var(--fs-xs); font-weight: 600; white-space: nowrap; font-variant-numeric: tabular-nums;
                container-type: inline-size; }
  @container (max-width: 26px) { .h-bar .seg span { visibility: hidden; } }
  .h-bar .seg.danger { background: var(--danger); } .h-bar .seg.warn { background: var(--warn); } .h-bar .seg.ok { background: var(--ok); }
  .h-bar .zero { color: var(--muted); font-size: var(--fs-xs); line-height: 26px; }
  .h-bar .line { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .h-bar .tot { font-size: var(--fs-small); font-weight: 600; font-variant-numeric: tabular-nums; }
  .h-bar .sum { grid-column: 2; color: var(--muted); font-size: var(--fs-xs); font-variant-numeric: tabular-nums; }
  .h-bars-total { margin: 16px 0 0; padding-top: 12px; border-top: 1px solid var(--border); color: var(--muted); font-size: var(--fs-small);
                  font-variant-numeric: tabular-nums; }
  .h-bars-total b { color: var(--text); font-weight: 600; }
  .h-card .h-tools { margin: 0 0 12px; }
  .h-more { display: block; width: 100%; margin-top: 10px; padding: 10px; border: 1px dashed var(--border); border-radius: 10px;
            background: none; color: var(--accent); font-size: var(--fs-small); font-weight: 600; cursor: pointer; }
  .h-more:hover { background: var(--surface-2); }
  .h-more[hidden] { display: none; }
  .h-table tbody tr.hl { background: var(--surface-2); }
  .h-bar .sum b { color: var(--text); font-weight: 600; }
  /* 표: 길면 표 안에서만 스크롤, 머리줄 고정 */
  .h-table-wrap { max-height: 560px; overflow: auto; margin: 0 -8px; padding: 0 8px; }
  .h-table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: var(--fs-small); font-variant-numeric: tabular-nums; }
  .h-table th { position: sticky; top: 0; z-index: 1; padding: 0; background: var(--surface); color: var(--muted); font-weight: 600;
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
  .h-table .go { color: var(--accent); font-weight: 600; text-decoration: none; white-space: nowrap; }
  .h-table .go:hover { text-decoration: underline; }

  /* ---------- 툴팁 · 묶음 고르기 (카드 스타일) ---------- */
  .tip { position: fixed; z-index: 3000; pointer-events: none; max-width: 280px; padding: 10px 12px; border-radius: 12px;
         background: var(--surface); color: var(--text); border: 1px solid var(--border); box-shadow: var(--shadow-pop); font-size: var(--fs-xs); }
  .tip b { display: block; margin-bottom: 2px; font-size: var(--fs-small); }
  .tip div { color: var(--muted); }
  .tip .tip-go { color: var(--accent); font-weight: 600; margin-top: 4px; }
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
  .d-photo .ph-cap { color: var(--text); font-size: var(--fs-small); font-weight: 600; word-break: keep-all; }
  .d-photo .ph-hint { display: inline-flex; align-items: center; gap: 5px; }
  .dlg { width: min(94vw, 980px); max-height: 94vh; padding: 0; border: 1px solid var(--border); border-radius: 16px;
         background: var(--surface); color: var(--text); box-shadow: var(--shadow); }
  .dlg::backdrop { background: rgb(31 28 31 / 0.6); -webkit-backdrop-filter: blur(4px); backdrop-filter: blur(4px); }
  .dlg-head { display: flex; align-items: center; gap: 8px; padding: 14px 16px 14px 20px; border-bottom: 1px solid var(--border); }
  .dlg-head h2 { margin: 0; font-size: var(--fs-h2); flex: 1; min-width: 0; }
  .dlg-head button { border: 1px solid var(--border); background: var(--surface-2); border-radius: 10px; padding: 6px 12px; cursor: pointer; }
  .dlg-body { padding: 16px; }
  .dlg .ph { --maxh: calc(94vh - 140px); }
  .dlg-cap { margin: 10px 2px 0; color: var(--muted); font-size: var(--fs-small); word-break: keep-all; overflow-wrap: anywhere; }
  .dlg-cap-main { color: var(--text); font-weight: 600; }

  /* ---------- 카드: 모서리 18px, 테두리 없이 옅은 그림자 ---------- */
  .kpi, .v-detail, .d-loc, .h-card, .d-summary { border: 0; border-radius: var(--radius); background: var(--surface);
                                                                     box-shadow: var(--shadow); }
  .h-mapbox, .d-mapbox { border: 0; border-radius: 14px; }
  /* ---------- 버튼·칩: 완전 둥근 모양(pill) ---------- */
  .btn, .lv-btn, .h-chip, .retry, .h-route-btn, .h-reset, .h-more, .tabs, .tabs button,
  .h-f select, .cf, .rep, .ph-btn { border-radius: 999px; }
  .ph-btn { border-radius: 12px; }
  .btn { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--border); background: var(--surface); color: var(--text); }
  .btn.primary { background: var(--accent); border-color: var(--accent); color: var(--on-accent); }
  .tabs { padding: 4px; border: 0; box-shadow: var(--shadow); }
  .lv-btn, .h-chip { background: var(--surface); }
  .h-cal-btn { width: 36px; height: 36px; padding: 0; border: 0; border-radius: 50%; background: var(--surface);
                         color: var(--text); box-shadow: var(--shadow); }

  /* ---------- 유리(젤리) 카드: 떠 있는 카드·메뉴·버튼 공통 ----------
     흰 유리 0.78 / 다크 유리 0.86. 지도에서 가장 어두운 곳(검정) / 가장 밝은 곳(흰색) 위에서도 글자 대비 4.5 이상,
     유리 위 보조 글자는 --glass-muted (라이트 #55505A 4.63:1, 다크 #C2BCC5 5.88:1). 등급 색 글자는 불투명 배지 안에만.
     종합 현황은 지도 밝기 = 테마 (밝은 지도 → 흰 유리, 어두운 지도 → 다크 유리) */
  :root { --glass-bg: rgb(255 255 255 / 0.78); --glass-border: rgb(255 255 255 / 0.8); --glass-hi: inset 0 1px 0 rgb(255 255 255 / 0.9);
          --glass-shadow: 0 8px 32px rgb(54 50 54 / 0.12); --glass-muted: #55505A; --glass-solid: #FFFFFF; --frame-bg: rgb(54 50 54 / 0.06);
          --gauge-track: rgb(54 50 54 / 0.12); }
  :root[data-theme="dark"] { --glass-bg: rgb(31 28 31 / 0.86); --glass-border: rgb(255 255 255 / 0.08); --glass-hi: inset 0 1px 0 rgb(255 255 255 / 0.06);
          --glass-shadow: 0 8px 32px rgb(0 0 0 / 0.36); --glass-muted: #C2BCC5; --glass-solid: #2A262A; --frame-bg: rgb(255 255 255 / 0.06);
          --gauge-track: rgb(255 255 255 / 0.16); }
  .glass, .nav, .icon-btn, #page-home .retry {
    background: var(--glass-bg); -webkit-backdrop-filter: blur(18px) saturate(1.4); backdrop-filter: blur(18px) saturate(1.4);
    border: 1px solid var(--glass-border); box-shadow: var(--glass-hi), var(--glass-shadow); }
  .glass { border-radius: 18px; color: var(--text); }
  .frame { padding: 6px; border-radius: 22px; background: var(--frame-bg); }  /* 카드 묶음을 감싸는 반투명 회색 틀 */
  /* 흐림을 못 쓰거나 투명도를 줄이도록 설정한 환경: 불투명 */
  @supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
    .glass, .nav, .icon-btn, #page-home .retry { background: var(--glass-solid); }
  }
  @media (prefers-reduced-transparency: reduce) {
    .glass, .nav, .icon-btn, #page-home .retry { background: var(--glass-solid); -webkit-backdrop-filter: none; backdrop-filter: none; }
  }
  .app:has(#page-home:not([hidden])) .tb-date { display: none; }

  /* ---------- 종합 현황: 화면 전체 지도 + 유리 카드 ---------- */
  #page-home { --card-w: 360px; }
  .sr-only { position: absolute; width: 1px; height: 1px; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
  .hfilter { display: flex; flex-direction: column; gap: 10px; padding: 12px 14px; color: var(--glass-muted); font-size: var(--fs-small); }
  .hfilter .lv-filter { display: flex; }
  .hfilter .lv-btn:not([aria-pressed="true"]) { background: var(--glass-solid); color: var(--glass-muted); }
  .hfilter .shape-legend .item { color: var(--text); }
  .hfilter .shape-legend .shp { fill: var(--glass-muted); }
  /* ---------- 아래 블록 줄: 반투명 회색 틀 안에 로봇 카드 + (지점을 누르면) 사진·측정값/기준 대비·근거 블록 ---------- */
  #page-home { --rc-w: clamp(440px, 34vw, 520px); }
  .hrow { display: flex; gap: 8px; padding: 8px; border-radius: 22px; background: rgb(54 50 54 / 0.08); }
  :root[data-theme="dark"] .hrow { background: rgb(255 255 255 / 0.08); }
  .hrow .glass { min-width: 0; }
  .chip-bg { background: rgb(54 50 54 / 0.07); }
  :root[data-theme="dark"] .chip-bg { background: rgb(255 255 255 / 0.09); }
  /* 로봇 카드 */
  .hrobot { position: relative; display: flex; flex-direction: column; flex: 0 0 var(--rc-w); padding: 16px 18px; overflow: visible; }
  .rc-top { position: relative; z-index: 1; display: flex; align-items: center; gap: 8px; min-width: 0; }
  .rc-name { min-width: 0; padding: 7px 16px; border-radius: 12px; background: #F7B558; color: #363236; font-size: 22px; font-weight: 600;
             line-height: 1.25; letter-spacing: -0.02em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .rc-nav { display: flex; gap: 4px; margin-left: auto; padding: 4px; border-radius: 14px; }
  .rc-nav button { display: grid; place-items: center; width: 34px; height: 34px; padding: 0; border: 0; border-radius: 50%;
                   background: var(--glass-solid); color: var(--text); box-shadow: 0 1px 3px rgb(54 50 54 / 0.14); cursor: pointer; }
  .rc-nav button:hover { background: var(--accent); color: var(--on-accent); }
  .rc-nav svg { width: 16px; height: 16px; }
  .rc-dl { position: relative; z-index: 1; display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: center; gap: 6px 10px;
           max-width: 58%; margin: 16px 0 0; font-size: var(--fs-small); }
  .rc-dl dt { color: var(--glass-muted); white-space: nowrap; }
  .rc-dl dd { justify-self: start; max-width: 100%; margin: 0; padding: 2px 10px; border-radius: 999px; overflow: hidden; white-space: nowrap;
              text-overflow: ellipsis; font-variant-numeric: tabular-nums; }
  .rc-dl dd.chip-bg { background: #EFEEF0; }  /* 불투명: 뒤의 로봇 사진이 비치지 않게 */
  .rc-dl [hidden] { display: none; }
  .rc-art { position: absolute; z-index: 0; right: -6px; bottom: -16px; width: 42%; height: 186px; pointer-events: none; }  /* 오른쪽 아래로 살짝 넘침 (옆 블록은 가리지 않게) */
  .rc-art::after { content: ""; position: absolute; left: 14%; right: 6%; bottom: 6px; height: 16px; border-radius: 50%;
                   background: radial-gradient(closest-side, rgb(54 50 54 / 0.26), rgb(54 50 54 / 0)); }  /* 발밑 옅은 타원 그림자 */
  :root[data-theme="dark"] .rc-art::after { background: radial-gradient(closest-side, rgb(0 0 0 / 0.55), rgb(0 0 0 / 0)); }
  .rc-art img, .rc-art svg { position: relative; z-index: 1; display: block; width: 100%; height: 100%; object-fit: contain; object-position: right bottom; }
  .rc-art svg { color: var(--text); }
  /* 사진: 카드 높이 + 14px로 위(4px)·아래(10px)·오른쪽(8px)으로 살짝 넘친다. ← → 버튼이 위 레이어.
     폭은 JS(fitRobotPhoto)가 칩 오른쪽 끝 + 4px부터 카드 오른쪽 넘침까지 안에서 최대로 맞춘다 */
  .rc-art.photo { right: -8px; bottom: -10px; width: 52%; height: calc(100% + 14px); opacity: 1; }
  .rc-art.photo::after { left: auto; right: calc(var(--shot-w, 100%) * 0.15); bottom: -5px; width: calc(var(--shot-w, 100%) * 0.7); height: 10px;
                         background: rgb(54 50 54 / 0.12); filter: blur(8px); }  /* 발밑 옅은 타원 그림자: 사진 폭의 70% */
  .rc-art[hidden], .rc-art img[hidden], .rc-art svg[hidden] { display: none; }
  :root[data-theme="dark"] .rc-art::before { content: ""; position: absolute; right: 6%; bottom: 8%; width: 76%; aspect-ratio: 1; border-radius: 50%;
                                             background: radial-gradient(circle, rgb(255 255 255 / 0.18), rgb(255 255 255 / 0) 70%); }  /* 다크: 옅은 받침 */
  /* 지점 블록: [사진][측정값 / 기준 대비][근거] */
  .hblocks { position: relative; flex: 1 1 auto; min-width: 0; display: grid; gap: 8px; overflow: hidden; overflow: clip; overflow-clip-margin: 12px;
             grid-template-columns: minmax(170px, 1.5fr) minmax(170px, 1fr) minmax(210px, 1.25fr); grid-template-rows: repeat(2, minmax(0, 1fr));
             grid-template-areas: "photo num why" "photo ratio why"; }
  .hblocks[hidden] { display: none; }
  .hblocks.in > .hb { animation: hb-up 0.25s ease-out both; }
  @keyframes hb-up { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: none; } }
  @media (prefers-reduced-motion: reduce) { .hblocks.in > .hb { animation: none; } }
  .hb { position: relative; display: flex; flex-direction: column; min-height: 0; padding: 12px 16px; }
  .hb-photo { grid-area: photo; padding: 0; overflow: hidden; border-radius: 18px; }
  .hb-num { grid-area: num; }
  .hb-ratio { grid-area: ratio; }
  .hb-why { grid-area: why; }
  .hb-photo .ph-btn { position: relative; display: block; width: 100%; height: 100%; padding: 4px; border: 0; background: none; cursor: zoom-in; }
  .hb-photo .hb-pic { position: relative; width: 100%; height: 100%; overflow: hidden; border-radius: 14px; }
  .hb-photo .hb-pic img, .hb-photo .hb-pic svg { position: absolute; inset: 0; width: 100%; height: 100%; }
  .hb-photo .hb-pic img { object-fit: cover; }
  .hb-photo .no-photo { height: calc(100% - 8px); margin: 4px; border-radius: 14px; }
  .hb-mk { position: absolute; z-index: 1; padding: 2px 7px; border-radius: 999px; background: rgb(255 255 255 / 0.86); color: #363236;
           font-size: 11px; font-weight: 600; line-height: 1.4; white-space: nowrap; pointer-events: none; transform: translate(-50%, 0); }
  .hb-tag { position: absolute; top: 12px; left: 12px; z-index: 1; display: inline-flex; align-items: center; gap: 6px; max-width: calc(100% - 24px);
            padding: 4px 10px 4px 4px; border-radius: 999px; background: var(--glass-solid); font-size: var(--fs-small); font-weight: 600;
            white-space: nowrap; overflow: hidden; box-shadow: var(--glass-shadow); }
  .hb-tag .id { color: var(--glass-muted); font-weight: 500; font-variant-numeric: tabular-nums; }
  .hb-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
  .hb-head .t { font-size: var(--fs-small); font-weight: 600; }
  .hb-head .s { color: var(--glass-muted); font-size: var(--fs-xs); white-space: nowrap; font-variant-numeric: tabular-nums; }
  .hb-body { flex: 1; display: flex; align-items: flex-end; justify-content: space-between; gap: 8px; min-height: 0; }
  .hb-big { font-size: 38px; font-weight: 500; line-height: 1; letter-spacing: -0.02em; white-space: nowrap; font-variant-numeric: tabular-nums; }
  .hb-big small { margin-left: 3px; color: var(--glass-muted); font-size: 15px; font-weight: 500; letter-spacing: 0; }
  .hb-big.txt { font-size: 24px; }
  .hb-gauge { display: block; flex: 0 1 112px; min-width: 76px; max-height: 100%; overflow: visible; }
  .hb-why { gap: 8px; padding-right: 92px; font-size: var(--fs-small); }
  .hb-why .crit { margin: 0; font-weight: 600; word-break: keep-all; }
  .hb-why .meta { margin: 0; color: var(--glass-muted); font-size: var(--fs-xs); font-variant-numeric: tabular-nums; }
  .hb-why .sink { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
  .hb-cf { padding: 2px 9px; border-radius: 999px; background: var(--accent); color: var(--on-accent); font-size: var(--fs-xs); font-weight: 600; }
  .hb-methods { display: flex; gap: 14px; margin-top: auto; }
  .hb-methods .m { display: inline-flex; flex-direction: column; align-items: center; gap: 3px; color: var(--glass-muted); font-size: 11px; }
  .hb-methods .m svg { width: 22px; height: 22px; opacity: 0.35; }
  .hb-methods .m.on { color: var(--text); font-weight: 600; }
  .hb-methods .m.on svg { opacity: 1; }
  .hb-acts { position: absolute; top: 10px; right: 10px; display: flex; align-items: center; gap: 6px; }
  .hb-go { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 50%; background: var(--accent); color: var(--on-accent); }
  .hb-go svg { width: 16px; height: 16px; }
  .hb-close { display: grid; place-items: center; width: 26px; height: 26px; padding: 0; border: 0; border-radius: 50%;
              background: rgb(54 50 54 / 0.07); color: var(--text); cursor: pointer; }
  :root[data-theme="dark"] .hb-close { background: rgb(255 255 255 / 0.09); }
  .hb-close:hover { background: var(--accent); color: var(--on-accent); }
  .hb-close svg { width: 13px; height: 13px; }
  /* 로봇개 마커: 차콜 원 + 흰 사족보행 실루엣, 옅은 차콜 고리가 천천히 퍼진다 */
  .robot-mk { background: none; border: 0; cursor: pointer; }
  .robot-mk:focus-visible { outline: 2px solid var(--m-focus); outline-offset: 3px; border-radius: 50%; }
  #plane .robot { cursor: pointer; }
  .robot-mk .pulse, .robot-mk .core { position: absolute; left: 0; top: 0; width: 36px; height: 36px; border-radius: 50%; }
  .robot-mk .pulse { background: rgb(54 50 54 / 0.28); animation: robot-pulse 2.6s ease-out infinite; }
  .robot-mk .core { display: grid; place-items: center; background: #363236; color: #FFFFFF;
                    box-shadow: 0 0 0 2px #FFFFFF, 0 2px 8px rgb(54 50 54 / 0.35); }
  .robot-mk svg { width: 24px; height: 24px; }
  #plane .robot-pulse { transform-box: fill-box; transform-origin: center; animation: robot-pulse 2.6s ease-out infinite; }
  @keyframes robot-pulse { from { transform: scale(1); opacity: 0.6; } to { transform: scale(2.6); opacity: 0; } }
  @media (prefers-reduced-motion: reduce) {
    .robot-mk .pulse, #plane .robot-pulse { animation: none; opacity: 0.3; transform: scale(1.5); }
  }
  /* 1260px 이상: 지도를 화면 전체에 깔고 메뉴·카드가 모두 위에 뜬다 (페이지 스크롤 없음) */
  @media (min-width: 1260px) {
    body:has(#page-home:not([hidden])) { overflow: hidden; }
    .app:has(#page-home:not([hidden])) .topbar { position: fixed; left: 0; right: 0; background: none;
                                                 -webkit-backdrop-filter: none; backdrop-filter: none; pointer-events: none; }
    .app:has(#page-home:not([hidden])) .topbar > * { pointer-events: auto; }
    .app:has(#page-home:not([hidden])) .logo { padding: 5px 16px 5px 5px; border-radius: 999px; background: var(--glass-bg);
      -webkit-backdrop-filter: blur(18px) saturate(1.4); backdrop-filter: blur(18px) saturate(1.4); border: 1px solid var(--glass-border);
      box-shadow: var(--glass-hi), var(--glass-shadow); }
    #page-home .mapbox { position: fixed; inset: 0; z-index: 0; }
    #page-home .hfilter { position: fixed; top: calc(var(--topbar-h) + 4px); left: 28px; z-index: 700; max-width: 380px; }
    #page-home .map-tools { position: fixed; top: calc(var(--topbar-h) + 4px); right: 28px; z-index: 700; }
    /* 틀은 처음엔 로봇 카드 크기만, 지점을 고르면 오른쪽 끝(여백 24px)까지 0.25초에 늘어난다 */
    #page-home .hrow { position: fixed; left: 24px; bottom: 24px; z-index: 700; height: 250px; width: calc(var(--rc-w) + 16px);
                       max-width: calc(100vw - 48px); transition: width 0.25s ease-out; }
    #page-home .hrow.open { width: calc(100vw - 48px); }
    #page-home .leaflet-bottom { bottom: 286px; }  /* 확대 버튼은 블록 줄(250px + 아래 여백 24px) 바로 위 (열고 닫아도 높이 같음) */
    #page-home .leaflet-right { right: 20px; }
    .map-attr { position: fixed; right: 8px; bottom: 4px; z-index: 750; max-width: calc(100vw - 16px); }  /* 블록 줄 아래 여백(24px) 안 */
  }
  @media (min-width: 1260px) and (prefers-reduced-motion: reduce) { #page-home .hrow { transition: none; } }
  /* 1259px 이하: 지도는 위 60%, 그 아래 로봇 카드 → 지점 블록 순서로 일반 카드 */
  @media (max-width: 1259px) {
    #page-home .hmapwrap { position: relative; height: 60vh; min-height: 320px; margin-top: 4px; overflow: hidden; border-radius: var(--radius);
                           box-shadow: var(--shadow); }
    #page-home .mapbox { position: absolute; inset: 0; }
    #page-home .hfilter { position: absolute; top: 10px; left: 10px; z-index: 700; max-width: calc(100% - 20px); padding: 10px 12px; }
    #page-home .map-tools { position: absolute; right: 10px; bottom: 34px; z-index: 700; }
    #page-home .hrow { flex-direction: column; margin-top: 12px; }
    #page-home .hrobot { flex: none; min-height: 230px; }
    #page-home .hblocks { grid-template-columns: repeat(2, minmax(0, 1fr)); grid-template-rows: none; padding-top: 4px;
                          grid-template-areas: "photo photo" "num ratio" "why why"; }
    #page-home .hb-photo { height: 240px; }
    #page-home .hb-num, #page-home .hb-ratio { min-height: 150px; }
    #page-home .hb-why { min-height: 150px; }
    #page-home .map-tools { max-width: calc(100% - 20px); }
    .map-attr { position: absolute; right: 0; bottom: 0; z-index: 750; max-width: 100%; }
    #page-home .leaflet-bottom { bottom: 16px; }  /* 확대 버튼은 저작자 표시 위 */
  }
  @media (max-width: 760px) {
    .app:has(#page-home:not([hidden])) .logo > span:last-child { display: none; }
    .rc-top { flex-wrap: wrap; }
    .rc-name { font-size: 16px; }
    .rc-dl { max-width: 100%; }
    .rc-art { width: 34%; height: 110px; right: -6px; bottom: -10px; opacity: 0.35; }  /* 좁은 화면: 글자 뒤로 작게 */
    #page-home .hblocks { grid-template-columns: minmax(0, 1fr); grid-template-areas: "photo" "num" "ratio" "why"; }
  }
  /* ---------- 모바일: 아래 탭바는 짧은 이름 ---------- */
  @media (max-width: 760px) {
    :root { --fs-title: 20px; --fs-h2: 15px; --topbar-h: 60px; }
    .topbar { padding: 0 16px; }
    .tb-date .k { display: none; }
    .nav .full { display: none; }
    .nav .short { display: inline; }
    .main { padding: 0 16px 96px; }
    .page-head { padding-top: 0; }
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
    :is(#map, #h-map, #d-map) .leaflet-control-attribution { font-size: 10px; }
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
    .h-points td:nth-child(3) { justify-self: end; font-weight: 600; }
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
  <header class="topbar">
    <a class="logo" href="#home" aria-label="StepMap 종합 현황"><span class="logo-mark"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 18.5c4 0 3-5 7-5s3-5 7-5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/><circle cx="5" cy="18.5" r="2" fill="currentColor"/><circle cx="19" cy="8.5" r="2" fill="currentColor"/></svg></span><span>StepMap</span></a>
    <nav class="nav" id="nav" aria-label="페이지">
      <a href="#home" data-page="home">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 11.5 12 5l8 6.5V19a1 1 0 0 1-1 1h-4.5v-5h-5v5H5a1 1 0 0 1-1-1z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>
        <span class="full">종합 현황</span><span class="short">종합</span></a>
      <a href="#detail" data-page="detail">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 4.5h8M8 4.5a1.5 1.5 0 0 0-1.5 1.5v.5h11V6A1.5 1.5 0 0 0 16 4.5M6.5 6.5H5a1 1 0 0 0-1 1V20a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V7.5a1 1 0 0 0-1-1h-1.5M8 12.5l2.5 2.5L16 9.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/></svg>
        <span class="full">검사 결과</span><span class="short">검사</span></a>
      <a href="#history" data-page="history">
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M12 7.5V12l3 2" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        <span class="full">점검 이력</span><span class="short">이력</span></a>
    </nav>
    <div class="tb-right">
      <span class="tb-date" id="tb-date"></span>
    </div>
  </header>

  <main class="main" id="main">
    <section class="page" id="page-home" data-page="home" aria-labelledby="home-title">
      <h1 class="sr-only" id="home-title">종합 현황</h1>
      <div class="hmapwrap">
        <div class="mapcard" id="mapcard" data-map="light">
          <div class="mapbox">
            <div id="map" role="application" aria-label="측정 지점 지도"></div>
            <div id="plane" role="group" aria-label="측정 지점 지도 (odom 좌표)" hidden></div>
            <div class="map-tools">
              <button type="button" class="retry" id="retry" hidden>지도 다시 불러오기</button>
            </div>
            <div class="map-empty" id="map-empty" role="status" hidden>표시할 지점이 없어요</div>
          </div>
        </div>
        <div class="map-attr" id="map-attr"></div>
        <div class="glass hfilter legend" id="legend" aria-label="범례">
          <div class="lv-filter" id="lv-filter" role="group" aria-label="판정별 지점 보기">__LEVEL_FILTER__</div>
          <span class="sep" aria-hidden="true"></span>
          <div class="shape-legend" id="shape-legend" role="group" aria-label="마커 모양">
            <span class="item"><svg class="shp" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="5.6"/></svg>노면 형상</span>
            <span class="item"><svg class="shp" viewBox="0 0 16 16" aria-hidden="true"><rect x="3.3" y="3.3" width="9.4" height="9.4" rx="1.8" transform="rotate(45 8 8)"/></svg>흔들림</span>
          </div>
        </div>
      </div>
      <div class="hrow" id="hrow" aria-label="점검 로봇과 지점 근거">
        <section class="glass hrobot" aria-labelledby="rc-name">
          <div class="rc-top">
            <b class="rc-name" id="rc-name"></b>
            <div class="rc-nav chip-bg" role="group" aria-label="지점 고르기">
              <button type="button" id="rc-prev" aria-label="이전 지점 (위험→주의 순)"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 5l-7 7 7 7" style="fill:none;stroke:currentColor;stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round"/></svg></button>
              <button type="button" id="rc-next" aria-label="다음 지점 (위험→주의 순)"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5l7 7-7 7" style="fill:none;stroke:currentColor;stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round"/></svg></button>
            </div>
          </div>
          <dl class="rc-dl">
            <dt>모델:</dt><dd class="chip-bg" id="rc-model"></dd>
            <dt id="rc-battery-k">배터리:</dt><dd class="chip-bg" id="rc-battery"></dd>
            <dt>센서:</dt><dd class="chip-bg" id="rc-sensors"></dd>
            <dt>점검 일시:</dt><dd class="chip-bg" id="rc-when"></dd>
            <dt>이동 거리:</dt><dd class="chip-bg" id="rc-dist"></dd>
          </dl>
          <div class="rc-art"><img id="rc-photo" alt="점검 로봇" hidden><svg id="rc-draw" viewBox="0 0 220 170" aria-hidden="true"><g style="fill:none;stroke:currentColor;stroke-width:11;stroke-linecap:round;stroke-linejoin:round"><path d="M62 96 46 122l10 30M84 96l-6 28 16 28M146 96l12 28-12 28M166 96l18 26-8 30"/></g><rect x="44" y="60" width="136" height="42" rx="20" style="fill:currentColor"/><path d="M168 66 196 46a7 7 0 0 1 9.6 2l6.4 10a7 7 0 0 1-2.6 9.8L186 80z" style="fill:currentColor"/><rect x="70" y="52" width="58" height="12" rx="6" style="fill:currentColor;opacity:0.7"/></svg></div>
        </section>
        <div class="hblocks" id="hblocks" aria-label="지점 근거" aria-live="polite" hidden></div>
      </div>
    </section>

    <section class="page" id="page-detail" data-page="detail" aria-labelledby="detail-title" hidden>
      <header class="page-head"><h1 id="detail-title">검사 결과</h1><p class="sub">노면 형상(카메라·발로 잰 단차·경사·균열)과 흔들림(발 접촉)</p></header>
      <p class="d-summary" id="d-summary" aria-label="검사 요약"></p>
      <div class="d-grid">
        <div class="d-left">
          <div class="tabs" id="d-tabs" role="tablist" aria-label="검사 종류"></div>
          <div class="lv-filter" id="d-levels" role="group" aria-label="판정별 지점 보기"><button type="button" class="lv-btn" data-level="danger" aria-pressed="true"><span class="dot" aria-hidden="true"></span>위험 <span class="n" id="d-n-danger"></span></button><button type="button" class="lv-btn" data-level="warn" aria-pressed="true"><span class="dot" aria-hidden="true"></span>주의 <span class="n" id="d-n-warn"></span></button><button type="button" class="lv-btn" data-level="ok" aria-pressed="false"><span class="dot" aria-hidden="true"></span>정상 <span class="n" id="d-n-ok"></span></button></div>
          <div class="d-list" id="d-list" role="listbox" aria-label="검사 지점"></div>
        </div>
        <div class="d-right">
          <article class="v-detail" id="d-detail" aria-live="polite"></article>
          <section class="d-loc mapcard" data-map="light" aria-labelledby="d-loc-title">
            <h2 id="d-loc-title">위치 <small id="d-loc-sub"></small></h2>
            <div class="d-mapbox">
              <div id="d-map" role="img" aria-label="선택한 지점 주변 지도"></div>
              <div id="d-plane" role="img" aria-label="선택한 지점 주변 (odom 좌표)" hidden></div>
            </div>
          </section>
        </div>
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
<script src="__MAPLIBRE_JS__" integrity="__MAPLIBRE_JS_SRI__" crossorigin="anonymous"></script>
<script src="__MAPLIBRE_LEAFLET_JS__" integrity="__MAPLIBRE_LEAFLET_JS_SRI__" crossorigin="anonymous"></script>
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
    detail:   { title: "검사 결과" },
    history:  { title: "점검 이력" },
  };
  // 지점 상세는 모두 검사 결과 페이지 (노면 형상·흔들림 함께)
  const detailHref = (e) => `#detail/${e.id}`;
  // 종합 현황 지도에서 마커를 누르면 페이지를 옮기지 않고 옆 패널에 상세를 연다 (#home/<id>: 새로고침해도 유지)
  const pick = (e) => {
    if (state.sel && state.sel.id === e.id) return;  // 같은 지점: 주소가 그대로라 hashchange가 오지 않는다
    state.pickedOnMap = true;
    location.replace(`#home/${e.id}`);
    ensureVisible(e);
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
    (sel ? `<circle cx="12" cy="12" r="14.5" style="fill:var(--map-bg);stroke:#363236;stroke-width:5"/>` +
           `<circle cx="12" cy="12" r="14.5" style="fill:none;stroke:#FFFFFF;stroke-width:3"/>` : "") +
    KIND[e.kind].shape(`var(--m-${e.level})`, "var(--m-ring)");
  // 종합 현황 지도 마커 모양: 노면 형상(단차·경사·균열)은 원, 흔들림은 마름모(45° 돌린 둥근 사각형) + 흰 발 아이콘.
  // 색은 판정 색 (지도 배경별 --m-*). 두 모양은 면적이 비슷하다 (원 r 8 ≈ 201, 마름모 한 변 14.2 ≈ 202)
  const homeShape = (e) => (e.kind === "loose" ? "diamond" : "circle");
  const PAW = '<g style="fill:#FFFFFF;stroke:#363236;stroke-width:1;paint-order:stroke">' +  // 흰 발 + 차콜 얇은 테두리 (주의 노랑 위 대비)
              '<ellipse cx="12" cy="13.7" rx="2.7" ry="2.2"/><circle cx="9.2" cy="10.6" r="1.1"/>' +
              '<circle cx="12" cy="9.5" r="1.15"/><circle cx="14.8" cy="10.6" r="1.1"/></g>';
  const HOME_SHAPE = {
    circle: (c) => `<circle class="mk-circle" cx="12" cy="12" r="8" style="fill:${c};stroke:var(--m-ring);stroke-width:4;paint-order:stroke"/>`,
    diamond: (c) => `<rect class="mk-diamond" x="4.9" y="4.9" width="14.2" height="14.2" rx="2.6" transform="rotate(45 12 12)" ` +
                    `style="fill:${c};stroke:var(--m-ring);stroke-width:4;paint-order:stroke"/>` + PAW,
  };
  // 누른 지점: 차콜 원 + 점선 고리 위에 원래 모양
  const homeMarkerInner = (e, sel) =>
    (sel ? `<circle class="mk-sel" cx="12" cy="12" r="14" style="fill:#363236"/>` +
           `<circle cx="12" cy="12" r="17.5" style="fill:none;stroke:var(--link, #363236);stroke-width:1.5;stroke-dasharray:3 2.6"/>` : "") +
    HOME_SHAPE[homeShape(e)](`var(--m-${e.level})`);
  // 로봇개 아이콘 (단순한 사족보행 실루엣: 몸통 + 머리 + 다리 넷, currentColor)
  const ROBOT_PATH = '<g style="fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round">' +
                     '<path d="M7.2 14.2 5.8 17l1.2 2.6M9.6 14.2l-.5 2.8 1.5 2.6M14.6 14.2l1.1 2.8-1.2 2.6M16.9 14.2l1.5 2.8-.9 2.6"/></g>' +
                     '<rect x="5.6" y="9.4" width="12.6" height="5.2" rx="2.2" style="fill:currentColor"/>' +
                     '<path d="M17.4 10.3 20 8.6a.8.8 0 0 1 1.1.2l.8 1.3a.8.8 0 0 1-.3 1.1l-2.6 1.4z" style="fill:currentColor"/>';
  // 로봇의 마지막 위치 = 이동 궤적 마지막 점 (위도·경도, odom x·y)
  const ROBOT_LL = DATA.trajectory.length ? DATA.trajectory[DATA.trajectory.length - 1] : null;
  const ROBOT_XY = DATA.trajectory_xy.length ? DATA.trajectory_xy[DATA.trajectory_xy.length - 1] : null;
  const wideHome = matchMedia("(min-width: 1260px)");
  // 지도 범위를 맞출 때 떠 있는 카드 자리를 비운다: 위(메뉴 + 필터 카드), 아래(블록 줄 높이 + 여백), 오른쪽(확대 버튼)
  function homePadding() {
    if (!wideHome.matches) return { tl: [28, 64], br: [28, 28] };
    const top = document.querySelector(".topbar").offsetHeight + $("legend").offsetHeight + 24;
    return { tl: [48, top], br: [72, $("hrow").offsetHeight + 24 + 32] };
  }
  const homeMarkerSvg = (e, sel, lead = "") =>
    `<svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">${lead}${homeMarkerInner(e, sel)}</svg>`;
  // 묶음: 흰 원 + 차콜 숫자(그 판정 기호 작게) + 가장 심한 판정 색 테두리. 흔들림이 하나라도 있으면 오른쪽 위에 작은 마름모 배지
  // (배지 색 = 묶음 안 흔들림 중 가장 심한 판정). w: 표시 상자 한 변 (원 지름 + 테두리)
  function pill(members, sel) {
    const worst = members[0].level;
    const n = members.length;
    const d = n < 10 ? 22 : 26, w = d + 4, c = w / 2;
    const ring = sel ? "var(--m-focus)" : "var(--m-ring)";
    const loose = members.filter((e) => e.kind === "loose");
    const badge = loose.length
      ? `<rect class="mk-badge" x="${w - 8}" y="-1" width="7" height="7" rx="1.4" transform="rotate(45 ${w - 4.5} 2.5)" ` +
        `style="fill:var(--m-${loose[0].level});stroke:var(--m-ring);stroke-width:3;paint-order:stroke"/>`
      : "";
    // 글자: 흰 원 위 차콜 (12.6:1)
    return { w, svg:
      `<circle class="mk-cluster" cx="${c}" cy="${c}" r="${d / 2 - 0.5}" style="fill:#FFFFFF;stroke:${sel ? ring : `var(--m-${worst})`};stroke-width:3"/>` +
      `<text x="${c}" y="${c + 4}" text-anchor="middle" style="fill:#363236;font:600 11.5px var(--font);letter-spacing:-0.02em">` +
      `<tspan style="font-size:8px">${LEVEL[worst].glyph}</tspan><tspan dx="0.5">${n}</tspan></text>` + badge };
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

  // ---------------------------------------------------------------- 배경 지도: 벡터(OpenFreeMap) → 래스터(CARTO → OpenTopoMap + 회색 필터) → 평면 지도
  const TILES = [
    { name: "vector", vector: true, url: "__VECTOR_STYLE__", attribution: '__VECTOR_ATTRIBUTION__' },
    { name: "carto", url: "__TILE_URL__", sub: "__TILE_SUBDOMAINS__", maxNative: __TILE_MAX_NATIVE_ZOOM__, attribution: '__TILE_ATTRIBUTION__' },
    { name: "topo", url: "__TILE_FALLBACK_URL__", sub: "__TILE_FALLBACK_SUBDOMAINS__", maxNative: __TILE_FALLBACK_MAX_NATIVE_ZOOM__,
      attribution: '__TILE_FALLBACK_ATTRIBUTION__' },
  ];
  // VWorld(국토교통부) 키가 있으면 벡터 지도 다음에 한국 일반 지도를 둔다 (회색 필터로 디자인 색에 맞춤).
  // 위성 지도·3D 지도는 VWorld만 쓴다
  const VWORLD = DATA.vworld_key ? `https://api.vworld.kr/req/wmts/1.0.0/${encodeURIComponent(DATA.vworld_key)}` : "";
  const VWORLD_ATTR = '&copy; <a href="https://www.vworld.kr">VWorld</a> (국토교통부)';
  if (VWORLD) TILES.splice(1, 0, { name: "vworld", url: `${VWORLD}/Base/{z}/{y}/{x}.png`, sub: "", maxNative: 19, attribution: VWORLD_ATTR });
  state.tileIdx = 0;          // 지금 쓰는 제공처 (지도 세 개가 함께 쓴다)
  state.tileChecks = {};      // 제공처별 확인 결과 (Promise<boolean>)
  root.dataset.tiles = TILES[0].name;
  const tileLayer = (maxZoom) => {
    const t = TILES[state.tileIdx];
    root.dataset.tiles = t.name;  // OpenTopoMap이면 CSS가 회색 필터를 건다
    return L.tileLayer(t.url, { subdomains: t.sub, maxNativeZoom: t.maxNative, maxZoom, attribution: t.attribution });
  };
  // 일반 지도 / 위성 지도 전환 (VWorld 키가 있을 때). 위성은 VWorld 영상 + 도로·지명 겹침, 바탕 지도 위에 덮는다
  state.satellite = false;
  const satMaps = [];
  function addSatelliteToggle(map, position, with3d) {
    if (!VWORLD) return;
    if (!map.getPane("sat")) map.createPane("sat").style.zIndex = 250;  // 바탕 지도(200) 위, 표시(400) 아래
    const sat = L.layerGroup([
      L.tileLayer(`${VWORLD}/Satellite/{z}/{y}/{x}.jpeg`, { pane: "sat", maxNativeZoom: 19, maxZoom: 22, attribution: VWORLD_ATTR }),
      L.tileLayer(`${VWORLD}/Hybrid/{z}/{y}/{x}.png`, { pane: "sat", maxNativeZoom: 19, maxZoom: 22 }),
    ]);
    const ctl = L.control({ position });
    ctl.onAdd = () => {
      const box = L.DomUtil.create("div", "leaflet-bar maptype");
      box.style.cssText = "display:flex;overflow:hidden;border-radius:999px;background:var(--ctl-bg,#fff);font:600 12px/1 inherit";
      const mk = (label, on) => {
        const b = L.DomUtil.create("button", "", box);
        b.type = "button";
        b.textContent = label;
        b.style.cssText = "border:0;padding:8px 12px;cursor:pointer;font:inherit;background:transparent;color:#333";
        L.DomEvent.on(b, "click", (ev) => { L.DomEvent.stop(ev); setSatellite(on); });
        return b;
      };
      const normal = mk("일반 지도", false), satellite = mk("위성 지도", true);
      if (with3d) {
        const b3 = L.DomUtil.create("button", "", box);
        b3.type = "button";
        b3.textContent = "3D 지도";
        b3.style.cssText = "border:0;border-left:1px solid #e2e2e2;padding:8px 12px;cursor:pointer;font:inherit;background:transparent;color:#333";
        L.DomEvent.on(b3, "click", (ev) => { L.DomEvent.stop(ev); open3d(true); });
      }
      satMaps.push({ map, sat, normal, satellite });
      L.DomEvent.disableClickPropagation(box);
      return box;
    };
    ctl.addTo(map);
    setSatellite(state.satellite);
  }
  // VWorld 3D 지도 (map3d.html, 같은 폴더): 화면 전체에 띄운다. 새로고침(실시간 갱신)되어도 열린 상태를 유지
  function open3d(on) {
    let ov = document.getElementById("map3d-overlay");
    try { sessionStorage.setItem("stepmap-3d", on ? "1" : "0"); } catch (e) {}
    if (!on) { if (ov) ov.remove(); return; }
    if (ov) return;
    ov = document.createElement("div");
    ov.id = "map3d-overlay";
    ov.style.cssText = "position:fixed;inset:0;z-index:99999;background:#1f1c1f";
    const fr = document.createElement("iframe");
    fr.src = "map3d.html";
    fr.title = "3D 지도";
    fr.style.cssText = "border:0;width:100%;height:100%";
    const close = document.createElement("button");
    close.type = "button";
    close.textContent = "2D 지도로 돌아가기";
    close.style.cssText = "position:absolute;right:12px;bottom:24px;z-index:2;border:0;border-radius:999px;padding:10px 16px;" +
                          "font:600 13px/1 inherit;background:#2f2a2f;color:#fff;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.3)";
    close.onclick = () => open3d(false);
    ov.append(fr, close);
    document.body.append(ov);
  }
  try { if (VWORLD && sessionStorage.getItem("stepmap-3d") === "1") setTimeout(() => open3d(true), 0); } catch (e) {}
  function setSatellite(on) {
    state.satellite = on;
    for (const m of satMaps) {
      if (on) m.sat.addTo(m.map); else m.sat.remove();
      m.normal.style.background = on ? "transparent" : "#2f2a2f";
      m.normal.style.color = on ? "#333" : "#fff";
      m.satellite.style.background = on ? "#2f2a2f" : "transparent";
      m.satellite.style.color = on ? "#fff" : "#333";
    }
  }
  // 벡터 지도 색 (Python VECTOR_PALETTE): positron 스타일을 받아 층마다 색을 덮어쓴다
  const MAP_COLORS = __MAP_COLORS__;
  let baseStyle = null;
  function vectorStyle(mode) {
    if (!baseStyle) baseStyle = fetch(TILES.find((t) => t.vector).url).then((r) => { if (!r.ok) throw new Error(`http ${r.status}`); return r.json(); });
    return baseStyle.then((st) => recolorStyle(st, MAP_COLORS[mode] || MAP_COLORS.light));
  }
  // 줌에 따라 바뀌는 값(interpolate·step)은 단계별 값에 곱한다 (["zoom"]은 맨 바깥 식에서만 쓸 수 있어 식째 곱할 수 없다)
  function scaleZoomValue(v, f) {
    if (typeof v === "number") return v * f;
    if (!Array.isArray(v)) return v;
    if (v[0] === "interpolate") return v.map((x, i) => (i >= 4 && i % 2 === 0 && typeof x === "number" ? x * f : x));
    if (v[0] === "step") return v.map((x, i) => (i >= 2 && i % 2 === 0 && typeof x === "number" ? x * f : x));
    return v;
  }
  function recolorStyle(src, c) {
    const st = JSON.parse(JSON.stringify(src));
    const NAME = ["coalesce", ["get", "name:ko"], ["get", "name"]];  // 한국어 이름 우선
    const has = (id, ...words) => words.some((w) => id.includes(w));
    // 도로 번호 방패, 골목·작은 도로 이름 숨김
    st.layers = st.layers.filter((l) => !has(l.id, "shield") && l.id !== "highway-name-path" && l.id !== "highway-name-minor");
    for (const l of st.layers) {
      const pt = (l.paint = l.paint || {}), lay = (l.layout = l.layout || {}), id = l.id, sl = l["source-layer"];
      if (l.type === "background") pt["background-color"] = c.land;
      else if (id === "landuse_residential") { pt["fill-color"] = c.land; pt["fill-opacity"] = 1; }
      else if (id === "park") { pt["fill-color"] = c.park; pt["fill-opacity"] = 1; }
      else if (sl === "landcover" && has(id, "wood", "grass")) { pt["fill-color"] = c.wood; pt["fill-opacity"] = c.wood_opacity; }
      else if (sl === "landcover") pt["fill-color"] = c.land;
      else if (id === "water") { pt["fill-color"] = c.water; pt["fill-antialias"] = false; }  // 물가 선 없음
      else if (id === "waterway") pt["line-color"] = c.water;
      else if (id === "building") { pt["fill-color"] = c.building; pt["fill-outline-color"] = c.building; }
      else if (l.type === "line" && (sl === "transportation" || sl === "aeroway")) {
        pt["line-color"] = has(id, "casing", "railway") ? c.casing : c.road;  // 도로는 모든 등급 같은 색, 테두리·철도는 옅은 회색
        if ("line-opacity" in pt) pt["line-opacity"] = 1;
        if (has(id, "major", "motorway", "runway") && pt["line-width"] != null) pt["line-width"] = scaleZoomValue(pt["line-width"], 1.25);  // 큰 도로는 조금 더 굵게
      }
      else if (l.type === "fill" && (sl === "transportation" || sl === "aeroway")) pt["fill-color"] = c.road;
      else if (l.type === "line" && sl === "boundary") pt["line-color"] = c.casing;
      else if (l.type === "symbol") {
        delete lay["icon-image"];  // 아이콘 숨김
        if (lay["text-field"]) lay["text-field"] = NAME;
        if (lay["text-size"] != null) lay["text-size"] = 11;  // 글자 작게 (11px)
        if (id === "highway-name-major") l.minzoom = 15;      // 큰 도로 이름은 줌 15 이상
        if (id === "label_other") l.minzoom = 14;              // 동 이름은 줌 14 이상
        pt["text-color"] = c.label;
        pt["text-halo-color"] = c.land;
        pt["text-halo-width"] = 1;
        delete pt["text-halo-blur"];
      }
    }
    return st;
  }
  // <img> 타일은 오류 상태(403 "Access blocked")나 대체 이미지("API KEY REQUIRED" 워터마크, 200 응답)를 그대로 그려
  // tileerror가 나지 않는다. 지도 중심과 그 옆 타일을 직접 받아 상태코드를 보고, 두 장의 내용이 똑같으면 대체 이미지로 본다.
  function checkTiles(map) {
    const idx = state.tileIdx;
    if (state.tileChecks[idx]) return state.tileChecks[idx];
    const t = TILES[idx];
    const z = Math.min(map.getZoom(), t.maxNative), c = map.project(map.getCenter(), z).divideBy(256).floor();
    const tileUrl = (x, y) => L.Util.template(t.url, { s: t.sub[0], z, x, y, r: "" });
    const same = (a, b) => {
      if (a.byteLength !== b.byteLength) return false;
      const u = new Uint8Array(a), w = new Uint8Array(b);
      for (let i = 0; i < u.length; i++) if (u[i] !== w[i]) return false;
      return true;
    };
    state.tileChecks[idx] = Promise.all([fetch(tileUrl(c.x, c.y)), fetch(tileUrl(c.x + 1, c.y))])
      .then(async ([a, b]) => {
        state.tiles.probe = a.ok ? b.status : a.status;
        if (!a.ok || !b.ok) return `http ${state.tiles.probe}`;
        return same(await a.arrayBuffer(), await b.arrayBuffer()) ? "placeholder" : null;
      })
      .catch(() => { state.tiles.probe = "network"; return "network"; });
    return state.tileChecks[idx];
  }
  // 지도 하나에 타일을 붙인다. 지금 제공처가 안 되면(확인 실패·한 장도 못 받고 실패 4번·10초 동안 0장) 다음 제공처,
  // 마지막 제공처도 안 되면 onPlane(이유). alive(): 그 지도가 아직 쓰이는지
  // modeOf(): 그 지도의 밝기 ("light" | "dark", 벡터 지도 색)
  function attachTiles(map, maxZoom, alive, onPlane, modeOf = () => "light") {
    let layer = null, loaded = 0, failed = 0, timer = 0, attempt = 0;
    const next = (reason, at) => {
      if (at !== attempt || !alive()) return;
      clearTimeout(timer);
      if (state.tileIdx < TILES.length - 1) { state.tileIdx++; use(); } else onPlane(reason);
    };
    const use = () => {
      const at = ++attempt;
      if (layer) layer.remove();
      layer = null;
      loaded = failed = 0;
      clearTimeout(timer);
      if (TILES[state.tileIdx].vector) {
        root.dataset.tiles = "vector";
        // 라이브러리·스타일을 못 받거나, 타일 오류가 이어지거나, 12초 동안 타일이 하나도 안 오면 다음 제공처
        if (!window.maplibregl || !L.maplibreGL) { next("vector-lib", at); return; }
        timer = setTimeout(() => { if (!loaded) next("timeout", at); }, 12000);
        vectorStyle(modeOf()).then((style) => {
          if (at !== attempt || !alive()) return;
          // 저작자 표시: 스타일 소스 문구 대신 "© OpenFreeMap © OpenMapTiles © OpenStreetMap contributors"
          layer = L.maplibreGL({ style, attributionControl: { customAttribution: TILES[state.tileIdx].attribution },
                                 localIdeographFontFamily: '"Pretendard Variable", "Malgun Gothic", "Apple SD Gothic Neo", sans-serif' });
          layer.addTo(map);
          const ml = layer.getMaplibreMap();
          ml.on("data", (ev) => { if (ev.dataType === "source" && ev.tile) { loaded++; if (map === state.map) state.tiles.loaded++; } });
          ml.on("error", () => { failed++; if (map === state.map) state.tiles.failed++; if (!loaded && failed >= 4) next("vector-error", at); });
        }).catch(() => next("style", at));
        return;
      }
      layer = tileLayer(maxZoom);
      layer.on("tileload", () => { loaded++; if (map === state.map) state.tiles.loaded++; });
      layer.on("tileerror", () => { failed++; if (map === state.map) state.tiles.failed++; if (!loaded && failed >= 4) next("tileerror", at); });
      layer.addTo(map);
      checkTiles(map).then((bad) => { if (bad) next(bad, at); });
      timer = setTimeout(() => { if (!loaded) next("timeout", at); }, 10000);
    };
    use();
    // 지도 밝기를 바꾸면 벡터 지도는 그 색의 스타일로 다시 칠한다
    state.themeHooks.push(() => {
      if (!alive() || !layer || !layer.getMaplibreMap || !TILES[state.tileIdx].vector) return;
      vectorStyle(modeOf()).then((style) => { if (layer && layer.getMaplibreMap) layer.getMaplibreMap().setStyle(style); });
    });
  }

  // ---------------------------------------------------------------- 종합 현황 지도 (Leaflet)
  let markerLayer = null;
  function startTiles() {
    const gen = ++state.gen;
    const map = L.map("map", { zoomControl: false });
    L.control.zoom({ position: "bottomright" }).addTo(map);  // 왼쪽 위는 로고·필터 카드 자리
    addSatelliteToggle(map, "bottomright", true);
    state.map = map;
    state.mode = "tiles";
    $("map-attr").append(map.attributionControl.getContainer());  // 화면 가장 아래 오른쪽 구석 (지도를 지우면 같이 지워진다)

    // 이동 경로는 그리지 않는다. 지도 범위는 전체 측정 지점 기준으로 처음 한 번만 맞춘다
    // (판정 필터를 바꿔도 움직이지 않는다). 지점이 없을 때만 경로 범위를 쓴다
    const bounds = L.latLngBounds(DATA.events.length ? DATA.events.map((e) => [e.lat, e.lon]) : DATA.trajectory);
    if (ROBOT_LL) bounds.extend(ROBOT_LL);
    // 떠 있는 카드에 마커가 가려지지 않게 카드 높이·폭만큼 여백을 두고 맞춘다
    const pad = homePadding();
    // maxZoom: 지점·경로가 한 점뿐일 때(로봇이 서 있는 실시간 첫 화면) 타일이 없는 배율까지 확대되지 않게
    map.fitBounds(bounds, { paddingTopLeft: pad.tl, paddingBottomRight: pad.br, animate: false, maxZoom: 19 });
    // 로봇개 마커: 로봇의 마지막 위치 (경로 선은 그리지 않는다)
    if (ROBOT_LL) {
      const robot = L.marker(ROBOT_LL, { icon: L.divIcon({ className: "robot-mk", iconSize: [36, 36], iconAnchor: [18, 18],
                                             html: `<span class="pulse"></span><span class="core"><svg viewBox="0 0 24 24" aria-hidden="true">${ROBOT_PATH}</svg></span>` }),
                           keyboard: true, zIndexOffset: 5000, title: "로봇 마지막 위치" }).addTo(map);
      robot.on("click", openRobotCard);  // 로봇개를 누르면 가장 최근에 찾은 위험 지점(없으면 주의)
      window.stepmapMoveRobot = (ll) => robot.setLatLng(ll);  // 실시간(live): 다시 그리지 않고 로봇 위치만 옮긴다
      robot.getElement().setAttribute("role", "button");
      robot.getElement().setAttribute("aria-label", "로봇 마지막 위치: 가장 최근에 찾은 위험 지점 보기");
    }
    map.on("zoomstart", () => { state.spider = null; });
    // 빈 곳을 누르면 펼친 묶음을 접고, 지점 블록이 열려 있으면 닫는다
    map.on("click", () => { if (state.spider) { state.spider = null; renderMap(); } else if (state.sel) closePanel(); });
    map.on("zoomend", renderMap);
    renderMap();

    // 타일: 지도 범위를 정한 뒤 붙인다 (제공처 확인이 지도 중심 타일을 받는다)
    attachTiles(map, 19, () => gen === state.gen && state.mode === "tiles", (reason) => fallback(reason), () => $("mapcard").dataset.map);
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
          icon: L.divIcon({ className: `ev-marker ev-${homeShape(lead)}`, iconSize: [24, 24], iconAnchor: [12 - g.dx, 12 - g.dy],
                            html: homeMarkerSvg(lead, sel, leader(g, 12, 12)) }),
          zIndexOffset: sel ? 1000 : LEVEL[lead.level].z,
        });
        m.on("click", () => pick(lead));
      } else {
        const p = pill(g.members, groupSelected(g));
        m = L.marker([lead.lat, lead.lon], {
          icon: L.divIcon({ className: "ev-cluster", iconSize: [p.w, p.w], iconAnchor: [p.w / 2 - g.dx, p.w / 2 - g.dy],
                            html: `<svg width="${p.w}" height="${p.w}" viewBox="0 0 ${p.w} ${p.w}" aria-hidden="true">${leader(g, p.w / 2, p.w / 2)}${p.svg}</svg>` }),
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
        icon: L.divIcon({ className: `ev-marker ev-${homeShape(e)}`, iconSize: [24, 24], iconAnchor: [12 - one.dx, 12 - one.dy],
                          html: homeMarkerSvg(e, isSel(e), leader(one, 12, 12)) }),
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
    state.tileIdx = 0;      // 다시 불러오기는 첫 제공처(벡터 지도)부터
    state.tileChecks = {};
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
    // 빈 곳을 누르면 지점 블록을 닫는다 (마커·로봇개는 각자 처리)
    box.addEventListener("click", (ev) => { if (!ev.target.closest(".ev, .robot") && state.sel) closePanel(); });
    const NS = "http://www.w3.org/2000/svg";
    // 범위: 전체 측정 지점 기준 (판정 필터와 무관). 지점이 없을 때만 경로 범위
    const pts = (DATA.events.length ? DATA.events.map((e) => [e.x, e.y]) : DATA.trajectory_xy).concat(ROBOT_XY ? [ROBOT_XY] : []);
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);

    function niceStep(raw) {
      const p = Math.pow(10, Math.floor(Math.log10(raw)));
      for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= raw) return m * p;
      return 10 * p;
    }

    function draw() {
      if (state.mode !== "plane") return;
      // 떠 있는 카드 자리(위·아래·왼쪽)를 비운다 (Leaflet 지도와 같은 여백)
      const W = box.clientWidth, H = box.clientHeight, P = homePadding();
      const [padL, padT] = P.tl, [padR, padB] = P.br;
      if (W <= padL + padR + 40 || H <= padT + padB + 40) return;  // 크기가 잡히기 전(레이아웃 전환 중)에는 건너뛴다
      const s = Math.min((W - padL - padR) / Math.max(maxX - minX, 1), (H - padT - padB) / Math.max(maxY - minY, 1));
      const ox = padL + (W - padL - padR - (maxX - minX) * s) / 2, oy = padT + (H - padT - padB - (maxY - minY) * s) / 2;
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
      // 축척·좌표 안내: 아래 카드 줄 위 오른쪽
      const bx = W - padR - Math.max(barPx, 150), by = H - padB + 28;
      const bar = `<g transform="translate(${bx.toFixed(1)},${by.toFixed(1)})" fill="${mapCss("--map-text")}" font-size="12">` +
                  `<rect width="${barPx}" height="4" y="-4"/><text y="-10">${barM} m · odom 좌표 · 격자 ${step} m</text></g>`;

      box.innerHTML = `<svg xmlns="${NS}" width="${W}" height="${H}">` +
        `<g stroke="${mapCss("--map-grid")}" stroke-width="2">${g}</g>` + bar + `</svg>`;

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
          node.setAttribute("class", `ev ev-${homeShape(e)}`);
          node.setAttribute("transform", `translate(${(grp.x + grp.dx - 12).toFixed(1)},${(grp.y + grp.dy - 12).toFixed(1)})`);
          node.innerHTML = leader(grp, 12, 12) + `<rect class="hit" x="-2" y="-2" width="28" height="28" rx="6" fill="transparent"/>` + homeMarkerInner(e, isSel(e));
          activate = () => pick(e);
        } else {
          const p = pill(grp.members, groupSelected(grp));
          node.setAttribute("transform", `translate(${(grp.x + grp.dx - p.w / 2).toFixed(1)},${(grp.y + grp.dy - p.w / 2).toFixed(1)})`);
          node.innerHTML = leader(grp, p.w / 2, p.w / 2) + `<rect class="hit" x="-2" y="-2" width="${p.w + 4}" height="${p.w + 4}" rx="${p.w / 2 + 2}" fill="transparent"/>` + p.svg;
          const members = grp.members;
          activate = () => showPicker(members, node.getBoundingClientRect());
        }
        node.addEventListener("click", activate);
        wire(node, tipContent(grp.members), activate, photoNote(grp.members));
        layer.append(node);
      }
      if (ROBOT_XY) {  // 로봇개 마커 (Leaflet 지도와 같은 모양)
        const rb = document.createElementNS(NS, "g");
        rb.setAttribute("class", "robot");
        rb.setAttribute("transform", `translate(${(X(ROBOT_XY[0]) - 18).toFixed(1)},${(Y(ROBOT_XY[1]) - 18).toFixed(1)})`);
        rb.setAttribute("role", "button");
        rb.setAttribute("tabindex", "0");
        rb.setAttribute("aria-label", "로봇 마지막 위치: 가장 최근에 찾은 위험 지점 보기");
        rb.addEventListener("click", openRobotCard);
        rb.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); openRobotCard(); } });
        rb.innerHTML = `<circle class="robot-pulse" cx="18" cy="18" r="18" style="fill:rgb(54 50 54 / 0.28)"/>` +
                       `<circle cx="18" cy="18" r="17" style="fill:#363236;stroke:#FFFFFF;stroke-width:2"/>` +
                       `<svg x="6" y="6" width="24" height="24" viewBox="0 0 24 24" style="color:#FFFFFF">${ROBOT_PATH}</svg>`;
        layer.append(rb);
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

  // 화면은 라이트, 지도는 밝은 지도로 고정 (<html data-theme="light">, #mapcard data-map="light")

  // ---------------------------------------------------------------- 위쪽 바: 마지막 점검 날짜 (마우스를 올리면 측정 시간·구간·로봇)
  if (DATA.t0 != null) {
    const d = $("tb-date"), pt = tparts(DATA.t0);
    d.append(el("span", "k", "마지막 점검 "), el("b", null, `${pt.year}.${pt.month}.${pt.day}`));
    d.setAttribute("title", [`측정 ${fmtDateTime(DATA.t0)} ~ ${fmtHM(DATA.t1)}`, DATA.area, DATA.robot].filter(Boolean).join(" · "));
  }

  // ---------------------------------------------------------------- KPI 공용 계산 (종합 현황 · 점검 이력이 같은 함수를 쓴다)
  const countLevel = (list, lv) => list.filter((e) => e.level === lv).length;
  // 점검 거리: 반올림은 화면에서 한 번만 (신고서와 같은 값). meters가 없으면 —
  function putDistance(node, meters) {
    node.replaceChildren();
    if (meters == null) { node.textContent = "—"; return; }
    node.textContent = Math.round(meters).toLocaleString("ko-KR");
    node.append(el("small", null, "m"));
  }
  for (const l of document.querySelectorAll(".kpi .label")) l.setAttribute("title", l.textContent.replace(/\s+/g, " ").trim());

  // ---------------------------------------------------------------- 종합 현황: 범례 (판정 필터 버튼 + 회색 모양 범례)
  function setShown(lv, on) {
    shown[lv] = on;
    if (!on && state.page === "home" && state.sel && byId[state.sel.id].level === lv) closePanel();  // 선택된 지점을 숨기면 패널도 닫는다
    for (const b of levelBtns) b.setAttribute("aria-pressed", String(shown[b.dataset.level]));
    $("map-empty").hidden = LEVELS.some((l) => shown[l]);
    state.spider = null;  // 펼친 묶음은 구성이 바뀌므로 접는다. 지도 범위는 그대로
    renderMap();
  }
  {
    for (const b of levelBtns) b.addEventListener("click", () => setShown(b.dataset.level, !shown[b.dataset.level]));
    $("map-empty").hidden = LEVELS.some((l) => shown[l]);
  }

  // ---------------------------------------------------------------- 현장 사진 (검사 결과 상세·종합 현황 패널에서 사용)
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

  // ---------------------------------------------------------------- 검사 결과 (노면 형상 + 흔들림)
  // 목록: 탭(전체/노면 형상/흔들림) × 판정 칩(처음 위험·주의). 정렬은 위험→주의→정상, 같은 판정은 ratio 큰 순
  const byIssueOrder = (a, b) => LEVEL[b.level].rank - LEVEL[a.level].rank || b.ratio - a.ratio || a.t - b.t;
  const D_TABS = [["all", "전체"], ["surface", "노면 형상"], ["loose", "흔들림"]];
  const levelChips = [...document.querySelectorAll("#d-levels .lv-btn")];
  const D = { tab: "all", levels: Object.fromEntries(levelChips.map((b) => [b.dataset.level, b.getAttribute("aria-pressed") === "true"])),
              redraw: null, scrollToDetail: false };
  const inTab = (e, tab) => tab === "all" || (tab === "loose") === (e.kind === "loose");
  const detailAll = [...DATA.events].sort(byIssueOrder);
  const detailShown = (tab = D.tab) => detailAll.filter((e) => inTab(e, tab) && D.levels[e.level]);
  const CATEGORY = (e) => (e.kind === "loose" ? "흔들림(발 접촉)" : "노면 형상");  // 신고서 측정 방식과 같은 분류
  // 측정 방법 (종류 + 측정 센서)
  const METHOD = {
    step:  { camera: "깊이 카메라 바닥 평면 대비 높이 차", foot: "발 접지 높이 차 (다른 발 대비)",
             "camera+foot": "깊이 카메라 바닥 평면 대비 높이 차 + 발 접지 높이 차 (교차 측정)" },
    slope: { camera: "깊이 카메라 바닥 평면 기울기" },
    crack: { camera: "RGB 영상 균열 검출 점수 (0~1)" },
    loose: { foot: "관절 각도 → 발끝 위치(정기구학), IMU 중력 정렬, 평소 걸음 대비" },
  };
  const methodText = (e) => {
    const m = (METHOD[e.kind] || {})[e.source] || e.source;
    return e.leg && e.source !== "camera" && e.kind !== "loose" ? `${m} · ${LEG[e.leg] || e.leg}(${e.leg})` : m;
  };
  const kindValue = (e) => `${KIND[e.kind].label} ${fmtValue(e)}`;
  const legName = (leg) => (leg ? `${LEG[leg] || leg}(${leg})` : "");
  const fmtDateTimeS = (t) => { const p = tparts(t); return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second}`; };
  const ratioText = (e) => (e.kind === "crack" ? "" : ` · 기준의 ${Number(e.ratio).toFixed(1)}배`);  // 균열 점수는 배수 표시 안 함
  // 흔들림은 ◆, 노면 형상은 종류 모양 (판정 색)
  const kindMark = (e) => {
    if (e.kind !== "loose") return svgIcon(e.kind, e.level);
    const d = el("span", `dia lv-c-${e.level}`, "◆");
    d.setAttribute("aria-hidden", "true");
    return d;
  };
  const confirmBadge = (e) => (e.confirm ? el("span", `cf${e.confirm === "확정" ? " sure" : ""}`, e.confirm) : null);

  // 요약 한 줄: 위험 N · 주의 N · 밟은 블록 N개 확인 (발끝 기록의 서로 다른 블록 수, events.count_stepped_blocks)
  {
    const box = $("d-summary");
    for (const lv of ["danger", "warn"]) {
      const sp = el("span", "blk"); sp.append(lvBadge(lv), document.createTextNode(` ${countLevel(DATA.events, lv)}`)); box.append(sp);
    }
    if (DATA.stepped_blocks != null) {
      const sp = el("span", "blk");
      sp.append(el("span", "dia lv-c-ok", "◆"), document.createTextNode(`밟은 블록 ${DATA.stepped_blocks.toLocaleString("ko-KR")}개 확인`));
      sp.firstChild.setAttribute("aria-hidden", "true");
      box.append(el("span", "sep"), sp);
    }
  }
  for (const b of levelChips) {
    b.addEventListener("click", () => {
      D.levels[b.dataset.level] = !D.levels[b.dataset.level];
      b.setAttribute("aria-pressed", String(D.levels[b.dataset.level]));
      refreshDetailSelection();
    });
  }
  function selectDetail(id) {
    D.scrollToDetail = narrow.matches;  // 좁은 화면: 목록 아래 상세로 내려간다
    location.replace(`#detail/${id}`);  // 같은 페이지 안 선택은 방문 기록을 쌓지 않는다
  }
  // 탭·칩을 바꾼 뒤: 선택이 목록에서 빠졌으면 첫 지점을 고른다
  function refreshDetailSelection() {
    const list = detailShown();
    if (state.sel && list.some((e) => e.id === state.sel.id)) renderDetailPage();
    else if (list.length) selectDetail(list[0].id);
    else { state.sel = null; renderDetailPage(); }
  }
  function renderDetailTabs() {
    const box = $("d-tabs");
    box.replaceChildren();
    for (const [k, label] of D_TABS) {
      const b = el("button");
      b.type = "button";
      b.dataset.tab = k;
      b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", String(D.tab === k));
      b.append(el("span", null, label), el("span", "n", String(detailShown(k).length)));
      b.addEventListener("click", () => { D.tab = k; refreshDetailSelection(); });
      box.append(b);
    }
    for (const lv of LEVELS) $(`d-n-${lv}`).textContent = detailAll.filter((e) => inTab(e, D.tab) && e.level === lv).length;
  }
  function renderDetailList() {
    const box = $("d-list");
    box.replaceChildren();
    const list = detailShown();
    if (!list.length) { box.append(el("div", "v-empty", "조건에 맞는 지점이 없습니다")); return; }
    for (const e of list) {
      const b = el("button", `d-row lv-c-${e.level}`);
      b.type = "button";
      b.setAttribute("role", "option");
      b.setAttribute("aria-selected", String(isSel(e)));
      const dot = el("span", "lvd");
      dot.setAttribute("aria-hidden", "true");
      const what = el("span", "what");
      what.append(el("span", null, KIND[e.kind].label), el("span", "val", fmtValue(e)));
      const cf = confirmBadge(e);
      b.append(dot, kindMark(e), what, cf || el("span"), el("span", "why", `${criterion(e)}${ratioText(e)}`));
      b.setAttribute("aria-label", `${LEVEL[e.level].label} ${kindValue(e)}${e.confirm ? ` ${e.confirm}` : ""}, 기준 ${criterion(e)}${ratioText(e)}`);
      b.addEventListener("click", () => selectDetail(e.id));
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
      const items = [[`평소 걸음 범위 (${tr.n}걸음)`, "band"], ["평소 걸음 평균", "mean"], [`이번 걸음 (${flagged ? "기준 초과" : "정상 범위"})`, "step"]];
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
    D.redraw = draw;
    requestAnimationFrame(draw);
    return fig;
  }
  addEventListener("resize", () => { if (state.page === "detail" && D.redraw) requestAnimationFrame(D.redraw); });

  function card(k, v, s, cls) {
    const c = el("div", `v-card${cls ? ` ${cls}` : ""}`);
    c.append(el("div", "k", k), el("div", "v", v));
    if (s) c.append(el("div", "s", s));
    return c;
  }

  function renderDetailCard() {
    const box = $("d-detail");
    box.replaceChildren();
    D.redraw = null;
    const e = state.sel && byId[state.sel.id];
    if (!e) { box.append(el("p", "v-empty", "목록에서 지점을 고르세요")); return; }
    const loose = e.kind === "loose";
    // 공통: 판정 배지 + 종류 + id
    const head = el("div", "v-head");
    const kind = el("span", "kind");
    kind.append(lvBadge(e.level), kindMark(e), el("span", null, KIND[e.kind].label), el("span", "id", e.id));
    const cf = confirmBadge(e);
    if (cf) kind.append(cf);
    const inReport = e.level !== "ok";
    head.append(kind, el("span", `rep${inReport ? " in" : ""}`, inReport ? "신고서에 포함됨" : "신고서 대상 아님 (정상)"));
    box.append(head);

    // 사진 (흔들림은 image_mark 점선 동그라미). 누르면 크게 보기, 없으면 사진 자리에 안내만
    if (e.photo) box.append(photoFigure(e));
    else { const np = el("div", "no-photo"); np.append(svgIcon(e.kind, null), el("span", null, "사진 없음")); box.append(np); }

    // 측정값(크게) + 근거 (criterion_text, exceed_ratio)
    const big = el("div", "v-big");
    big.append(el("span", "num", fmtNum(e.value, e.unit)),
               el("span", "unit", e.unit === "score" ? "균열 점수 (0~1)" : loose ? `${UNIT[e.unit]} 추가 침하` : UNIT[e.unit]));
    const crit = el("p", "v-crit");
    crit.append(el("span", "k", "기준 "), document.createTextNode(criterion(e)));
    if (ratioText(e)) crit.append(el("span", "x", ratioText(e)));
    box.append(big, crit);

    if (e.source === "camera+foot") {  // 노면 형상: 카메라·발 교차 측정
      const d = Number(e.value_foot) - Number(e.value);
      const cards = el("div", "v-cards");
      cards.append(card("카메라", fmtValue(e)),
                   card(`발 · ${legName(e.leg)}`, fmtFoot(e)),
                   card("두 측정 차이", `${Math.abs(d).toFixed(1)}${UNIT[e.unit]}`, d === 0 ? "두 값 같음" : `발 측정이 ${d > 0 ? "더 큼" : "더 작음"}`, "diff"));
      box.append(cards);
    }
    if (loose) {  // 흔들림: 밟은 횟수 · 추가 침하 · 확정/의심 + 발끝 높이 그래프
      const steps = e.steps || [];
      const n = Math.max(steps.length, 1);
      const cards = el("div", "v-cards");
      cards.append(card("밟은 횟수", `${n}회`, steps.length ? steps.map((x) => `${x.leg} ${x.extra.toFixed(1)}mm`).join(" · ") : legName(e.leg)),
                   card("추가 침하", `${fmtNum(e.value, e.unit)}mm`, `기준 ${DATA.thresholds.loose[0]}mm 이상이면 흔들림`),
                   card("판정", e.confirm || "정상", e.confirm === "확정" ? "2걸음 이상 기준 초과" : e.confirm === "의심" ? "1걸음만 기준 초과" : "기준 초과 걸음 없음",
                        e.confirm ? "diff" : ""));
      box.append(cards, footGraph(e));
    }

    // 공통: 위치·측정 시각·측정 방식 (+ 메모·신뢰도·다리)
    const basis = el("section", "v-basis");
    basis.append(el("h2", null, "측정 근거"));
    const dl = el("dl");
    const row = (k, v) => dl.append(el("dt", null, k), el("dd", null, v));
    row("위도·경도", `${Number(e.lat).toFixed(6)}, ${Number(e.lon).toFixed(6)}`);
    row("측정 시각", fmtDateTimeS(e.t));
    row("측정 방식", `${CATEGORY(e)} · ${methodText(e)}`);
    if (loose) {
      row("측정 다리", legName(e.leg) || "—");
      row("평소 걸음 수", e.trace ? `${e.trace.n}걸음` : "—");
    } else {
      row("신뢰도", Number(e.confidence).toFixed(2));
    }
    row("메모", e.note || "—");
    basis.append(dl);
    box.append(basis);

    if (loose) {  // 흔들림: 1m 안의 노면 형상 이상과 비교 (카메라로는 안 보이는 흔들림인지)
      const near = el("section", "d-near");
      near.append(el("h2", null, "주변 노면 형상 비교"));
      const ids = e.near_visual || [];
      if (!ids.length) near.append(el("p", null, "1m 안에 노면 형상 이상 없음 · 카메라로는 이상 없음"));
      else {
        const ul = el("ul");
        for (const i of ids) {
          const o = byId[i], a = el("a", null, `${kindValue(o)} · ${LEVEL[o.level].label} (${o.id})`);
          a.href = detailHref(o);
          const li = el("li"); li.append(a); ul.append(li);
        }
        near.append(el("p", null, "1m 안의 노면 형상 이상:"), ul);
      }
      box.append(near);
    }

    const act = el("div", "v-actions");
    const toMap = el("button", "btn primary", "지도에서 위치 보기");
    toMap.type = "button";
    toMap.addEventListener("click", () => { location.hash = `#home/${e.id}`; });
    act.append(toMap);
    box.append(act);
  }

  // 상세 아래 작은 위치 지도: 선택한 지점(크게) + 같은 날 다른 지점(작은 점). 타일을 못 받으면 평면 그림
  const DM = { mode: null, map: null, layer: null, tiles: { loaded: 0, failed: 0 } };
  // 밟은 블록 칸 (검사 범위): 선택 지점 둘레 BLOCK_NEAR_M 안의 칸 모서리 [x0, y0, x1, y1] (odom)
  const BLOCK_NEAR_M = 30;
  function nearBlocks(e) {
    const B = DATA.blocks;
    if (!B) return [];
    const out = [];
    for (const [i, j] of B.ij) {
      const x0 = i * B.size, y0 = j * B.size;
      if (Math.abs(x0 - e.x) <= BLOCK_NEAR_M && Math.abs(y0 - e.y) <= BLOCK_NEAR_M) out.push([x0, y0, x0 + B.size, y0 + B.size]);
    }
    return out;
  }
  const xyToLatLng = (x, y) => { const g = DATA.blocks.geo; return [g[0] + g[1] * x + g[2] * y, g[3] + g[4] * x + g[5] * y]; };
  function drawDetailMap() {
    const e = state.sel && byId[state.sel.id];
    if ($("page-detail").hidden) return;
    $("d-loc-sub").textContent = e ? `${Number(e.lat).toFixed(6)}, ${Number(e.lon).toFixed(6)}${DATA.blocks ? " · 회색 칸 = 밟은 블록 (검사 범위)" : ""}` : "";
    if (!DM.mode) {
      if (!window.L || state.mode === "plane" || HM.mode === "plane") DM.mode = "plane";
      else {
        DM.mode = "tiles";
        const map = L.map("d-map", { zoomControl: true, scrollWheelZoom: false, maxZoom: 22 });
        map.attributionControl.setPosition("bottomright");
        addSatelliteToggle(map, "bottomleft");
        DM.map = map;
        DM.pendingTiles = true;  // 타일은 선택 지점으로 범위를 정한 뒤 붙인다
      }
    }
    $("d-map").hidden = DM.mode !== "tiles";
    $("d-plane").hidden = DM.mode !== "plane";
    if (DM.mode === "plane") { drawDetailPlane(e); return; }
    if (!e) return;
    const map = DM.map;
    map.invalidateSize({ animate: false });
    map.setView([e.lat, e.lon], 21, { animate: false });  // 0.3 m 칸이 약 5 px로 보이는 배율
    if (DM.pendingTiles) {
      DM.pendingTiles = false;
      attachTiles(map, 22, () => DM.map === map, () => detailPlane());
    }
    if (DM.layer) DM.layer.remove();
    DM.layer = L.layerGroup().addTo(map);
    if (DATA.blocks && DATA.blocks.geo) {  // 밟은 블록: 옅은 회색 칸들을 도형 하나로 (마커보다 아래)
      const rings = nearBlocks(e).map(([x0, y0, x1, y1]) => [xyToLatLng(x0, y0), xyToLatLng(x1, y0), xyToLatLng(x1, y1), xyToLatLng(x0, y1)]);
      if (rings.length) L.polygon(rings, { className: "d-blk", interactive: false }).addTo(DM.layer);
    }
    for (const o of DATA.events) {
      if (o.id === e.id) continue;
      L.circleMarker([o.lat, o.lon], { radius: 4, className: `d-dot d-dot-${o.level}`, interactive: false }).addTo(DM.layer);
    }
    L.marker([e.lat, e.lon], { icon: L.divIcon({ className: "ev-marker", iconSize: [24, 24],
                                                 html: `<svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">${markerInner(e, true)}</svg>` }),
                               interactive: false, keyboard: false, zIndexOffset: 1000 }).addTo(DM.layer);
  }
  function detailPlane() {
    if (DM.mode === "plane") return;
    if (DM.map) { DM.map.remove(); DM.map = null; }
    DM.mode = "plane";
    drawDetailMap();
  }
  // 평면 그림: 선택한 지점 둘레 ±DPLANE_M m (odom 좌표, 0.3 m 칸이 보이는 크기)
  const DPLANE_M = 6;
  function drawDetailPlane(e) {
    const box = $("d-plane"), W = box.clientWidth, Ht = box.clientHeight;
    box.replaceChildren();
    if (!e || W < 80 || Ht < 80) return;
    const k = Math.min(W, Ht) / (2 * DPLANE_M);
    const X = (x) => W / 2 + (x - e.x) * k, Y = (y) => Ht / 2 - (y - e.y) * k;
    let out = `<svg xmlns="${SVGNS}" width="${W}" height="${Ht}">` +
              `<text x="12" y="${Ht - 12}" style="fill:var(--map-text);font:12px var(--font)">odom 좌표 · 가로 ${Math.round(W / k)} m</text>`;
    for (const [x0, y0, x1, y1] of nearBlocks(e)) {
      out += `<rect x="${X(x0).toFixed(1)}" y="${Y(y1).toFixed(1)}" width="${((x1 - x0) * k).toFixed(1)}" height="${((y1 - y0) * k).toFixed(1)}" class="d-blk"/>`;
    }
    for (const o of DATA.events) {
      if (o.id === e.id) continue;
      const x = X(o.x), y = Y(o.y);
      if (x < -10 || x > W + 10 || y < -10 || y > Ht + 10) continue;
      out += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4" style="fill:var(--m-${o.level});stroke:var(--m-ring);stroke-width:1.5"/>`;
    }
    out += `<g transform="translate(${(W / 2 - 12).toFixed(1)},${(Ht / 2 - 12).toFixed(1)})">${markerInner(e, true)}</g></svg>`;
    box.innerHTML = out;
  }

  function renderDetailPage() {
    renderDetailTabs();
    renderDetailList();
    renderDetailCard();
    drawDetailMap();
    const e = state.sel && byId[state.sel.id];
    const row = document.querySelector('#d-list .d-row[aria-selected="true"]');
    if (row) row.scrollIntoView({ block: "nearest" });
    if (D.scrollToDetail && e) $("d-detail").scrollIntoView({ block: "start", behavior: reduceMotion.matches ? "auto" : "smooth" });
    D.scrollToDetail = false;
  }

  // ---------------------------------------------------------------- 종합 현황: 아래 블록 줄 (로봇 카드 + 지점 블록)
  // 로봇 카드는 늘 보인다. 지점 블록은 지도에서 마커를 누르거나 ← → 로 고른 때(#home/<id>)만.
  // ← →와 로봇개 누르기의 순서·지점은 Python home_cards (위험→주의, 같은 판정은 exceed_ratio 큰 순 / 가장 최근 위험 지점)
  const HOME = DATA.home || { order: [], default: null };
  const CLOSE_ICON = '<path d="M6 6l12 12M18 6 6 18" style="fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round"/>';
  const GO_ICON = '<path d="M7 17 17 7M9 7h8v8" style="fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round"/>';
  function closePanel() { location.replace("#home"); }
  const cardEvent = () => (state.sel && byId[state.sel.id]) || null;
  function openRobotCard() {
    const e = byId[HOME.default];
    if (!e) return;
    if (!shown[e.level]) setShown(e.level, true);
    pick(e);
  }
  // ← →: 이전·다음 지점 (지도 마커 누르기와 같은 동작). 아무것도 고르지 않았으면 →는 첫 지점(가장 심한 위험), ←는 마지막
  function stepPick(dir) {
    const order = HOME.order;
    if (!order.length) return;
    const i = state.sel ? order.indexOf(state.sel.id) : -1;
    const e = byId[i < 0 ? order[dir > 0 ? 0 : order.length - 1] : order[(i + dir + order.length) % order.length]];
    if (!shown[e.level]) setShown(e.level, true);
    pick(e);
  }
  $("rc-prev").addEventListener("click", () => stepPick(-1));
  $("rc-next").addEventListener("click", () => stepPick(1));

  // 로봇 카드: 이름(config robot.name), 모델, 배터리(robot.battery, 없으면 줄 숨김), 센서, 점검 일시, 이동 거리(display_meters),
  // 사진(robot.png, 없으면 직접 그린 그림)
  {
    $("rc-name").textContent = DATA.robot || "점검 로봇";
    $("rc-model").textContent = DATA.robot_model || "—";
    const hasBattery = DATA.robot_battery != null;
    $("rc-battery-k").hidden = $("rc-battery").hidden = !hasBattery;
    if (hasBattery) $("rc-battery").textContent = `${DATA.robot_battery}%`;
    $("rc-sensors").textContent = (DATA.robot_sensors || []).join(" · ") || "—";
    if (DATA.t0 != null) {
      const pt = tparts(DATA.t0);
      $("rc-when").textContent = `${pt.year}-${pt.month}-${pt.day} ${pt.hour}:${pt.minute}`;
    } else {
      $("rc-when").textContent = "—";
    }
    $("rc-dist").textContent = DATA.meters != null ? `${DATA.meters.toLocaleString("ko-KR")} m` : "—";
    const img = $("rc-photo"), draw = $("rc-draw");
    if (DATA.robot_photo) {
      img.src = DATA.robot_photo;
      img.hidden = false;
      draw.hidden = true;
      img.parentElement.classList.add("photo");
      img.addEventListener("error", () => { img.hidden = true; draw.hidden = false; img.parentElement.classList.remove("photo"); });  // 사진 파일이 없으면 그림으로
      // 사진 폭: 카드 오른쪽 45% 안, 칩 줄 오른쪽 끝 + 12px보다 오른쪽만. --shot-w = 실제로 그려진 사진 폭 (그림자 폭 기준)
      const art = img.parentElement, card = art.parentElement;
      const fitRobotPhoto = () => {
        if (!art.classList.contains("photo") || !img.naturalWidth) return;
        const box = card.getBoundingClientRect();
        const chipRight = Math.max(0, ...[...card.querySelectorAll(".rc-dl dd")].filter((d) => !d.hidden).map((d) => d.getBoundingClientRect().right - box.left));
        art.style.height = "";
        const want = art.clientHeight * img.naturalWidth / img.naturalHeight;  // 카드 높이 + 14px일 때 사진 폭
        const room = box.width - (chipRight + 4) + 8;                          // 칩 오른쪽 끝 + 4px부터 오른쪽 넘침(8px)까지
        const w = Math.max(0, Math.min(want, room));
        art.style.width = `${w}px`;
        art.style.setProperty("--shot-w", `${w}px`);
      };
      img.addEventListener("load", fitRobotPhoto);
      const ro = new ResizeObserver(fitRobotPhoto);
      ro.observe(card);
      for (const d of card.querySelectorAll(".rc-dl dd")) ro.observe(d);  // 칩 폭이 바뀌면 (글꼴 로딩 등) 다시 맞춘다
      if (document.fonts) document.fonts.ready.then(fitRobotPhoto);
    }
  }

  // 반원 게이지: f(0~1) 위치까지 등급 색 + 빗금, marks: 작은 점 [[위치, 색]]
  let gaugeSeq = 0;
  function halfGauge(f, level, marks, label) {
    const id = `hbh${++gaugeSeq}`, R = 44, cx = 52, cy = 54, len = Math.PI * R, k = Math.max(0, Math.min(f, 1));
    const at = (m) => { const a = Math.PI * (1 - Math.max(0, Math.min(m, 1))); return [cx + R * Math.cos(a), cy - R * Math.sin(a)]; };
    const arc = `M${cx - R} ${cy}A${R} ${R} 0 0 1 ${cx + R} ${cy}`;
    const svg = document.createElementNS(SVGNS, "svg");
    svg.setAttribute("viewBox", "0 0 104 62");
    svg.setAttribute("class", "hb-gauge");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", label);
    svg.innerHTML =
      `<defs><pattern id="${id}" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">` +
      `<rect width="6" height="6" style="fill:var(--${level})"/><rect width="2.2" height="6" style="fill:rgb(255 255 255 / 0.45)"/></pattern></defs>` +
      `<path d="${arc}" style="fill:none;stroke:var(--gauge-track);stroke-width:12;stroke-linecap:round"/>` +
      (k > 0 ? `<path d="${arc}" style="fill:none;stroke:url(#${id});stroke-width:12;stroke-linecap:round;stroke-dasharray:${(len * k).toFixed(1)} ${len.toFixed(1)}"/>` : "") +
      marks.map(([m, c]) => { const [x, y] = at(m); return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.4" style="fill:${c};stroke:var(--glass-solid);stroke-width:1.6"/>`; }).join("");
    return svg;
  }
  const UNIT_TXT = { cm: "cm", deg: "°", mm: "mm", score: "" };
  const withUnit = (v, unit) => (unit === "deg" ? `${v}°` : UNIT_TXT[unit] ? `${v} ${UNIT_TXT[unit]}` : `${v}`);
  // 측정 방식 아이콘: 카메라 · LiDAR · 발 접촉 (이번 지점에 쓴 것만 진하게)
  const METHOD_ICONS = [
    ["camera", "카메라", CAMERA],
    ["lidar", "LiDAR", '<circle cx="12" cy="12" r="3.2" style="fill:none;stroke:currentColor;stroke-width:1.8"/>' +
                       '<path d="M5 12a7 7 0 0 1 2-5M19 12a7 7 0 0 0-2-5M2 12a10 10 0 0 1 3-7M22 12a10 10 0 0 0-3-7" style="fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round"/>'],
    ["foot", "발 접촉", '<g style="fill:currentColor"><ellipse cx="12" cy="15" rx="4.2" ry="3.4"/><circle cx="7.4" cy="9.6" r="1.8"/>' +
                       '<circle cx="12" cy="7.6" r="1.9"/><circle cx="16.6" cy="9.6" r="1.8"/></g>'],
  ];
  const methodsUsed = (e) => ({ camera: e.source.includes("camera"), lidar: false, foot: e.source.includes("foot") });

  function blockPhoto(e, onMissing) {
    const p = e.photo, pic = el("div", "hb-pic");
    const img = el("img");
    img.src = p.src;
    img.alt = `${KIND[e.kind].label} ${fmtValue(e)} 현장 사진`;
    img.addEventListener("error", onMissing);
    pic.append(img);
    if (e.kind === "loose" && p.mark) {
      const [u, v, r] = p.mark, R = r * Math.min(p.w, p.h);
      const svg = document.createElementNS(SVGNS, "svg");
      svg.setAttribute("viewBox", `0 0 ${p.w} ${p.h}`);
      svg.setAttribute("preserveAspectRatio", "xMidYMid slice");  // 칸에 꽉 채워 자른 사진과 같게
      svg.setAttribute("aria-hidden", "true");
      const ring = (stroke, w, dash) => `<circle cx="${u * p.w}" cy="${v * p.h}" r="${R}" vector-effect="non-scaling-stroke" ` +
        `style="fill:none;stroke:${stroke};stroke-width:${w}${dash ? ";stroke-dasharray:7 5" : ""}"/>`;
      svg.innerHTML = ring("#FFFFFF", 5, false) + ring(`var(--${e.level})`, 2.5, true);
      const mk = el("span", "hb-mk", "발 접촉 위치");
      // 라벨: 동그라미 바로 아래 (cover로 잘린 비율에 맞춰 위치 계산)
      const place = () => {
        const W = pic.clientWidth, Hh = pic.clientHeight;
        if (!W || !Hh) return;
        const k = Math.max(W / p.w, Hh / p.h), ox = (W - p.w * k) / 2, oy = (Hh - p.h * k) / 2;
        const x = ox + u * p.w * k, y = oy + (v * p.h + R) * k + 4;
        mk.style.left = `${Math.max(48, Math.min(W - 48, x))}px`;
        mk.style.top = `${Math.min(Hh - 22, y)}px`;
      };
      new ResizeObserver(place).observe(pic);
      pic.append(svg, mk);
    }
    return pic;
  }

  function renderBlocks() {
    const box = $("hblocks");
    const e = cardEvent();
    box.replaceChildren();
    box.hidden = !e;
    $("hrow").classList.toggle("open", !!e);
    if (!e) return;
    const th = DATA.thresholds[e.kind], unit = e.unit;
    const close = el("button", "hb-close");
    close.type = "button";
    close.setAttribute("aria-label", "지점 블록 닫기");
    close.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${CLOSE_ICON}</svg>`;
    close.addEventListener("click", closePanel);

    // a. 사진 블록: 손상 사진(흔들림은 점선 동그라미 + 작은 "발 접촉 위치" 라벨), 위 왼쪽에 등급 배지 + 종류 + id
    const ph = el("div", "glass hb hb-photo");
    const noPhoto = () => { const np = el("div", "no-photo"); np.append(svgIcon(e.kind, null), el("span", null, "사진 없음")); return np; };
    if (e.photo) {
      const btn = el("button", "ph-btn");
      btn.type = "button";
      btn.setAttribute("aria-label", "사진 크게 보기");
      btn.append(blockPhoto(e, () => btn.replaceWith(noPhoto())));
      btn.addEventListener("click", () => openPhoto(e));
      ph.append(btn);
    } else {
      ph.append(noPhoto());
    }
    const tag = el("span", "hb-tag");
    tag.append(lvBadge(e.level), el("span", null, KIND[e.kind].label), el("span", "id", e.id));
    ph.append(tag);

    // b. 측정값 블록: 큰 숫자 + 단위, 반원 게이지(위험 기준의 2배를 가득, 주의·위험 기준에 점)
    const nb = el("div", "glass hb hb-num");
    const h1 = el("div", "hb-head");
    h1.append(el("span", "t", "측정값"), el("span", "s", `위험 기준 ${withUnit(th[1], unit)}`));
    const big = el("div", "hb-big", fmtNum(e.value, unit));
    if (UNIT_TXT[unit] || unit === "score") big.append(el("small", null, unit === "score" ? "점" : UNIT_TXT[unit]));
    const span = th[1] * 2, nbody = el("div", "hb-body");
    nbody.append(big, halfGauge(e.value / span, e.level, [[th[0] / span, "var(--warn)"], [th[1] / span, "var(--danger)"]],
                                `측정값 ${fmtValue(e)}, 주의 기준 ${withUnit(th[0], unit)}, 위험 기준 ${withUnit(th[1], unit)}`));
    nb.append(h1, nbody);

    // c. 기준 대비 블록: exceed_ratio (기준의 3배를 가득, 기준 위치에 점). 정상이면 "기준 이내"
    const rb = el("div", "glass hb hb-ratio");
    const h2 = el("div", "hb-head");
    h2.append(el("span", "t", "기준 대비"), el("span", "s", e.level === "danger" ? "위험 기준" : "주의 기준"));
    const ratio = Number(e.ratio);
    const rbig = e.level === "ok" ? el("div", "hb-big txt", "기준 이내") : el("div", "hb-big", ratio.toFixed(1));
    if (e.level !== "ok") rbig.append(el("small", null, "배"));
    const rbody = el("div", "hb-body");
    rbody.append(rbig, halfGauge(ratio / 3, e.level, [[1 / 3, "var(--text)"]], `기준의 ${ratio.toFixed(1)}배`));
    rb.append(h2, rbody);

    // d. 근거 블록: criterion_text, 위치·측정 시각, 측정 방식 아이콘, 흔들림 확정/의심 + 추가 침하, 오른쪽 위 ↗ 자세히 보기 · × 닫기
    const wb = el("div", "glass hb hb-why");
    wb.append(el("p", "crit", `기준 ${criterion(e)}`),
              el("p", "meta", `${Number(e.lat).toFixed(6)}, ${Number(e.lon).toFixed(6)} · ${fmtDateTimeS(e.t)}`));
    if (e.kind === "loose") {
      const sink = el("div", "sink");
      if (e.confirm) sink.append(el("span", "hb-cf", e.confirm));
      sink.append(el("span", null, `추가 침하 ${fmtNum(e.value, unit)} mm`));
      wb.append(sink);
    }
    const used = methodsUsed(e), ms = el("div", "hb-methods");
    for (const [k, label, path] of METHOD_ICONS) {
      const m = el("span", `m${used[k] ? " on" : ""}`);
      const ic = document.createElementNS(SVGNS, "svg");
      ic.setAttribute("viewBox", "0 0 24 24");
      ic.setAttribute("aria-hidden", "true");
      ic.innerHTML = path;
      m.append(ic, el("span", null, label));
      m.setAttribute("aria-label", `${label} ${used[k] ? "사용" : "사용 안 함"}`);
      ms.append(m);
    }
    const go = el("a", "hb-go");
    go.href = detailHref(e);
    go.setAttribute("aria-label", `자세히 보기 (${PAGES.detail.title})`);
    go.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${GO_ICON}</svg>`;
    const acts = el("div", "hb-acts");
    acts.append(go, close);
    wb.append(ms, acts);

    box.append(ph, nb, rb, wb);
    box.classList.remove("in");
    void box.offsetWidth;  // 다시 고를 때도 올라오는 움직임을 다시 시작
    box.classList.add("in");
  }
  // 고른 지점이 블록 줄·필터 카드에 가리지 않게 (이미 보이면 움직이지 않는다)
  function ensureVisible(e) {
    if (state.mode !== "tiles" || !state.map || !e) return;
    const P = homePadding();
    state.map.panInside([e.lat, e.lon], { paddingTopLeft: P.tl, paddingBottomRight: P.br, animate: !reduceMotion.matches });
  }
  wideHome.addEventListener("change", () => { if (state.map) state.map.invalidateSize({ animate: false }); });

  // 종합 현황 지도에서 지점 위치 보기 (#home/<id>): 선택 표시 + 그 지점이 보이게
  function focusOnMap(e) {
    if (!shown[e.level]) setShown(e.level, true);  // 꺼진 판정의 지점이면 그 판정을 켠다
    renderMap();
    ensureVisible(e);
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
    hint: newest ? `클릭 → ${PAGES.detail.title}` : "상세 페이지는 가장 최근 점검만",
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
    addSatelliteToggle(map, "bottomleft");
    HM.map = map;
    HM.pendingTiles = true;  // 타일은 그날 경로로 범위를 정한 뒤 붙인다 (drawHMap)
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
    if (HM.pendingTiles) {
      HM.pendingTiles = false;
      attachTiles(map, 19, () => HM.map === map, () => hPlane());
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
               `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="7.5" style="fill:none;stroke:#363236;stroke-width:1.5"/>` + tag(x, y, side, 12, text, 11.5, 750);
      };
      out += end(r.xy[0], sd.start, "var(--h-route)", "출발") +
             end(r.xy[r.xy.length - 1], sd.end, "#363236", `도착 ${dateMeters(H.date).toLocaleString("ko-KR")} m`);
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
      // 상세 페이지는 가장 최근 점검만: 지난 날짜는 이동 링크 없이 "—" (방문 기록에 남겨 뒤로 가기 → #history/<날짜>)
      const go = newest ? el("a", "go", `${PAGES.detail.title} →`) : el("span", "tm", "—");
      if (newest) go.href = detailHref(e);
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
    // 예전 주소(#visual/<id>, #physical/<id>)는 검사 결과로 연다
    if (rawPage === "visual" || rawPage === "physical") {
      location.replace(rawId && byId[rawId] ? `#detail/${rawId}` : "#detail");
      return;
    }
    const page = Object.prototype.hasOwnProperty.call(PAGES, rawPage) ? rawPage : "home";
    const id = rawId && byId[rawId] ? rawId : null;
    if (page === "detail") {
      if (id) {
        // 고른 지점이 탭·칩에 걸려 안 보이면 보이게 맞춘다
        const e = byId[id];
        if (!inTab(e, D.tab)) D.tab = "all";
        if (!D.levels[e.level]) {
          D.levels[e.level] = true;
          levelChips.find((b) => b.dataset.level === e.level)?.setAttribute("aria-pressed", "true");
        }
      } else {
        const first = detailShown()[0] || detailAll[0];  // 선택 없이 들어오면 목록 첫 지점
        if (first) { location.replace(`#detail/${first.id}`); return; }
      }
    }
    if (page === "history" && NEWEST && !DATE_BY[rawId]) { location.replace(`#history/${NEWEST}`); return; }
    const changed = page !== state.page;
    const fromOtherPage = !!state.page && state.page !== "home";  // 검사 결과의 "지도에서 위치 보기"
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
      renderBlocks();
      if (state.map) state.map.invalidateSize({ animate: false });  // 화면 크기·배치가 바뀌었으면 지도 크기를 다시 잰다
    }
    state.pickedOnMap = false;
    if (page === "detail") renderDetailPage();
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
