"""GPS 위치 보정: 로봇과 함께 다니는 휴대폰·노트북의 GPS 위치로 odom 원점의 위도·경도와 방위각(GeoRef)을 구한다.

로봇(Go2)에는 GPS가 없다. 대시보드를 연 기기의 위치(브라우저 Geolocation)를 live 서버가 받을 때마다 그 순간의
로봇 odom 위치(x, y)와 짝지어 둔다 (gps 항목). 짝이 여럿이면 odom → 지도 평면의 회전·이동을 최소제곱으로 맞춘다.

  짝 1개 또는 로봇이 거의 움직이지 않음: 위치만 맞춘다 (방위각은 이전 값, 없으면 0 → "방향 확인 중")
  로봇이 MIN_SPREAD_M 이상 움직인 짝들: 위치 + 방위각. 정확도(acc)가 나쁜 위치는 가볍게, 크게 벗어난 위치는 뺀다

휴대폰은 로봇 옆 1~2 m에 있고 GPS 오차도 수 m라 결과 위치 오차는 수 m 수준이다 (보도 단위로는 충분, 블록 단위는 아님).
"""
from __future__ import annotations

import math

from .events import _EARTH_R, GeoRef

MAX_ACC_M = 50.0          # 이보다 부정확한 위치(실내·WiFi 추정)는 쓰지 않는다
MIN_ACC_M = 3.0           # 가중치 계산용 하한 (정확도를 과신하지 않게)
MIN_SPREAD_M = 5.0        # 방위각을 정하려면 짝들의 odom 위치가 이만큼 퍼져 있어야 한다
WINDOW = 300              # 최근 짝만 쓴다 (odom은 오래 걸으면 조금씩 어긋난다)


def _fit(P, Q, W, theta=None):
    """Q ≈ R(theta)·P + T. theta가 None이면 회전도 구한다. 반환: (theta, T)."""
    sw = sum(W)
    pc = (sum(w * p[0] for w, p in zip(W, P)) / sw, sum(w * p[1] for w, p in zip(W, P)) / sw)
    qc = (sum(w * q[0] for w, q in zip(W, Q)) / sw, sum(w * q[1] for w, q in zip(W, Q)) / sw)
    if theta is None:
        sxx = sxy = 0.0
        for w, p, q in zip(W, P, Q):
            px, py, qx, qy = p[0] - pc[0], p[1] - pc[1], q[0] - qc[0], q[1] - qc[1]
            sxx += w * (px * qx + py * qy)
            sxy += w * (px * qy - py * qx)
        theta = math.atan2(sxy, sxx)
    c, s = math.cos(theta), math.sin(theta)
    return theta, (qc[0] - (c * pc[0] - s * pc[1]), qc[1] - (s * pc[0] + c * pc[1]))


def _spread(P) -> float:
    cx, cy = sum(p[0] for p in P) / len(P), sum(p[1] for p in P) / len(P)
    return max(math.hypot(p[0] - cx, p[1] - cy) for p in P)


def fit_geo(fixes: list[dict], heading_deg: float | None = None) -> tuple[GeoRef, bool] | None:
    """fixes: {"lat", "lon", "acc", "x", "y"} (GPS 위치와 그때의 odom 위치). heading_deg: 방위각을 못 정할 때 쓸 값.
    반환: (GeoRef, 방위각을 GPS로 정했는지) 또는 None (쓸 만한 위치 없음)."""
    use = [f for f in fixes[-WINDOW:] if f.get("acc") is None or f["acc"] <= MAX_ACC_M]
    if not use:
        return None
    lat0, lon0 = use[-1]["lat"], use[-1]["lon"]
    mlat = math.radians(1) * _EARTH_R
    mlon = mlat * math.cos(math.radians(lat0))
    P = [(f["x"], f["y"]) for f in use]
    Q = [((f["lon"] - lon0) * mlon, (f["lat"] - lat0) * mlat) for f in use]
    W = [1.0 / max(f.get("acc") or MIN_ACC_M, MIN_ACC_M) ** 2 for f in use]
    fixed = None if len(use) >= 2 and _spread(P) >= MIN_SPREAD_M else math.radians(90.0 - (heading_deg or 0.0))
    theta, T = _fit(P, Q, W, fixed)
    if fixed is None:                     # 크게 벗어난 위치(오차 3배 이상, 최소 10 m)를 빼고 한 번 더
        c, s = math.cos(theta), math.sin(theta)
        keep = [i for i, (p, q, f) in enumerate(zip(P, Q, use))
                if math.hypot(c * p[0] - s * p[1] + T[0] - q[0], s * p[0] + c * p[1] + T[1] - q[1])
                <= max(3 * (f.get("acc") or MIN_ACC_M), 10.0)]
        if 2 <= len(keep) < len(use) and _spread([P[i] for i in keep]) >= MIN_SPREAD_M:
            theta, T = _fit([P[i] for i in keep], [Q[i] for i in keep], [W[i] for i in keep])
    # GeoRef: east = x·sin(h) − y·cos(h), north = x·cos(h) + y·sin(h)  →  회전각 theta = 90° − h
    heading = (90.0 - math.degrees(theta)) % 360.0
    return GeoRef(lat0 + T[1] / mlat, lon0 + T[0] / mlon, heading), fixed is None


def shift_m(a: GeoRef, b: GeoRef, points) -> float:
    """두 GeoRef로 같은 odom 점들을 지도에 놓았을 때 가장 크게 달라지는 거리 [m]."""
    mlat = math.radians(1) * _EARTH_R
    out = 0.0
    for x, y in points:
        la, lo = a.to_latlon(x, y)
        lb, lob = b.to_latlon(x, y)
        out = max(out, math.hypot((la - lb) * mlat, (lo - lob) * mlat * math.cos(math.radians(la))))
    return out
