"""자동 신고서 (계획서 8.3, stepmap report).

출력
- report.html: A4 인쇄용. 요약 → 위치 확인용 경로 그림(SVG, 인터넷 없이 보임) → 위험·주의 지점 목록
- report.csv: 지자체 데이터 제공용. 목록과 같은 지점·같은 순서·같은 번호

이동 거리(path_length + display_meters)와 기준 문구(criterion_text)는 대시보드와 같은 함수를 쓴다.
데이터 문자열은 HTML에서는 html.escape, CSV에서는 수식 주입(=, +, -, @ 시작)을 막는다.
"""

from __future__ import annotations

import csv
import html
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .events import (
    DEFAULT_THRESHOLDS, ENCODING, KIND_UNITS, criterion_text, display_meters, exceed_ratio,
    path_length, read_events, read_trajectory,
)
from .photos import LEG_NAMES, contact_label, prepare_photos

KST = timezone(timedelta(hours=9))
KIND_LABEL = {"step": "단차", "slope": "경사", "crack": "균열", "loose": "흔들림"}
LEVEL_LABEL = {"danger": "위험", "warn": "주의", "ok": "정상"}
LEVEL_GLYPH = {"danger": "!!", "warn": "!", "ok": "✓"}
LEVEL_RANK = {"danger": 3, "warn": 2, "ok": 1}
LEG_LABEL = LEG_NAMES
UNIT_TEXT = {"cm": "cm", "deg": "°", "mm": "mm", "score": ""}
REPORT_LEVELS = ("danger", "warn")

CSV_COLUMNS = ["번호", "판정", "종류", "측정값", "단위", "기준", "기준 대비", "측정 방식", "카메라 값", "발 값",
               "차이", "다리", "위도", "경도", "측정 시각", "메모", "사진", "세션", "ID"]


# ---------------------------------------------------------------------------
# 값 표기 (대시보드와 같은 모양)
# ---------------------------------------------------------------------------

def fmt_num(v: float, unit: str) -> str:
    return f"{v:.2f}" if unit == "score" else f"{v:.1f}"


def fmt_value(v: float, unit: str) -> str:
    return f"{fmt_num(v, unit)}{UNIT_TEXT[unit]}"


def fmt_dt(t: float, with_date: bool = True) -> str:
    d = datetime.fromtimestamp(t, KST)
    return d.strftime("%Y-%m-%d %H:%M") if with_date else d.strftime("%H:%M:%S")


def leg_name(leg: str) -> str:
    return f"{LEG_LABEL.get(leg, leg)}({leg})" if leg else ""


def method_text(e: dict) -> str:
    if e["source"] == "camera+foot":
        diff = abs(e["value_foot"] - e["value"])
        return (f"카메라 {fmt_value(e['value'], e['unit'])} · 발 {fmt_value(e['value_foot'], e['unit'])} "
                f"· {leg_name(e['leg'])} · 차이 {fmt_value(diff, e['unit'])}")
    if e["source"] == "foot":
        return f"발 접촉 · {leg_name(e['leg'])}"
    return "카메라"


def report_items(events: list[dict], thresholds: dict | None = None) -> list[dict]:
    """신고 대상(위험·주의)만, 위험 먼저, 같은 판정 안에서는 기준 대비 초과 정도가 큰 순. 번호 부여."""
    th = thresholds or DEFAULT_THRESHOLDS
    picked = [e for e in events if e["level"] in REPORT_LEVELS]
    picked.sort(key=lambda e: (-LEVEL_RANK[e["level"]], -exceed_ratio(e["kind"], e["level"], e["value"], th), e["t"]))
    return [{**e, "no": i, "criterion": criterion_text(e["kind"], e["level"], th),
             "ratio": exceed_ratio(e["kind"], e["level"], e["value"], th), "method": method_text(e)}
            for i, e in enumerate(picked, 1)]


def summary(events: list[dict], traj: list[dict], area: str = "") -> dict:
    t0, t1 = traj[0]["t"], traj[-1]["t"]
    counts = {k: {lv: sum(1 for e in events if e["kind"] == k and e["level"] == lv) for lv in LEVEL_LABEL}
              for k in KIND_UNITS}
    return {
        "session": " · ".join(sorted({e["session"] for e in events})),
        "period": f"{fmt_dt(t0)} ~ {fmt_dt(t1)[-5:]} (KST)",
        "area": area,
        "distance_m": display_meters(path_length(traj)),
        "counts": counts,
        "total": len(events),
        "by_level": {lv: sum(c[lv] for c in counts.values()) for lv in LEVEL_LABEL},
    }


# ---------------------------------------------------------------------------
# 위치 확인용 경로 그림 (SVG)
# ---------------------------------------------------------------------------

def route_svg(traj: list[dict], items: list[dict], width: int = 680, max_height: int = 620, pad: int = 64) -> str:
    """위도·경도 → 북쪽이 위인 평면(m). 번호표는 서로·경로·측정점과 겹치지 않는 자리에 두고 연결선을 긋는다."""
    lat0 = sum(p["lat"] for p in traj) / len(traj)
    lon0 = sum(p["lon"] for p in traj) / len(traj)
    m_lat = math.radians(1) * 6378137.0
    m_lon = m_lat * math.cos(math.radians(lat0))
    en = lambda lat, lon: ((lon - lon0) * m_lon, (lat - lat0) * m_lat)

    route = [en(p["lat"], p["lon"]) for p in traj[::4]] + [en(traj[-1]["lat"], traj[-1]["lon"])]
    pts = [en(e["lat"], e["lon"]) for e in items]
    xs = [p[0] for p in route + pts]
    ys = [p[1] for p in route + pts]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    s = min((width - 2 * pad) / max(maxx - minx, 1), (max_height - 2 * pad) / max(maxy - miny, 1))
    height = round((maxy - miny) * s + 2 * pad)
    ox = (width - (maxx - minx) * s) / 2
    X = lambda x: ox + (x - minx) * s
    Y = lambda y: pad + (maxy - y) * s

    rpx = [(X(x), Y(y)) for x, y in route]
    ppx = [(X(x), Y(y)) for x, y in pts]
    cx, cy = (X(minx) + X(maxx)) / 2, (Y(miny) + Y(maxy)) / 2

    def seg_dist(px, py, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy
        t = 0 if L2 == 0 else max(0, min(1, ((px - a[0]) * dx + (py - a[1]) * dy) / L2))
        return math.hypot(px - a[0] - t * dx, py - a[1] - t * dy)

    R = 9  # 번호표 반지름
    placed: list[tuple[float, float]] = []
    labels = []
    for (px, py), e in zip(ppx, items):
        base = math.atan2(py - cy, px - cx) if (px, py) != (cx, cy) else -math.pi / 2
        best = None
        for radius in (20, 32, 46, 62, 80, 100):
            for off in (0, 30, -30, 60, -60, 90, -90, 120, -120, 150, -150, 180):
                a = base + math.radians(off)
                lx, ly = px + radius * math.cos(a), py + radius * math.sin(a)
                if not (R + 2 <= lx <= width - R - 2 and R + 2 <= ly <= height - R - 2):
                    continue
                if any(math.hypot(lx - qx, ly - qy) < 2 * R + 3 for qx, qy in placed):
                    continue
                if any(math.hypot(lx - qx, ly - qy) < R + 4 for qx, qy in ppx):
                    continue
                if min(seg_dist(lx, ly, a1, b1) for a1, b1 in zip(rpx, rpx[1:])) < R + 3:
                    continue
                best = (lx, ly)
                break
            if best:
                break
        best = best or (px, py - 24)
        placed.append(best)
        labels.append((px, py, best, e))

    out = [f'<svg class="route" viewBox="0 0 {width} {height}" role="img" '
           f'aria-label="위치 확인용 경로. 번호는 목록 번호" xmlns="http://www.w3.org/2000/svg">',
           f'<rect width="{width}" height="{height}" fill="#ffffff"/>']
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in rpx)
    out.append(f'<polyline points="{line}" fill="none" stroke="#9aa6b8" stroke-width="5" stroke-linejoin="round" stroke-linecap="round"/>')
    out.append(f'<polyline points="{line}" fill="none" stroke="#2563eb" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>')
    for (x, y), name in ((rpx[0], "출발"), (rpx[-1], "도착")):
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#ffffff" stroke="#1f2328" stroke-width="2"/>'
                   f'<text x="{x:.1f}" y="{y + 20:.1f}" text-anchor="middle" class="tag">{name}</text>')
    for px, py, (lx, ly), e in labels:
        out.append(f'<line x1="{px:.1f}" y1="{py:.1f}" x2="{lx:.1f}" y2="{ly:.1f}" stroke="#5c626b" stroke-width="1"/>')
    for px, py, _, e in labels:
        out.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3" class="dot-{e["level"]}"/>')
    for _, _, (lx, ly), e in labels:
        out.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="{R}" class="no-{e["level"]}"/>'
                   f'<text x="{lx:.1f}" y="{ly + 3.6:.1f}" text-anchor="middle" class="no-text no-text-{e["level"]}">{e["no"]}</text>')

    # 북쪽 표시 + 축척 막대
    nx, ny = width - 30, 30
    out.append(f'<path d="M{nx} {ny - 16} L{nx + 7} {ny + 4} L{nx} {ny} L{nx - 7} {ny + 4} Z" fill="#1f2328"/>'
               f'<text x="{nx}" y="{ny + 20}" text-anchor="middle" class="tag">N</text>')
    bar_m = next(m for m in (10, 20, 25, 50, 100, 200, 250, 500, 1000) if m * s >= 70)
    out.append(f'<g transform="translate(16,{height - 18})"><rect width="{bar_m * s:.1f}" height="4" y="-4" fill="#1f2328"/>'
               f'<text y="-9" class="tag">{bar_m} m</text></g>')
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------------------
# HTML / CSV
# ---------------------------------------------------------------------------

def _e(v) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def _badge(level: str) -> str:
    return (f'<span class="lv lv-{level}"><span class="sw">{LEVEL_GLYPH[level]}</span>'
            f'{LEVEL_LABEL[level]}</span>')


def build_html(events: list[dict], traj: list[dict], thresholds: dict | None = None, area: str = "",
               photos: dict | None = None) -> str:
    """photos: prepare_photos 결과. 사진이 있는 지점은 사진과 위치 표시(대시보드와 같은 overlay_svg)를 넣는다."""
    sm = summary(events, traj, area)
    items = report_items(events, thresholds)
    bl = sm["by_level"]

    rows = "".join(
        f"<tr><th>{KIND_LABEL[k]}</th>" + "".join(f"<td>{c[lv]}</td>" for lv in LEVEL_LABEL) + f"<td>{sum(c.values())}</td></tr>"
        for k, c in sm["counts"].items())
    total_row = "<tr class='sum'><th>계</th>" + "".join(f"<td>{bl[lv]}</td>" for lv in LEVEL_LABEL) + f"<td>{sm['total']}</td></tr>"

    cards = []
    for e in items:
        p = (photos or {}).get(e["id"])
        photo = ""
        if p:
            cap = " · ".join(filter(None, [p.get("caption"),
                                           f"표시: {contact_label(e['leg'])}" if p["overlay"] else ""]))
            photo = (f'<figure class="photo"><div class="ph" style="aspect-ratio: {p["w"]} / {p["h"]}">'
                     f'<img src="{_e(p["src"])}" alt="{_e(KIND_LABEL[e["kind"]])} {_e(fmt_value(e["value"], e["unit"]))} 현장 사진">'
                     f'{p["overlay"]}</div>{f"<figcaption>{_e(cap)}</figcaption>" if cap else ""}</figure>')
        note = f"<dt>메모</dt><dd>{_e(e['note'])}</dd>" if e["note"] else ""
        cards.append(f"""
<article class="item item-{e['level']}{' has-photo' if photo else ''}">
  <div class="no no-{e['level']}">{e['no']}</div>
  <div class="body">
    <h3>{_badge(e['level'])} {KIND_LABEL[e['kind']]} <span class="val">{_e(fmt_value(e['value'], e['unit']))}</span></h3>
    <p class="crit">기준: {_e(e['criterion'])} <span>(기준의 {e['ratio']:.1f}배)</span></p>
    <dl>
      <dt>측정 방식</dt><dd>{_e(e['method'])}</dd>
      <dt>위도·경도</dt><dd>{e['lat']:.6f}, {e['lon']:.6f}</dd>
      <dt>측정 시각</dt><dd>{fmt_dt(e['t'], with_date=False)}</dd>
      {note}
      <dt>ID</dt><dd>{_e(e['id'])}</dd>
    </dl>
    {photo}
  </div>
</article>""")

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>보도 측정 신고서 · {_e(sm['session'])}</title>
<style>
  @page {{ size: A4; margin: 14mm 14mm 16mm; }}
  * {{ box-sizing: border-box; }}
  html {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  body {{ margin: 0; background: #e9e9e6; color: #1f2328;
         font: 10.5pt/1.5 "Malgun Gothic", "Apple SD Gothic Neo", system-ui, sans-serif; }}
  .sheet {{ width: 210mm; min-height: 297mm; margin: 12px auto; padding: 14mm; background: #ffffff; }}
  h1 {{ font-size: 17pt; margin: 0 0 2mm; }}
  h2 {{ font-size: 12.5pt; margin: 7mm 0 3mm; padding-bottom: 1.5mm; border-bottom: 1.5px solid #1f2328; break-after: avoid; }}
  .sub {{ color: #5c626b; margin: 0 0 5mm; }}
  .summary {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6mm; break-inside: avoid; }}
  .facts {{ display: grid; grid-template-columns: auto 1fr; gap: 1.2mm 4mm; margin: 0; }}
  .facts dt {{ color: #5c626b; }}
  .facts dd {{ margin: 0; font-weight: 600; overflow-wrap: anywhere; }}
  table {{ border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }}
  th, td {{ border: 1px solid #c9cbc6; padding: 1.2mm 2.5mm; text-align: right; }}
  th {{ text-align: left; font-weight: 600; }}
  thead th {{ background: #f1f1ee; text-align: center; }}
  tr.sum th, tr.sum td {{ font-weight: 700; background: #f7f7f5; }}
  .lv {{ display: inline-flex; align-items: center; gap: 1.2mm; font-weight: 700; white-space: nowrap; }}
  .lv .sw {{ display: inline-grid; place-items: center; min-width: 4.6mm; height: 4.6mm; padding: 0 0.8mm; border-radius: 1.2mm;
            font-size: 8pt; font-weight: 800; line-height: 1; }}
  .lv-danger .sw {{ background: #d03b3b; color: #ffffff; }}
  .lv-warn .sw {{ background: #fab219; color: #1a1a19; }}
  .lv-ok .sw {{ background: #0ca30c; color: #1a1a19; }}
  .figure {{ break-inside: avoid; }}
  .route {{ display: block; width: 100%; height: auto; border: 1px solid #c9cbc6; }}
  .route .tag {{ font: 600 11px "Malgun Gothic", system-ui, sans-serif; fill: #1f2328; }}
  .route .no-danger {{ fill: #d03b3b; stroke: #ffffff; stroke-width: 1.5; }}
  .route .no-warn {{ fill: #fab219; stroke: #ffffff; stroke-width: 1.5; }}
  .route .dot-danger {{ fill: #d03b3b; stroke: #ffffff; stroke-width: 1; }}
  .route .dot-warn {{ fill: #fab219; stroke: #1f2328; stroke-width: 0.8; }}
  .route .no-text {{ font: 700 10px system-ui, sans-serif; }}
  .route .no-text-danger {{ fill: #ffffff; }}
  .route .no-text-warn {{ fill: #1a1a19; }}
  .cap {{ color: #5c626b; font-size: 9pt; margin: 1.5mm 0 0; }}
  .item {{ display: grid; grid-template-columns: 9mm 1fr; gap: 3mm; padding: 3mm 0; border-bottom: 1px solid #d9dad6;
          break-inside: avoid; page-break-inside: avoid; }}
  .item .no {{ width: 8mm; height: 8mm; border-radius: 50%; display: grid; place-items: center; font-weight: 800; font-size: 10pt; }}
  .no-danger {{ background: #d03b3b; color: #ffffff; }}
  .no-warn {{ background: #fab219; color: #1a1a19; }}
  .item h3 {{ margin: 0; font-size: 11.5pt; display: flex; align-items: baseline; gap: 2mm; flex-wrap: wrap; }}
  .item .val {{ font-size: 14pt; font-weight: 800; font-variant-numeric: tabular-nums; }}
  .item .crit {{ margin: 0.8mm 0 1.5mm; font-weight: 600; }}
  .item .crit span {{ color: #5c626b; font-weight: 400; }}
  .item dl {{ display: grid; grid-template-columns: 20mm 1fr; gap: 0.6mm 3mm; margin: 0; font-size: 9.5pt; }}
  .item dt {{ color: #5c626b; }}
  .item dd {{ margin: 0; word-break: keep-all; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }}
  /* 사진이 있는 지점: 왼쪽 정보, 오른쪽 사진 (지점 단위로 쪽이 나뉘지 않으므로 같은 쪽에 남는다) */
  .has-photo .body {{ display: grid; grid-template-columns: minmax(0, 1fr) 64mm; column-gap: 5mm; align-items: start; }}
  .has-photo .body > h3, .has-photo .body > .crit {{ grid-column: 1 / -1; }}
  .photo {{ margin: 0; }}
  .ph {{ position: relative; width: 100%; max-height: 90mm; border: 1px solid #c9cbc6; overflow: hidden; }}
  .ph img {{ position: absolute; inset: 0; width: 100%; height: 100%; display: block; }}
  .ph .ph-mark {{ position: absolute; inset: 0; width: 100%; height: 100%; }}
  .photo figcaption {{ color: #5c626b; font-size: 8.5pt; margin-top: 1mm; }}
  @media print {{
    body {{ background: none; }}
    .sheet {{ width: auto; min-height: 0; margin: 0; padding: 0; }}
  }}
</style>
</head>
<body>
<main class="sheet">
  <h1>보도 측정 결과 신고서</h1>
  <p class="sub">사족보행 로봇 측정값 기반 · 위험·주의 지점 {len(items)}건</p>

  <section class="summary" aria-label="요약">
    <dl class="facts">
      <dt>세션</dt><dd>{_e(sm['session'])}</dd>
      <dt>측정 일시</dt><dd>{_e(sm['period'])}</dd>
      <dt>구간</dt><dd>{_e(sm['area']) or '—'}</dd>
      <dt>이동 거리</dt><dd>{sm['distance_m']:,} m</dd>
      <dt>측정 지점</dt><dd>{sm['total']}개 (위험 {bl['danger']} · 주의 {bl['warn']} · 정상 {bl['ok']})</dd>
    </dl>
    <table aria-label="종류별·판정별 건수">
      <thead><tr><th>종류</th>{''.join(f'<th>{_badge(lv)}</th>' for lv in LEVEL_LABEL)}<th>계</th></tr></thead>
      <tbody>{rows}{total_row}</tbody>
    </table>
  </section>

  <section class="figure">
    <h2>위치 확인용 경로</h2>
    {route_svg(traj, items)}
    <p class="cap">번호는 아래 목록 번호, 작은 점은 측정 위치입니다. 북쪽이 위, 파란 선은 이동 경로입니다.</p>
  </section>

  <section>
    <h2>신고 대상 지점 ({len(items)}건 · 위험 먼저, 같은 판정 안에서는 기준 대비 초과 정도가 큰 순)</h2>
    {''.join(cards)}
  </section>
</main>
</body>
</html>
"""


def _csv_text(v) -> str:
    """CSV 수식 주입 방지: =, +, -, @ 로 시작하는 문자열 앞에 ' 를 붙인다."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def build_csv_rows(events: list[dict], thresholds: dict | None = None, photos: dict | None = None) -> list[list[str]]:
    rows = []
    for e in report_items(events, thresholds):
        cross = e["source"] == "camera+foot"
        rows.append([
            e["no"], LEVEL_LABEL[e["level"]], KIND_LABEL[e["kind"]], fmt_num(e["value"], e["unit"]),
            UNIT_TEXT[e["unit"]] or "점수", e["criterion"], f"{e['ratio']:.2f}", e["method"],
            fmt_num(e["value"], e["unit"]) if e["source"] != "foot" else "",
            fmt_num(e["value_foot"] if cross else e["value"], e["unit"]) if e["source"] != "camera" else "",
            fmt_num(abs(e["value_foot"] - e["value"]), e["unit"]) if cross else "",
            e["leg"], f"{e['lat']:.6f}", f"{e['lon']:.6f}",
            datetime.fromtimestamp(e["t"], KST).isoformat(timespec="seconds"),
            _csv_text(e["note"]), _csv_text((photos or {}).get(e["id"], {}).get("src", "")),
            _csv_text(e["session"]), _csv_text(e["id"]),
        ])
    return rows


def write_report(events_path: str | Path, traj_path: str | Path, out_html: str | Path,
                 thresholds: dict | None = None, area: str = "") -> tuple[Path, Path, dict]:
    events, traj = read_events(events_path), read_trajectory(traj_path)
    if any(e["lat"] is None for e in events) or any(p["lat"] is None for p in traj):
        raise ValueError("신고서에는 lat, lon이 필요합니다. config.yaml의 geo를 채운 뒤 다시 생성하세요.")
    out_html = Path(out_html)
    out_csv = out_html.with_suffix(".csv")
    out_html.parent.mkdir(parents=True, exist_ok=True)
    photos = prepare_photos(events, Path(events_path).parent, out_html.parent)  # 사본: <HTML 폴더>/photos/
    out_html.write_text(build_html(events, traj, thresholds, area, photos), encoding="utf-8")
    with open(out_csv, "w", encoding=ENCODING, newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLUMNS)
        w.writerows(build_csv_rows(events, thresholds, photos))
    return out_html, out_csv, summary(events, traj, area)
