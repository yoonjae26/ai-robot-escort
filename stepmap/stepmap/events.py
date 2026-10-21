"""공통 데이터 형식(events.csv, trajectory.csv), 판정, 좌표 변환.

계획서 6장의 형식을 코드로 고정한 곳이다. 예시 데이터든 실측 모듈이든
CSV 저장은 반드시 write_events / write_trajectory 로만 한다.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# 형식 정의 (계획서 6.1, 6.2)
# ---------------------------------------------------------------------------

EVENT_COLUMNS = [
    "id", "t", "session", "x", "y", "lat", "lon", "kind", "value", "unit", "source",
    "leg", "confidence", "level", "image", "note", "value_foot", "image_mark",
]
# 선택 열: 파일에 없어도 읽는다 (빈칸으로 채움). 저장할 때는 항상 쓴다.
#   image_mark (events.csv), t_event (foot_traces.csv: 접지 순간의 절대 시각, merge가 지점과 연결할 때 쓴다)
OPTIONAL_COLUMNS = {"image_mark", "t_event"}
OPTIONAL_EVENT_COLUMNS = OPTIONAL_COLUMNS
TRAJECTORY_COLUMNS = ["t", "x", "y", "lat", "lon"]
# 흔들림 지점의 발끝 높이 기록 (계획서 6.4). 행 하나 = 한 시점, t는 접지 순간 = 0초
FOOT_TRACE_COLUMNS = ["id", "leg", "t", "z_step", "z_mean", "z_lo", "z_hi", "n_normal", "t_event"]

KIND_UNITS = {"step": "cm", "slope": "deg", "crack": "score", "loose": "mm"}
SOURCES = ("camera", "foot", "camera+foot")
LEVELS = ("ok", "warn", "danger")
LEGS = ("FR", "FL", "RR", "RL")

# 숫자 열과 CSV에 쓸 소수 자릿수. lat/lon 8자리 ≈ 1mm.
_NUMERIC_DIGITS = {
    "t": 2, "x": 3, "y": 3, "lat": 8, "lon": 8,
    "value": 3, "confidence": 3, "value_foot": 3,
    "z_step": 2, "z_mean": 2, "z_lo": 2, "z_hi": 2, "n_normal": 0, "t_event": 2,  # foot_traces.csv (mm, 걸음 수, 초)
}
_REQUIRED_NUMERIC = {"t", "x", "y", "value", "confidence"}

# 판정 기준 기본값 (계획서 6.3, config.yaml thresholds와 동일)
DEFAULT_THRESHOLDS = {
    "step": (1.0, 2.0),      # cm
    "slope": (4.76, 7.13),   # deg (1/12, 1/8)
    "crack": (0.5, 0.8),     # score
    "loose": (3.0, 6.0),     # mm
}

ENCODING = "utf-8-sig"  # 엑셀에서 한글 비고가 깨지지 않게 BOM 포함


class FormatError(ValueError):
    """events.csv / trajectory.csv 형식 위반."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        shown = "\n  ".join(errors[:20])
        more = f"\n  ... 외 {len(errors) - 20}건" if len(errors) > 20 else ""
        super().__init__(f"형식 오류 {len(errors)}건:\n  {shown}{more}")


# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------

def load_config(path: str | Path) -> dict:
    import yaml

    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def thresholds_from_config(cfg: dict) -> dict[str, tuple[float, float]]:
    th = cfg.get("thresholds") or {}
    keys = {"step": "step_{}_cm", "slope": "slope_{}_deg", "crack": "crack_{}", "loose": "loose_{}_mm"}
    out = {}
    for kind, key in keys.items():
        warn = float(th.get(key.format("warn"), DEFAULT_THRESHOLDS[kind][0]))
        danger = float(th.get(key.format("danger"), DEFAULT_THRESHOLDS[kind][1]))
        out[kind] = (warn, danger)
    return out


# ---------------------------------------------------------------------------
# 판정 (계획서 6.3)
# ---------------------------------------------------------------------------

def judge(kind: str, value: float, thresholds: dict | None = None) -> str:
    """값이 warn 이상이면 'warn', danger 이상이면 'danger', 아니면 'ok'."""
    if kind not in KIND_UNITS:
        raise ValueError(f"알 수 없는 kind: {kind!r}")
    warn, danger = (thresholds or DEFAULT_THRESHOLDS)[kind]
    if value >= danger:
        return "danger"
    if value >= warn:
        return "warn"
    return "ok"


def _num(v: float) -> str:
    """기준값 표기: 2.0 → "2", 4.76 → "4.76" (JS 문자열 변환과 같은 모양)."""
    return f"{float(v):g}"


def round_half_up(v: float) -> int:
    """0.5는 위로 올리는 반올림 (JS Math.round와 같음. Python round는 짝수 쪽으로 보낸다)."""
    return math.floor(v + 0.5)


def slope_fraction(deg: float) -> str:
    """경사 각도 → 1/n 표기 (7.13° → 1/8)."""
    return f"1/{round_half_up(1 / math.tan(math.radians(deg)))}"


def criterion_text(kind: str, level: str, thresholds: dict | None = None) -> str:
    """판정 기준 문구. 대시보드 상세 패널과 신고서가 같은 이 함수를 쓴다."""
    lo, hi = (thresholds or DEFAULT_THRESHOLDS)[kind]
    w, d = _num(lo), _num(hi)
    if kind == "step":
        texts = {"danger": f"휠체어 회피 기준 {d}cm 이상",
                 "warn": f"주의 기준 {w}cm 이상 · 휠체어 회피 기준 {d}cm 미만",
                 "ok": f"주의 기준 {w}cm 미만"}
    elif kind == "slope":
        fw, fd = slope_fraction(lo), slope_fraction(hi)
        texts = {"danger": f"휠체어 회피 기준 {fd}({d}°) 이상",
                 "warn": f"주의 기준 {fw}({w}°) 이상 · 회피 기준 {fd} 미만",
                 "ok": f"주의 기준 {fw}({w}°) 미만"}
    elif kind == "crack":
        texts = {"danger": f"균열 점수 {d} 이상", "warn": f"균열 점수 {w} 이상 · {d} 미만", "ok": f"균열 점수 {w} 미만"}
    else:  # loose
        texts = {"danger": f"접지 후 추가 침하 {d}mm 이상", "warn": f"추가 침하 {w}mm 이상 · {d}mm 미만",
                 "ok": f"추가 침하 {w}mm 미만"}
    return texts[level]


def exceed_ratio(kind: str, level: str, value: float, thresholds: dict | None = None) -> float:
    """기준 대비 초과 정도: 판정에 쓰인 기준값(위험→danger, 주의→warn, 정상→warn)에 대한 비율."""
    w, d = (thresholds or DEFAULT_THRESHOLDS)[kind]
    return value / (d if level == "danger" else w)


# ---------------------------------------------------------------------------
# odom (x, y) ↔ 위도·경도
# ---------------------------------------------------------------------------

_EARTH_R = 6378137.0  # WGS84 장반경 [m]


@dataclass(frozen=True)
class GeoRef:
    """odom 원점의 위도·경도와 odom x축 방위각(북=0, 동=90, 시계방향).

    출발점 기준 평면 근사(등장방형). 1~2km 범위에서 오차는 mm 수준이다.
    odom은 ROS 규약(x 전방, y 좌측)을 따른다.
    """

    origin_lat: float
    origin_lon: float
    heading_deg: float = 0.0

    def _axes(self):
        h = math.radians(self.heading_deg)
        m_per_deg_lat = math.radians(1) * _EARTH_R
        m_per_deg_lon = m_per_deg_lat * math.cos(math.radians(self.origin_lat))
        return math.sin(h), math.cos(h), m_per_deg_lat, m_per_deg_lon

    def to_latlon(self, x: float, y: float) -> tuple[float, float]:
        s, c, mlat, mlon = self._axes()
        east = x * s - y * c
        north = x * c + y * s
        return self.origin_lat + north / mlat, self.origin_lon + east / mlon

    def to_odom(self, lat: float, lon: float) -> tuple[float, float]:
        s, c, mlat, mlon = self._axes()
        north = (lat - self.origin_lat) * mlat
        east = (lon - self.origin_lon) * mlon
        return east * s + north * c, -east * c + north * s


def georef_from_config(cfg: dict) -> GeoRef | None:
    """config의 geo 섹션. 값이 아직 <...> 자리표시자면 None."""
    geo = cfg.get("geo") or {}
    try:
        return GeoRef(float(geo["origin_lat"]), float(geo["origin_lon"]), float(geo.get("heading_deg", 0)))
    except (KeyError, TypeError, ValueError):
        return None


def odom_to_latlon(x: float, y: float, geo: GeoRef) -> tuple[float, float]:
    return geo.to_latlon(x, y)


def latlon_to_odom(lat: float, lon: float, geo: GeoRef) -> tuple[float, float]:
    return geo.to_odom(lat, lon)


# ---------------------------------------------------------------------------
# 이동 거리
# ---------------------------------------------------------------------------

PATH_MIN_STEP_M = 1.0


def display_meters(meters: float) -> int:
    """화면·신고서에 쓰는 이동 거리 [m]: 반올림은 표시할 때 한 번만 (대시보드 Math.round와 같음)."""
    return round_half_up(meters)


def path_length(traj: list[dict], min_step: float = PATH_MIN_STEP_M) -> float:
    """궤적 이동 거리 [m]. 직전에 채택한 점에서 min_step 이상 떨어진 점만 이어서 더한다.

    odom 위치의 작은 흔들림(cm 단위)이 점마다 더해져 거리가 늘어나는 것을 막는다.
    마지막 점까지의 남은 거리는 더한다.
    """
    if len(traj) < 2:
        return 0.0
    total, anchor = 0.0, traj[0]
    for p in traj[1:]:
        d = math.hypot(p["x"] - anchor["x"], p["y"] - anchor["y"])
        if d >= min_step:
            total += d
            anchor = p
    return total + math.hypot(traj[-1]["x"] - anchor["x"], traj[-1]["y"] - anchor["y"])


# ---------------------------------------------------------------------------
# 형식 검사
# ---------------------------------------------------------------------------

def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def parse_image_mark(text: str) -> tuple[float, float, float] | None:
    """image_mark "u,v,r" → (u, v, r). u·v: 사진 가로·세로 대비 위치(0~1), r: 짧은 변 대비 반지름(0~1].

    빈칸이면 None, 형식이 틀리면 ValueError.
    """
    if not text:
        return None
    parts = [p.strip() for p in str(text).split(",")]
    if len(parts) != 3:
        raise ValueError(f"image_mark는 'u,v,r' 형식이어야 함 ({text!r})")
    u, v, r = (float(p) for p in parts)
    if not (0 <= u <= 1 and 0 <= v <= 1 and 0 < r <= 1):
        raise ValueError(f"image_mark 값 범위: u·v는 0~1, r은 0 초과 1 이하 ({text!r})")
    return u, v, r


def _check_columns(header, expected, name) -> list[str]:
    missing = [c for c in expected if c not in header and c not in OPTIONAL_EVENT_COLUMNS]
    extra = [c for c in header if c not in expected]
    errors = []
    if missing:
        errors.append(f"{name}: 열 누락 {missing}")
    if extra:
        errors.append(f"{name}: 알 수 없는 열 {extra}")
    return errors


def _check_latlon(row, where) -> list[str]:
    lat, lon = row.get("lat"), row.get("lon")
    if lat is None and lon is None:
        return []  # geo 설정 전의 실측 데이터는 비워둘 수 있다
    if not (_is_num(lat) and _is_num(lon)):
        return [f"{where}: lat/lon은 둘 다 숫자이거나 둘 다 빈칸이어야 함"]
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return [f"{where}: lat/lon 범위 밖 ({lat}, {lon})"]
    return []


def validate_events(rows: list[dict], raw: bool = False) -> list[str]:
    """events 행 목록의 형식 오류를 모두 모아 반환한다. 빈 목록이면 통과.

    raw=True: 기능별 결과(병합 전) 검사. id·level은 비어 있어도 된다 (merge가 다시 매긴다).
    """
    errors: list[str] = []
    seen_ids = set()
    for i, r in enumerate(rows, 1):
        where = f"events {i}행({r.get('id', '?')})"
        errors += _check_columns(list(r.keys()), EVENT_COLUMNS, where)
        if any(c not in r for c in EVENT_COLUMNS if c not in OPTIONAL_EVENT_COLUMNS):
            continue
        if not r["id"]:
            if not raw:
                errors.append(f"{where}: id 빈칸")
        elif r["id"] in seen_ids and not raw:
            errors.append(f"{where}: id 중복")
        seen_ids.add(r["id"])
        if not r["session"]:
            errors.append(f"{where}: session 빈칸")
        for c in _REQUIRED_NUMERIC:
            if not _is_num(r[c]):
                errors.append(f"{where}: {c}는 숫자여야 함 ({r[c]!r})")
        errors += _check_latlon(r, where)

        kind, source, leg = r["kind"], r["source"], r["leg"]
        if kind not in KIND_UNITS:
            errors.append(f"{where}: kind {kind!r}는 {list(KIND_UNITS)} 중 하나여야 함")
        elif r["unit"] != KIND_UNITS[kind]:
            errors.append(f"{where}: {kind}의 unit은 {KIND_UNITS[kind]!r}여야 함 ({r['unit']!r})")
        if source not in SOURCES:
            errors.append(f"{where}: source {source!r}는 {list(SOURCES)} 중 하나여야 함")
        if r["level"] not in LEVELS and not (raw and r["level"] == ""):
            errors.append(f"{where}: level {r['level']!r}는 {list(LEVELS)} 중 하나여야 함")
        if leg and leg not in LEGS:
            errors.append(f"{where}: leg {leg!r}는 {list(LEGS)} 중 하나여야 함")
        if source in ("foot", "camera+foot") and not leg:
            errors.append(f"{where}: 발 측정({source})은 leg 필요")
        if source == "camera" and leg:
            errors.append(f"{where}: 카메라 단독 측정에는 leg를 비워야 함")
        if source == "camera+foot" and not _is_num(r["value_foot"]):
            errors.append(f"{where}: camera+foot은 value_foot 필요")
        if source != "camera+foot" and r["value_foot"] is not None:
            errors.append(f"{where}: value_foot은 camera+foot일 때만 기록")
        if _is_num(r["confidence"]) and not 0 <= r["confidence"] <= 1:
            errors.append(f"{where}: confidence는 0~1 ({r['confidence']})")
        if r.get("image_mark"):
            try:
                parse_image_mark(r["image_mark"])
            except ValueError as ex:
                errors.append(f"{where}: {ex}")
            if not r["image"]:
                errors.append(f"{where}: image_mark는 image가 있을 때만 기록")
    return errors


def validate_trajectory(rows: list[dict]) -> list[str]:
    errors: list[str] = []
    prev_t = None
    for i, r in enumerate(rows, 1):
        where = f"trajectory {i}행"
        errors += _check_columns(list(r.keys()), TRAJECTORY_COLUMNS, where)
        if any(c not in r for c in TRAJECTORY_COLUMNS):
            continue
        for c in ("t", "x", "y"):
            if not _is_num(r[c]):
                errors.append(f"{where}: {c}는 숫자여야 함 ({r[c]!r})")
        errors += _check_latlon(r, where)
        if _is_num(r["t"]):
            if prev_t is not None and r["t"] < prev_t:
                errors.append(f"{where}: t가 시간순이 아님")
            prev_t = r["t"]
    return errors


# ---------------------------------------------------------------------------
# 읽기 / 쓰기
# ---------------------------------------------------------------------------

def _parse(row: dict, columns: list[str]) -> dict:
    out = {}
    for c in columns:
        if c not in row:
            if c in OPTIONAL_COLUMNS:
                out[c] = None if c in _NUMERIC_DIGITS else ""
            continue
        v = (row[c] or "").strip()
        if c in _NUMERIC_DIGITS:
            if v == "":
                out[c] = None
            else:
                try:
                    out[c] = float(v)
                except ValueError:
                    out[c] = v  # 형식 검사에서 걸리도록 그대로 둔다
        else:
            out[c] = v
    for c in row:
        if c not in columns and c is not None:
            out[c] = row[c]
    return out


def _fmt(c: str, v) -> str:
    if v is None:
        return ""
    if c in _NUMERIC_DIGITS and _is_num(v):
        s = f"{v:.{_NUMERIC_DIGITS[c]}f}"
        s = s.rstrip("0").rstrip(".") if "." in s else s
        return "0" if s == "-0" else s
    return str(v)


def _read(path, columns, validate):
    with open(path, encoding=ENCODING, newline="") as f:
        reader = csv.DictReader(f)
        header_errors = _check_columns(reader.fieldnames or [], columns, str(path))
        if header_errors:
            raise FormatError(header_errors)
        rows = [_parse(r, columns) for r in reader]
    errors = validate(rows)
    if errors:
        raise FormatError(errors)
    return rows


def _write(path, rows, columns, validate):
    errors = validate(rows)
    if errors:
        raise FormatError(errors)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding=ENCODING, newline="") as f:
        w = csv.writer(f)
        w.writerow(columns)
        for r in rows:
            w.writerow([_fmt(c, r.get(c)) for c in columns])


def read_events(path: str | Path, raw: bool = False) -> list[dict]:
    """raw=True: id·level이 빈 기능별 결과도 읽는다."""
    return _read(path, EVENT_COLUMNS, lambda rows: validate_events(rows, raw))


def write_events(path: str | Path, rows: list[dict], raw: bool = False) -> None:
    _write(path, rows, EVENT_COLUMNS, lambda rows: validate_events(rows, raw))


def _trace_key(r: dict) -> str:
    """지점 하나의 기록을 묶는 열쇠: id, id가 비었으면(모듈 출력) 접지 시각·다리."""
    return r["id"] if r.get("id") else f"@{r.get('t_event')}/{r.get('leg')}"


def validate_foot_traces(rows: list[dict], raw: bool = False) -> list[str]:
    """foot_traces.csv 형식 검사: 열, 숫자, 다리, 범위(z_lo ≤ z_mean ≤ z_hi), 지점마다 시간순·같은 다리·같은 걸음 수.

    raw=True: 발 분석 모듈 출력(merge 전). id는 비어 있어도 되지만 그때는 t_event(접지 순간 절대 시각)가 있어야 한다.
    """
    errors: list[str] = []
    last: dict[str, dict] = {}
    for i, r in enumerate(rows, 1):
        where = f"foot_traces {i}행({r.get('id', '?')})"
        errors += _check_columns(list(r.keys()), FOOT_TRACE_COLUMNS, where)
        if any(c not in r for c in FOOT_TRACE_COLUMNS if c not in OPTIONAL_COLUMNS):
            continue
        if not r["id"] and not raw:
            errors.append(f"{where}: id 빈칸")
        if r.get("t_event") is not None and not _is_num(r["t_event"]):
            errors.append(f"{where}: t_event는 숫자여야 함 ({r['t_event']!r})")
        if not r["id"] and raw and not _is_num(r.get("t_event")):
            errors.append(f"{where}: id가 비어 있으면 t_event 필요 (merge가 지점과 연결)")
        if r["leg"] not in LEGS:
            errors.append(f"{where}: leg {r['leg']!r}는 {list(LEGS)} 중 하나여야 함")
        nums = ("t", "z_step", "z_mean", "z_lo", "z_hi", "n_normal")
        bad = [c for c in nums if not _is_num(r[c])]
        if bad:
            errors.append(f"{where}: {bad}는 숫자여야 함")
            continue
        if not r["z_lo"] <= r["z_mean"] <= r["z_hi"]:
            errors.append(f"{where}: z_lo ≤ z_mean ≤ z_hi 이어야 함")
        if r["n_normal"] < 1 or r["n_normal"] != int(r["n_normal"]):
            errors.append(f"{where}: n_normal은 1 이상의 정수")
        key = _trace_key(r)
        prev = last.get(key)
        if prev is not None:
            if r["t"] <= prev["t"]:
                errors.append(f"{where}: 같은 지점 안에서 t가 시간순이 아님")
            if r["leg"] != prev["leg"] or r["n_normal"] != prev["n_normal"]:
                errors.append(f"{where}: 같은 지점은 leg·n_normal이 같아야 함")
        last[key] = r
    for key, r in last.items():
        first_t = next(x["t"] for x in rows if _trace_key(x) == key and _is_num(x.get("t")))
        if not (first_t <= 0 <= r["t"]):
            errors.append(f"foot_traces {key}: 접지 순간(t=0)을 포함해야 함 ({first_t} ~ {r['t']}초)")
    return errors


def read_foot_traces(path: str | Path, raw: bool = False) -> list[dict]:
    """raw=True: id가 빈 발 분석 모듈 출력도 읽는다 (t_event 필요)."""
    return _read(path, FOOT_TRACE_COLUMNS, lambda rows: validate_foot_traces(rows, raw))


def write_foot_traces(path: str | Path, rows: list[dict], raw: bool = False) -> None:
    _write(path, rows, FOOT_TRACE_COLUMNS, lambda rows: validate_foot_traces(rows, raw))


def is_foot_traces_file(path: str | Path) -> bool:
    """CSV 머리줄로 발끝 기록 파일인지 판단한다 (merge 입력에 events와 섞여 있어도 나눠 읽는다)."""
    with open(path, encoding=ENCODING, newline="") as f:
        header = next(csv.reader(f), [])
    return {"z_step", "z_mean"} <= set(header)


def group_foot_traces(rows: list[dict]) -> dict[str, dict]:
    """지점 id별로 묶는다: {id: {"leg", "n_normal", "t": [...], "z_step": [...], "z_mean", "z_lo", "z_hi"}}."""
    out: dict[str, dict] = {}
    for r in rows:
        g = out.setdefault(r["id"], {"leg": r["leg"], "n_normal": int(r["n_normal"]),
                                     "t": [], "z_step": [], "z_mean": [], "z_lo": [], "z_hi": []})
        for c in ("t", "z_step", "z_mean", "z_lo", "z_hi"):
            g[c].append(r[c])
    return out


# ---------------------------------------------------------------------------
# 추가 침하 (계획서 10.3): 접지 뒤 발이 멈춘 시점부터 계산
# ---------------------------------------------------------------------------

SETTLE_SPEED_MM_S = 20.0  # 이 속도보다 느려지면 "발이 멈췄다"(접지 직후 내려오는 구간이 끝났다)고 본다


def settle_index(ts: list[float], zs: list[float], v_max: float = SETTLE_SPEED_MM_S) -> int:
    """접지(t=0) 뒤 발끝 속도(중앙 차분)가 처음으로 v_max 미만이 되는 위치."""
    start = next((i for i, t in enumerate(ts) if t >= 0), 0)
    for i in range(max(start, 1), len(ts) - 1):
        v = (zs[i + 1] - zs[i - 1]) / (ts[i + 1] - ts[i - 1])
        if abs(v) < v_max:
            return i
    return start


def stance_sink(ts: list[float], zs: list[float], v_max: float = SETTLE_SPEED_MM_S) -> tuple[float, float, int]:
    """(멈춘 높이, 접지 뒤 내려간 양 mm, 멈춘 위치). 내려간 양 = 멈춘 높이 − 다음 발 들기 최고점 전까지의 최저점."""
    i_s = settle_index(ts, zs, v_max)
    tail = zs[i_s:]
    i_peak = i_s + max(range(len(tail)), key=tail.__getitem__)  # 다음 발 들기 최고점
    low = min(zs[i_s:i_peak + 1]) if i_peak > i_s else min(tail)
    return zs[i_s], zs[i_s] - low, i_s


def extra_sink(trace: dict, v_max: float = SETTLE_SPEED_MM_S) -> dict:
    """추가 침하 = 이번 걸음이 접지 뒤 내려간 양 − 평소 걸음이 접지 뒤 내려간 양.

    접지 직후 발이 아직 내려오는 구간은 빼고, 발 속도가 거의 0이 된 시점부터 잰다.
    contact_diff = 멈춘 높이 차이 (이번 걸음 − 평소 걸음, "접지 높이: 평소보다 ±N mm").
    """
    ts = trace["t"]
    z0_step, sink_step, i_step = stance_sink(ts, trace["z_step"], v_max)
    z0_mean, sink_mean, i_mean = stance_sink(ts, trace["z_mean"], v_max)
    return {"extra_mm": sink_step - sink_mean, "sink_step_mm": sink_step, "sink_mean_mm": sink_mean,
            "contact_diff_mm": z0_step - z0_mean, "t_settle_step": ts[i_step], "t_settle_mean": ts[i_mean]}


def read_trajectory(path: str | Path) -> list[dict]:
    return _read(path, TRAJECTORY_COLUMNS, validate_trajectory)


def write_trajectory(path: str | Path, rows: list[dict]) -> None:
    _write(path, rows, TRAJECTORY_COLUMNS, validate_trajectory)


# ---------------------------------------------------------------------------
# 병합 (계획서 9.3, stepmap merge)
# ---------------------------------------------------------------------------

MERGE_DEFAULTS = {
    "step_radius_m": 1.0,   # 카메라 단차와 발 단차를 한 건(camera+foot)으로 합치는 거리 (이하)
    "step_window_s": 10.0,  # 〃 시간 차. 카메라가 먼저 보고 발이 나중에 밟는다
    "dedup_radius_m": 1.0,  # 같은 종류(균열·경사) 중복 검출을 하나로 줄이는 거리 (이하)
    "dedup_window_s": 10.0,
}
DEDUP_KINDS = ("crack", "slope")
_EPS = 1e-9


def merge_from_config(cfg: dict) -> dict:
    m = cfg.get("merge") or {}
    return {k: float(m.get(k, v)) for k, v in MERGE_DEFAULTS.items()}


def _dist(a: dict, b: dict) -> float:
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def _near(a: dict, b: dict, radius: float, window: float) -> bool:
    return _dist(a, b) <= radius + _EPS and abs(a["t"] - b["t"]) <= window + _EPS


def _combine_step(cam: dict, foot: dict) -> dict:
    """카메라 단차 + 발 단차 → 한 건. 위치·시각·대표값은 카메라 기준."""
    out = dict(cam)
    out["source"] = "camera+foot"
    out["value_foot"] = foot["value"]
    out["leg"] = foot["leg"]
    out["confidence"] = max(cam["confidence"], foot["confidence"])
    notes = [n for n in (cam["note"], foot["note"]) if n]
    out["note"] = " / ".join(dict.fromkeys(notes))
    out["image"] = cam["image"] or foot["image"]
    return out


TRACE_MATCH_S = 0.5  # 발끝 기록의 접지 시각(t_event)과 흔들림 지점 시각의 허용 차이 [초]


def link_foot_traces(trace_rows: list[dict], events: list[dict],
                     window_s: float = TRACE_MATCH_S) -> tuple[list[dict], list[dict]]:
    """발끝 기록을 merge된 흔들림 지점과 연결해 id를 채운다.

    지점 하나의 기록(접지 시각 t_event + 다리)마다, 다리가 같고 시각 차이가 window_s 이하인 흔들림 지점 중
    가장 가까운 것에 붙인다. 한 지점에는 기록 하나만 붙는다.
    돌려주는 값: (id를 채운 행들 — id·t 순, 짝이 없는 기록 [{"t_event", "leg", "rows"}])
    """
    groups: dict[str, list[dict]] = {}
    for r in trace_rows:
        groups.setdefault(_trace_key(r) if r.get("t_event") is None else f"@{r['t_event']}/{r['leg']}", []).append(r)
    loose = [e for e in events if e["kind"] == "loose"]
    cand = []
    for key, rows in groups.items():
        r0 = rows[0]
        if r0.get("t_event") is None:
            continue
        for e in loose:
            dt = abs(e["t"] - r0["t_event"])
            if e["leg"] == r0["leg"] and dt <= window_s + _EPS:
                cand.append((dt, key, e["id"]))
    used_k, used_e, linked = set(), set(), []
    for _, key, eid in sorted(cand):
        if key in used_k or eid in used_e:
            continue
        used_k.add(key)
        used_e.add(eid)
        linked += [{**r, "id": eid} for r in groups[key]]
    unmatched = [{"t_event": rows[0].get("t_event"), "leg": rows[0]["leg"], "rows": len(rows)}
                 for key, rows in groups.items() if key not in used_k]
    linked.sort(key=lambda r: (r["id"], r["t"]))
    return linked, unmatched


def merge_events(rows: list[dict], thresholds: dict | None = None, merge: dict | None = None,
                 geo: GeoRef | None = None) -> tuple[list[dict], dict]:
    """기능별 결과를 합쳐 events 목록과 통계를 돌려준다.

    1. 카메라 단차 ↔ 발 단차: step_radius_m·step_window_s 안이면 가까운 쌍부터 1:1로 묶어
       source=camera+foot, value=카메라 값, value_foot=발 값, leg=발 측정 다리
    2. 균열·경사: dedup_radius_m·dedup_window_s 안에 여러 번 잡히면 confidence가 가장 높은 것 하나만
    3. 흔들림(발)과 그 밖의 행은 그대로 (카메라 결과와 합치지 않음)
    4. level은 thresholds로 다시 계산, id는 시간순으로 다시 매김, lat/lon이 비었으면 geo로 채움
    """
    m = {**MERGE_DEFAULTS, **(merge or {})}
    rows = [dict(r) for r in rows]
    cams = [r for r in rows if r["kind"] == "step" and r["source"] == "camera"]
    feet = [r for r in rows if r["kind"] == "step" and r["source"] == "foot"]
    rest = [r for r in rows if not (r["kind"] == "step" and r["source"] in ("camera", "foot"))
            and r["kind"] not in DEDUP_KINDS]

    # 1) 단차 교차 측정
    cand = sorted((_dist(c, f), i, j) for i, c in enumerate(cams) for j, f in enumerate(feet)
                  if _near(c, f, m["step_radius_m"], m["step_window_s"]))
    used_c, used_f, out = set(), set(), []
    for _, i, j in cand:
        if i in used_c or j in used_f:
            continue
        used_c.add(i)
        used_f.add(j)
        out.append(_combine_step(cams[i], feet[j]))
    out += [c for i, c in enumerate(cams) if i not in used_c]
    out += [f for j, f in enumerate(feet) if j not in used_f]

    # 2) 균열·경사 중복 제거
    dropped = 0
    for kind in DEDUP_KINDS:
        kept: list[dict] = []
        for r in sorted((r for r in rows if r["kind"] == kind), key=lambda r: (-r["confidence"], r["t"])):
            if any(_near(r, k, m["dedup_radius_m"], m["dedup_window_s"]) for k in kept):
                dropped += 1
            else:
                kept.append(r)
        out += kept

    # 3) 나머지 + 4) 판정·id·좌표
    out += rest
    out.sort(key=lambda r: (r["t"], r["x"], r["y"], r["kind"]))
    for i, r in enumerate(out, 1):
        r["id"] = f"ev_{i:04d}"
        r["level"] = judge(r["kind"], r["value"], thresholds)
        if geo is not None and r["lat"] is None and r["lon"] is None:
            lat, lon = geo.to_latlon(r["x"], r["y"])
            r["lat"], r["lon"] = round(lat, 8), round(lon, 8)
    stats = {"inputs": len(rows), "pairs": len(used_c), "duplicates_dropped": dropped, "events": len(out)}
    return out, stats
