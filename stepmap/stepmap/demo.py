"""디자인 단계용 예시 데이터 생성기 (make_demo_data.py 이식).

계획서 7장. 제주시 노형동·연동 일대 실제 보도를 따라 걷는 경로와 측정 지점을 만든다.
실측 데이터가 나오면 이 출력 대신 stepmap step/foot/crack/traj 출력으로 교체한다.

경로 (약 913m, 3구간, 모두 좌회전 · 보도는 진행 방향 왼쪽이라 차도를 건너지 않음)
  1. 노연로 북측 보도, 연동1길 입구 → 신광로 교차로 (동쪽, 약 301m)
  2. 신광로 서측 보도, 노연로 → 삼무로 교차로 (북쪽, 약 437m)
  3. 삼무로 남측 보도, 신광로 → 연동3길 입구 (서쪽, 약 174m)
경로 좌표는 OpenStreetMap 도로 중심선(© OpenStreetMap contributors, ODbL)을
보도 쪽으로 평행 이동해 만들었다 (노연로 북측 차로 5m, 신광로 11m, 삼무로 9m).
오프셋은 중심선에서 걷는 쪽 건물 벽까지의 거리(노연로 6~10m, 신광로 12~18m)보다
작게 잡아, 경로가 OSM 건물 외곽선 안으로 들어가지 않는다(최소 이격 0.8m).
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from .events import GeoRef, extra_sink, judge, write_events, write_foot_traces, write_trajectory

DAY_S = 86400

SEED = 20261020
SESSION = "20261020_nohyeong_yeon_A"
T0 = 1792454400.0   # 2026-10-20 09:00 KST
SPEED = 0.45        # m/s
SPACING = 0.25      # 궤적 점 간격 [m]
POS_NOISE = 0.03    # 궤적 위치 흔들림 [m]
EVENT_JITTER = 0.25 # 측정 지점의 궤적 대비 위치 흩어짐 [m]

# 보도 경로 꺾임점 (위도, 경도)
WAYPOINTS = [
    (33.4860377, 126.4866072),  #   0 m  출발: 노연로 북측, 연동1길 입구 동쪽
    (33.4859819, 126.4879068),  # 121 m  연동3길 입구
    (33.4859450, 126.4892363),  # 244 m  제원길 입구
    (33.4859279, 126.4898508),  # 301 m  노연로·신광로 교차로 북서 모퉁이 (좌회전)
    (33.4868893, 126.4898914),  # 409 m  신광로8길 입구
    (33.4878726, 126.4899330),  # 518 m  신광로6길 입구
    (33.4888261, 126.4899733),  # 624 m  신광로4길 입구 (제원아파트 정류장 480 m)
    (33.4898548, 126.4900275),  # 739 m  신광로·삼무로 교차로 남서 모퉁이 (좌회전)
    (33.4898839, 126.4894242),  # 795 m  제원길 입구 (롯데시티호텔 정류장 842 m)
    (33.4899325, 126.4881586),  # 913 m  도착: 연동3길 입구 앞
]

# 측정 지점: (경로상 거리 m, 대표값, 발 측정값, 다리, 비고)
# 판정 비율은 현실적으로: 40개 중 위험 4 (종류별 1), 주의 5, 나머지 정상 (위험·주의 약 20%)
# 단차 13 = 카메라+발 교차 7 (값 차이 0.2~0.3cm) + 카메라 단독 4 + 발만 2 (카메라 사각)
#   위험 1 (4.8cm, 사진), 주의 2 (교차 측정 1.6cm, 발만 1.0cm = 주의 경계값), 정상 10
STEPS_CROSS = [
    (60, 0.6, 0.8, "FL", "보도블럭 이음부"),
    (117, 1.6, 1.8, "FR", "연동3길 입구 횡단보도 진입부 연석"),
    (241, 0.8, 0.6, "FR", "제원길 입구 연석 경사로 끝단"),
    (297, 4.8, 5.1, "FR", "노연로·신광로 교차로 횡단보도 진입부 연석"),
    (412, 0.5, 0.8, "FL", "신광로8길 입구 경계석"),
    (560, 0.7, 0.9, "FR", "상가 진입로 경계"),
    (735, 0.9, 0.6, "FL", "신광로·삼무로 교차로 횡단보도 진입부 연석"),
]
STEPS_CAMERA = [
    (180, 0.6, ""),
    (355, 0.7, "맨홀 뚜껑 주변"),
    (650, 0.8, ""),
    (797, 0.6, "제원길 입구 배수구 덮개"),
]
STEPS_FOOT = [
    (484, 1.0, "FL", "버스정류장 승차대 옆, 카메라 사각으로 발 접촉만 확인"),
    (845, 0.8, "RL", "가로수 보호판 가장자리, 카메라 사각으로 발 접촉만 확인"),
]
# 경사 8 (2.2~7.9°): 위험 1, 주의 1, 정상 6
SLOPES = [
    (30, 2.2, ""),
    (125, 3.6, "연동3길 입구 연석 경사로"),
    (300, 7.9, "교차로 모퉁이 경사로"),
    (450, 3.1, ""),
    (590, 6.2, "건물 주차장 출입구 경사로"),
    (700, 3.8, ""),
    (742, 4.2, "신광로·삼무로 교차로 모퉁이 경사로"),
    (860, 2.8, "보도 횡단 경사(배수 방향)"),
]
# 균열 11 (점수 0.35~0.91): 위험 1 (사진), 주의 1, 정상 9. 균열은 점수가 곧 신뢰도
CRACKS = [
    (45, 0.42, "블럭 표면 잔금"),
    (150, 0.38, ""),
    (205, 0.91, "아스팔트 덧씌움 경계 균열"),
    (335, 0.44, ""),
    (420, 0.46, "블럭 모서리 마모"),
    (530, 0.71, "가로수 뿌리 주변 균열"),
    (600, 0.47, ""),
    (680, 0.41, "점자블록 이음부 줄눈"),
    (755, 0.35, ""),
    (810, 0.49, ""),
    (875, 0.39, "맨홀 테두리 줄눈"),
]
# 흔들림 8 (추가 침하 1.8~8.5mm): 위험 1 (외관 정상, 사진), 주의 1 (외관 정상), 정상 6
LOOSE = [
    (85, 2.1, "RL", "외관 정상, 침하 기준 미만"),
    (215, 2.4, "FR", ""),
    (330, 8.5, "FL", "외관 정상, 체중 시 기울어짐"),
    (466, 1.8, "RR", "외관 정상, 미세 침하"),
    (545, 2.6, "RR", ""),
    (630, 2.2, "RL", "가로수 보호판 주변 블럭"),
    (705, 5.1, "FL", "외관 정상, 디딤 시 흔들림"),
    (840, 2.7, "FR", "버스정류장 앞 블럭"),
]


def demo_georef() -> GeoRef:
    """출발점을 odom 원점으로, 첫 구간 방향을 odom x축으로 둔다."""
    (lat0, lon0), (lat1, lon1) = WAYPOINTS[0], WAYPOINTS[1]
    north = math.radians(lat1 - lat0)
    east = math.radians(lon1 - lon0) * math.cos(math.radians(lat0))
    heading = math.degrees(math.atan2(east, north)) % 360
    return GeoRef(lat0, lon0, round(heading, 1))


def _resample(points: list[tuple[float, float]], step: float) -> list[tuple[float, float]]:
    """꺾은선을 일정 간격으로 다시 샘플링한다 (끝점 포함)."""
    cum = [0.0]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        cum.append(cum[-1] + math.hypot(x1 - x0, y1 - y0))
    out, k = [], 0
    for i in range(int(cum[-1] / step) + 1):
        d = i * step
        while cum[k + 1] < d:
            k += 1
        a = (d - cum[k]) / (cum[k + 1] - cum[k])
        (x0, y0), (x1, y1) = points[k], points[k + 1]
        out.append((x0 + (x1 - x0) * a, y0 + (y1 - y0) * a))
    out.append(points[-1])
    return out


def _walk(rng: random.Random, waypoints, t0: float, session: str, thresholds: dict | None,
          value_at=None) -> tuple[list[dict], list[dict]]:
    """경로를 따라 걸은 궤적과 측정 지점 40개. value_at(kind, 거리, 값, 발 값) → (값, 발 값): 날짜별 값 (없으면 그대로)."""
    geo = demo_georef()

    # 1) 궤적
    path = [geo.to_odom(lat, lon) for lat, lon in waypoints]
    traj = []
    for i, (x, y) in enumerate(_resample(path, SPACING)):
        x += rng.gauss(0, POS_NOISE)
        y += rng.gauss(0, POS_NOISE)
        lat, lon = geo.to_latlon(x, y)
        traj.append({"t": round(t0 + i * SPACING / SPEED, 2), "x": round(x, 3), "y": round(y, 3),
                     "lat": round(lat, 8), "lon": round(lon, 8)})

    # 2) 측정 지점
    events = []

    def add(dist, kind, value, unit, source, conf, leg="", note="", value_foot=None):
        if value_at:
            value, value_foot = value_at(kind, dist, value, value_foot)
        p = traj[min(round(dist / SPACING), len(traj) - 1)]
        x = round(p["x"] + rng.uniform(-EVENT_JITTER, EVENT_JITTER), 2)
        y = round(p["y"] + rng.uniform(-EVENT_JITTER, EVENT_JITTER), 2)
        lat, lon = geo.to_latlon(x, y)
        events.append({
            "id": "", "t": p["t"], "session": session, "x": x, "y": y,
            "lat": round(lat, 8), "lon": round(lon, 8),
            "kind": kind, "value": value, "unit": unit, "source": source, "leg": leg,
            "confidence": conf, "level": judge(kind, value, thresholds),
            "image": "", "note": note, "value_foot": value_foot, "image_mark": "",
        })

    def conf(lo, hi):
        return round(rng.uniform(lo, hi), 2)

    for d, cam, foot, leg, note in STEPS_CROSS:
        add(d, "step", cam, "cm", "camera+foot", conf(0.85, 0.95), leg, note, foot)
    for d, cam, note in STEPS_CAMERA:
        add(d, "step", cam, "cm", "camera", conf(0.75, 0.9), note=note)
    for d, foot, leg, note in STEPS_FOOT:
        add(d, "step", foot, "cm", "foot", conf(0.75, 0.85), leg, note)
    for d, deg, note in SLOPES:
        add(d, "slope", deg, "deg", "camera", conf(0.8, 0.95), note=note)
    for d, score, note in CRACKS:
        add(d, "crack", score, "score", "camera", score, note=note)
    for d, mm, leg, note in LOOSE:
        add(d, "loose", mm, "mm", "foot", conf(0.7, 0.9), leg, note)

    events.sort(key=lambda e: e["t"])
    for i, e in enumerate(events, 1):
        e["id"] = f"ev_{i:04d}"
    return traj, events


def generate(out_dir: str | Path, thresholds: dict | None = None, split: bool = False,
             photos_dir: str | Path | None = None) -> tuple[list[dict], list[dict]]:
    """예시 trajectory.csv, events.csv를 out_dir에 만들고 (trajectory, events)를 반환한다.

    split=True면 같은 측정 결과를 기능별 파일로 나눠 out_dir/raw/에도 저장한다 (split_events 참고).
    photos_dir를 주면 그 폴더의 현장 사진을 정해진 지점에 연결한다 (attach_photos 참고).
    """
    rng = random.Random(SEED)
    out_dir = Path(out_dir)
    traj, events = _walk(rng, WAYPOINTS, T0, SESSION, thresholds)
    if photos_dir is not None:
        attach_photos(events, photos_dir, out_dir)
    write_trajectory(out_dir / "trajectory.csv", traj)
    traces = make_foot_traces(events)
    write_foot_traces(out_dir / "foot_traces.csv", traces)
    write_events(out_dir / "events.csv", events)
    if split:
        for name, rows in split_events(events).items():
            write_events(out_dir / "raw" / name, rows, raw=True)
        # 발 분석 모듈 출력처럼 id를 비운 발끝 기록 (merge가 접지 시각·다리로 지점과 연결해 id를 채운다)
        write_foot_traces(out_dir / "raw" / RAW_TRACES, [{**r, "id": ""} for r in traces], raw=True)
    return traj, events


# ---------------------------------------------------------------------------
# 지난 점검 (점검 이력 페이지): 같은 구간을 하루 한 번, 날짜마다 조금 다른 경로로 다시 걸었다.
# 가장 최근 날짜(T0, 2026-10-20)는 generate 출력 그대로이고, 여기서는 그 이전 날짜만
# <out>/history/<YYYY-MM-DD>/events.csv, trajectory.csv로 만든다 (stepmap map이 읽는다).
# ---------------------------------------------------------------------------
HISTORY_DIR = "history"
HISTORY_DAYS_BEFORE = (35, 21, 14, 7)  # T0 기준 며칠 전: 09-15, 09-29, 10-06, 10-13 (오래된 순)
WAYPOINT_JITTER_M = 1.0                # 날짜마다 꺾임점을 이만큼 안에서 옮겨 경로가 조금씩 다르다
OLDER_FACTOR = 0.03                    # 나머지 지점: 한 회 이전마다 값이 이만큼 작았다 (최근 값 이하로만)
# 날짜가 지나며 나빠진 지점: (종류, 경로상 거리 m) → 오래된 날짜부터 값 (가장 최근 값은 위 표)
TRENDS = {
    ("step", 297): (1.4, 1.6, 1.9, 2.6),       # 주의 → 위험 (최근 4.8cm)
    ("slope", 300): (6.1, 6.5, 6.9, 7.4),      # 주의 → 위험 (최근 7.9°)
    ("crack", 205): (0.58, 0.66, 0.74, 0.83),  # 주의 → 위험 (최근 0.91)
    ("loose", 330): (3.4, 4.1, 5.0, 5.8),      # 주의 → 위험 (최근 8.5mm)
    ("step", 117): (0.7, 0.8, 1.1, 1.3),       # 정상 → 주의 (최근 1.6cm)
    ("loose", 705): (2.2, 2.6, 3.4, 4.3),      # 정상 → 주의 (최근 5.1mm)
    ("crack", 530): (0.44, 0.52, 0.6, 0.66),   # 정상 → 주의 (최근 0.71)
}
DIGITS = {"step": 1, "slope": 1, "crack": 2, "loose": 1}


def history_dates() -> list[str]:
    """지난 점검 날짜 (오래된 순, YYYY-MM-DD)."""
    from datetime import datetime, timedelta, timezone

    kst = timezone(timedelta(hours=9))
    return [datetime.fromtimestamp(T0 - n * DAY_S, kst).strftime("%Y-%m-%d") for n in HISTORY_DAYS_BEFORE]


def generate_history(out_dir: str | Path, thresholds: dict | None = None) -> list[tuple[str, list[dict], list[dict]]]:
    """지난 점검 날짜별 trajectory.csv, events.csv를 out_dir/history/<날짜>/에 만들고 [(날짜, 궤적, 지점)]을 반환한다."""
    out = []
    for k, (date, days) in enumerate(zip(history_dates(), HISTORY_DAYS_BEFORE)):
        rng = random.Random(SEED + 100 + k)
        lat0 = WAYPOINTS[0][0]
        m_lat, m_lon = 1 / 111320, 1 / (111320 * math.cos(math.radians(lat0)))
        waypoints = [(lat + rng.uniform(-1, 1) * WAYPOINT_JITTER_M * m_lat, lon + rng.uniform(-1, 1) * WAYPOINT_JITTER_M * m_lon)
                     for lat, lon in WAYPOINTS]
        older = len(HISTORY_DAYS_BEFORE) - k  # 가장 최근 날짜보다 몇 회 앞인지

        def value_at(kind, dist, value, value_foot, k=k, older=older, rng=rng):
            trend = TRENDS.get((kind, dist))
            if trend:
                new = trend[k]
            else:
                new = round(min(value, value * (1 - OLDER_FACTOR * older + rng.uniform(-0.02, 0.02))), DIGITS[kind])
            foot = None if value_foot is None else round(max(0.0, new + value_foot - value), DIGITS[kind])
            return new, foot

        session = f"{date.replace('-', '')}_nohyeong_yeon_A"
        traj, events = _walk(rng, waypoints, T0 - days * DAY_S, session, thresholds, value_at)
        for e in events:
            if e["kind"] == "crack":  # 균열은 점수가 곧 신뢰도
                e["confidence"] = e["value"]
        d = Path(out_dir) / HISTORY_DIR / date
        write_trajectory(d / "trajectory.csv", traj)
        write_events(d / "events.csv", events)
        out.append((date, traj, events))
    return out


# ---------------------------------------------------------------------------
# 흔들림 지점의 발끝 높이 기록 (foot_traces.csv, 계획서 6.4)
# 높이 기준: 평소 걸음이 딛고 있을 때의 평균 높이 = 0mm. t: 접지 순간 = 0초
# ---------------------------------------------------------------------------
TRACE_T = [round(-0.30 + i * 0.01, 2) for i in range(113)]  # -0.30 ~ +0.82초


def _smooth(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def _foot_curve(t: float, swing1=31.0, c1=-0.13, swing2=26.0, contact=0.0, sink=2.0) -> float:
    """발끝 높이 [mm]: 접지 전 휘두르기 → 접지 직후 조금 더 내려와 멈춤 → 체중이 실리며 sink만큼 내려감 → 다시 발 들기."""
    z = swing1 * math.exp(-((t - c1) / 0.07) ** 2)          # 접지 전 다리 휘두르기
    z += 1.2 * (1 - _smooth(t / 0.07)) if t >= 0 else 1.2    # 접지 직후 남은 내려옴 (0.07초 안에 멈춤)
    z += 1.0 + contact                                       # 멈춘 높이
    z -= sink * _smooth((t - 0.09) / 0.16)                   # 체중이 실리며 내려감 (0.09 ~ 0.25초)
    z += (sink - 2.0) * _smooth((t - 0.44) / 0.12)           # 발을 들면 흔들리는 블럭이 되돌아옴
    z += swing2 * math.exp(-((t - 0.64) / 0.08) ** 2)        # 다음 발 들기
    return z


def _band(t: float) -> float:
    """평소 걸음 범위의 반폭 [mm]: 휘두르는 구간은 넓고 딛고 있는 구간은 좁다."""
    return (1.3 + 18 * math.exp(-((t + 0.13) / 0.09) ** 2) + 14 * math.exp(-((t - 0.64) / 0.1) ** 2)
            + 1.5 * math.exp(-(t / 0.04) ** 2))


def make_foot_traces(events: list[dict]) -> list[dict]:
    """흔들림 지점마다 발끝 높이 기록. 그래프에서 읽히는 추가 침하(events.extra_sink)가 그 지점의 value와 같다."""
    rng = random.Random(SEED + 2)
    rows = []
    for e in sorted((e for e in events if e["kind"] == "loose"), key=lambda e: e["id"]):
        n_normal = rng.randint(18, 26)
        a1, c1, a2 = rng.uniform(0.85, 1.15), -0.13 + rng.uniform(-0.01, 0.01), rng.uniform(0.85, 1.1)
        contact = rng.uniform(-0.5, 0.5)  # 접지 높이는 평소와 비슷
        mean = [round(_foot_curve(t), 2) for t in TRACE_T]
        lo = [round(m - 0.85 * _band(t), 2) for m, t in zip(mean, TRACE_T)]
        hi = [round(m + 1.15 * _band(t), 2) for m, t in zip(mean, TRACE_T)]
        sink = 2.0 + e["value"]
        for _ in range(4):  # 저장할 값(소수 둘째 자리) 기준으로 계산한 추가 침하가 value와 같아지게 맞춘다
            step = [round(_foot_curve(t, 31 * a1, c1, 26 * a2, contact, sink), 2) for t in TRACE_T]
            got = extra_sink({"t": TRACE_T, "z_step": step, "z_mean": mean})["extra_mm"]
            if abs(got - e["value"]) < 0.005:
                break
            sink += e["value"] - got
        rows += [{"id": e["id"], "leg": e["leg"], "t": t, "z_step": zs, "z_mean": zm, "z_lo": zl, "z_hi": zh,
                  "n_normal": n_normal, "t_event": e["t"]} for t, zs, zm, zl, zh in zip(TRACE_T, step, mean, lo, hi)]
    return rows


# 현장 사진 연결: (파일, 고르는 규칙, 비고, image_mark "u,v,r")
# image_mark는 겉보기에 멀쩡한 흔들림 사진에만 (발 접촉 위치 표시). 단차·균열은 문제가 사진에 보이므로 비운다
def _pick_step(events):  # 단차 위험 중 카메라+발 교차 측정, 값이 가장 큰 것
    c = [e for e in events if e["kind"] == "step" and e["level"] == "danger" and e["source"] == "camera+foot"]
    return max(c, key=lambda e: e["value"], default=None)


def _pick_crack(events):  # 균열 위험 중 confidence가 가장 높은 것
    c = [e for e in events if e["kind"] == "crack" and e["level"] == "danger"]
    return max(c, key=lambda e: e["confidence"], default=None)


def _pick_loose(events):  # 흔들림 위험 중 외관 정상인 것, 값이 가장 큰 것
    c = [e for e in events if e["kind"] == "loose" and e["level"] == "danger" and "외관 정상" in e["note"]]
    return max(c, key=lambda e: e["value"], default=None)


PHOTO_LINKS = [
    ("step_curb_gap.jpg", _pick_step, "경계석 이음부 벌어짐·단차", ""),
    ("crack_broken_hole.jpg", _pick_crack, "블럭 파손·함몰, 점자블럭 인접", ""),
    ("loose_normal.jpg", _pick_loose, None, "0.5,0.5,0.05"),  # 사진 가운데 블럭 한 장 (비고는 그대로)
]


def attach_photos(events: list[dict], photos_dir: str | Path, out_dir: str | Path) -> list[tuple[str, str]]:
    """PHOTO_LINKS대로 사진을 연결한다. image는 events.csv(out_dir) 기준 상대 경로.

    위치·값·판정은 바꾸지 않고 image·image_mark(와 정해진 경우 note)만 채운다. 파일이 없으면 그 연결만 건너뛴다.
    """
    import os

    linked = []
    for name, pick, note, mark in PHOTO_LINKS:
        path = Path(photos_dir) / name
        e = pick(events)
        if not path.is_file() or e is None:
            continue
        e["image"] = Path(os.path.relpath(path, out_dir)).as_posix()
        e["image_mark"] = mark
        if note is not None:
            e["note"] = note
        linked.append((name, e["id"]))
    return linked


# 기능별 결과 파일 (계획서 9장 step / foot / crack 모듈 출력 자리)
RAW_FILES = ("camera_step.csv", "camera_slope.csv", "camera_crack.csv", "foot.csv")
RAW_TRACES = "foot_traces.csv"  # 발 분석 모듈의 발끝 기록 (id 빈칸, t_event로 연결)
FOOT_OFFSET = (0.3, 0.2)   # 교차 측정에서 발이 밟은 위치: 카메라 위치에서 약 0.36m
FOOT_DELAY_S = 1.0         # 카메라가 먼저 보고 발이 나중에 밟는다
DUP_OFFSET = (0.4, -0.3)   # 균열·경사 중복 검출 위치: 원래 위치에서 0.5m
DUP_DELAY_S = 0.9


def split_events(events: list[dict]) -> dict[str, list[dict]]:
    """병합된 events를 기능별 결과로 되돌린다 (id·level은 비움).

    - 카메라+발 교차 단차 → camera_step.csv 한 행 + foot.csv 한 행 (발 위치·시각은 조금 뒤)
    - 균열·경사 → 원래 행 + confidence가 더 낮은 중복 검출 한 행
    stepmap merge로 다시 합치면 원래 events와 같아야 한다.
    """
    rng = random.Random(SEED + 1)
    geo = demo_georef()
    out = {name: [] for name in RAW_FILES}

    def raw(e, **kw):
        r = {**e, "id": "", "level": "", **kw}
        if "x" in kw or "y" in kw:
            lat, lon = geo.to_latlon(r["x"], r["y"])
            r["lat"], r["lon"] = round(lat, 8), round(lon, 8)
        return r

    for e in events:
        moved = lambda dxy, dt: {"x": round(e["x"] + dxy[0], 2), "y": round(e["y"] + dxy[1], 2), "t": round(e["t"] + dt, 2)}
        if e["kind"] == "step" and e["source"] == "camera+foot":
            out["camera_step.csv"].append(raw(e, source="camera", leg="", value_foot=None))
            out["foot.csv"].append(raw(e, source="foot", value=e["value_foot"], value_foot=None,
                                       **moved(FOOT_OFFSET, FOOT_DELAY_S)))
        elif e["kind"] == "step" and e["source"] == "camera":
            out["camera_step.csv"].append(raw(e))
        elif e["kind"] in ("step", "loose"):
            out["foot.csv"].append(raw(e))
        else:
            name = f"camera_{e['kind']}.csv"
            out[name].append(raw(e))
            if e["kind"] == "crack":  # 균열은 점수가 곧 신뢰도
                score = round(max(0.0, e["value"] - rng.uniform(0.02, 0.08)), 2)
                dup = raw(e, value=score, confidence=score, **moved(DUP_OFFSET, DUP_DELAY_S))
            else:
                dup = raw(e, value=round(e["value"] + rng.uniform(-0.2, 0.2), 1),
                          confidence=round(max(0.0, e["confidence"] - rng.uniform(0.05, 0.15)), 2),
                          **moved(DUP_OFFSET, DUP_DELAY_S))
            out[name].append(dup)
    for rows in out.values():
        rows.sort(key=lambda r: r["t"])
    return out


