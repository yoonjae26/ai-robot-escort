import hashlib
import json
import re
from pathlib import Path

import pytest
from PIL import Image

from stepmap import demo
from stepmap.dashboard import write_dashboard
from stepmap.events import merge_events, read_events, write_events
from stepmap.photos import PHOTO_SHORT_SIDE, overlay_svg, photo_caption, prepare_photos, thumb_scale
from stepmap.report import write_report

FORBIDDEN = ("가상", "예시", "샘플", "demo", "mock", "test", "sample")


def make_jpg(path: Path, size=(620, 800), gps=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", size, (120, 110, 100))
    exif = Image.Exif()
    if gps:
        exif[0x8825] = {2: (33.0, 29.0, 0.0), 4: (126.0, 29.0, 0.0)}  # GPSInfo
    im.save(path, "JPEG", exif=exif)
    return path


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def ev(**kw):
    e = {"id": "ev_0001", "kind": "step", "level": "danger", "leg": "", "image": "", "image_mark": ""}
    e.update(kw)
    return e


# --- 사본 ---------------------------------------------------------------------------

def test_copy_resized_without_exif_original_untouched(tmp_path):
    src = make_jpg(tmp_path / "data" / "photos" / "big shot.jpg", (2000, 1500), gps=True)
    before = md5(src)
    photos = prepare_photos([ev(kind="loose", image="photos/big shot.jpg", image_mark="0.5,0.5,0.1")],
                            tmp_path / "data", tmp_path / "out")
    p = photos["ev_0001"]
    assert p["src"] == "photos/ev_0001_big_shot.jpg" and (p["w"], p["h"]) == (960, PHOTO_SHORT_SIDE)
    with Image.open(tmp_path / "out" / p["src"]) as im:
        assert im.size == (960, 720) and 0x8825 not in im.getexif()  # GPS 없음
    with Image.open(src) as orig:
        assert md5(src) == before and orig.size == (2000, 1500)  # 원본 그대로
    assert p["mark"] == [0.5, 0.5, 0.1] and p["overlay"].startswith("<svg")


def test_small_photo_not_upscaled_and_missing_or_broken_skipped(tmp_path):
    make_jpg(tmp_path / "photos" / "small.jpg", (400, 300))
    (tmp_path / "photos" / "broken.jpg").write_bytes(b"not an image")
    events = [ev(id="a", image="photos/small.jpg"), ev(id="b", image="photos/none.jpg"),
              ev(id="c", image="photos/broken.jpg"), ev(id="d")]
    photos = prepare_photos(events, tmp_path, tmp_path / "out")
    assert set(photos) == {"a"}
    assert (photos["a"]["w"], photos["a"]["h"]) == (400, 300) and photos["a"]["overlay"] == ""


# --- 위치 표시 -----------------------------------------------------------------------

def test_overlay_loose_dashed_with_leg_label():
    svg = overlay_svg({"w": 740, "h": 986, "mark": [0.5, 0.5, 0.05]}, "loose", "danger", "FL")
    assert 'stroke-dasharray' in svg and "발 접촉 위치 (추정) · 앞 왼발(FL)" in svg
    assert svg.count('stroke="#ffffff"') >= 1 and 'stroke="#EF6461"' in svg  # 흰 테두리 + 판정 색
    assert 'cx="370.0" cy="493.0" r="37.0"' in svg


@pytest.mark.parametrize("kind", ["step", "crack", "slope"])
def test_no_overlay_for_visible_problems(kind):
    """단차·균열 등은 문제가 사진에 보이므로 image_mark가 있어도 동그라미를 그리지 않는다."""
    photo = {"w": 620, "h": 827, "mark": [0.35, 0.4, 0.13]}
    assert overlay_svg(photo, kind, "danger") == ""
    assert overlay_svg(photo, kind, "danger", min_font_px=11, scale=0.36) == ""


def test_loose_label_stays_inside_photo():
    svg = overlay_svg({"w": 620, "h": 827, "mark": [0.02, 0.02, 0.05]}, "loose", "warn", "RR")
    assert "stroke-dasharray" in svg and 'stroke="#F7B558"' in svg
    x, y, w, h = (float(v) for v in re.search(r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)"', svg).groups())
    assert 0 <= x and x + w <= 620 and 0 <= y and y + h <= 827  # 위에 자리가 없으면 아래로
    assert overlay_svg({"w": 10, "h": 10, "mark": None}, "loose", "danger") == ""


# --- demo --photos ------------------------------------------------------------------

@pytest.fixture()
def photo_dir(tmp_path):
    d = tmp_path / "data" / "photos"
    for name, _, _, _ in demo.PHOTO_LINKS:
        make_jpg(d / name)
    return d


def test_demo_photos_link_rules(tmp_path, photo_dir):
    _, plain = demo.generate(tmp_path / "plain")
    _, events = demo.generate(tmp_path / "data", photos_dir=photo_dir)
    linked = {e["image"]: e for e in events if e["image"]}
    assert set(linked) == {"photos/step_curb_gap.jpg", "photos/crack_broken_hole.jpg", "photos/loose_normal.jpg"}
    step, crack, loose = (linked[f"photos/{n}"] for n in ("step_curb_gap.jpg", "crack_broken_hole.jpg", "loose_normal.jpg"))
    assert (step["kind"], step["level"], step["source"], step["value"]) == ("step", "danger", "camera+foot", 4.8)
    assert step["note"] == "경계석 이음부 벌어짐·단차"
    assert (crack["kind"], crack["level"], crack["confidence"]) == ("crack", "danger", 0.91)
    assert crack["note"] == "블럭 파손·함몰, 점자블럭 인접"
    assert (loose["kind"], loose["level"], loose["value"]) == ("loose", "danger", 8.5)
    assert loose["note"] == "외관 정상, 체중 시 기울어짐" and loose["image_mark"] == "0.5,0.5,0.05"  # 비고는 그대로
    assert not any("발 접촉으로 확인" in e["note"] for e in events)  # 사진 설명은 데이터에 넣지 않는다
    # 위치·값·판정은 그대로
    keep = ("id", "t", "x", "y", "lat", "lon", "kind", "value", "unit", "source", "leg", "confidence", "level", "value_foot")
    assert [{k: e[k] for k in keep} for e in events] == [{k: e[k] for k in keep} for e in plain]


def test_demo_photos_missing_file_skips_only_that_link(tmp_path, photo_dir):
    (photo_dir / "crack_broken_hole.jpg").unlink()
    _, events = demo.generate(tmp_path / "data", photos_dir=photo_dir)
    assert sorted(e["kind"] for e in events if e["image"]) == ["loose", "step"]


def test_split_merge_roundtrip_with_photos(tmp_path, photo_dir):
    out = tmp_path / "data"
    demo.generate(out, split=True, photos_dir=photo_dir)
    rows = [r for name in demo.RAW_FILES for r in read_events(out / "raw" / name, raw=True)]
    merged, _ = merge_events(rows)
    write_events(out / "merged.csv", merged)
    assert (out / "merged.csv").read_bytes() == (out / "events.csv").read_bytes()


# --- 대시보드·신고서 ------------------------------------------------------------------

def test_dashboard_and_report_show_photos(tmp_path, photo_dir):
    data = tmp_path / "data"
    demo.generate(data, photos_dir=photo_dir)
    out = tmp_path / "outputs"
    html = write_dashboard(data / "events.csv", data / "trajectory.csv", out / "dashboard.html").read_text(encoding="utf-8")
    payload = json.loads(re.search(r'<script id="stepmap-data" type="application/json">(.*?)</script>', html, re.S).group(1))
    photos = {e["id"]: e["photo"] for e in payload["events"] if e["photo"]}
    assert len(photos) == 3 and all((out / p["src"]).is_file() for p in photos.values())
    kinds = {e["id"]: e["kind"] for e in payload["events"]}
    assert {kinds[i] for i, p in photos.items() if p["overlay"]} == {"loose"}  # 동그라미는 흔들림만
    assert all(not p["overlay_thumb"] for i, p in photos.items() if kinds[i] != "loose")
    assert all(not p["src"].startswith(("/", "C:", "data")) for p in photos.values())  # HTML 기준 상대 경로

    rep_html, rep_csv, _ = write_report(data / "events.csv", data / "trajectory.csv", out / "report.html")
    text = rep_html.read_text(encoding="utf-8")
    assert len(re.findall(r'<article class="item item-\w+ has-photo">', text)) == 3
    assert text.count('<svg class="ph-mark"') == 1 and "발 접촉 위치 (추정) · 앞 왼발(FL)" in text
    caps = re.findall(r"<figcaption>(.*?)</figcaption>", text)
    assert caps == ["외관 정상, 발 접촉으로 확인 · 표시: 발 접촉 위치 (추정) · 앞 왼발(FL)"]  # 단차·균열은 사진만
    for doc in (html, text, rep_csv.read_text(encoding="utf-8-sig")):
        for w in FORBIDDEN:
            assert w not in doc.lower(), w

    # 사본이 없어지면 사진 영역을 만들지 않는다 (원본을 지우고 다시 생성)
    for p in photo_dir.iterdir():
        p.unlink()
    html2 = write_dashboard(data / "events.csv", data / "trajectory.csv", tmp_path / "o2" / "dashboard.html").read_text(encoding="utf-8")
    payload2 = json.loads(re.search(r'<script id="stepmap-data" type="application/json">(.*?)</script>', html2, re.S).group(1))
    assert all(e["photo"] is None for e in payload2["events"])


# --- 사진 설명·썸네일 라벨 --------------------------------------------------------------

def font_px(svg: str) -> float:
    return float(re.search(r'font-size="([\d.]+)"', svg).group(1))


def label_of(svg: str) -> str:
    return re.search(r"<text[^>]*>(.*?)</text>", svg).group(1)


def test_caption_by_kind():
    assert photo_caption("loose") == "외관 정상, 발 접촉으로 확인"
    assert photo_caption("step") == photo_caption("crack") == ""


def test_thumb_label_at_least_11px_on_screen():
    for w, h, kind, leg in ((620, 827, "loose", "FR"), (620, 642, "loose", "RL"), (720, 959, "loose", "FL")):
        photo = {"w": w, "h": h, "mark": [0.5, 0.5, 0.05]}
        s = thumb_scale(w, h)
        thumb = overlay_svg(photo, kind, "danger", leg, min_font_px=11, scale=s)
        assert font_px(thumb) * s >= 11 - 1e-6
        big = overlay_svg(photo, kind, "danger", leg)
        assert font_px(big) == pytest.approx(0.045 * min(w, h), abs=0.1)  # 크게 보기·신고서는 그대로


def test_thumb_label_shortened_only_when_it_overflows():
    photo = {"w": 720, "h": 959, "mark": [0.5, 0.5, 0.05]}
    fits = overlay_svg(photo, "loose", "danger", "FL", min_font_px=11, scale=thumb_scale(720, 959))
    assert label_of(fits) == "발 접촉 위치 (추정) · 앞 왼발(FL)"
    # 좁은 화면(사진 1px = 화면 0.15px): 11px로 키우면 사진 폭을 넘는다 → 짧은 라벨
    short = overlay_svg(photo, "loose", "danger", "FL", min_font_px=11, scale=0.15)
    assert label_of(short) == "발 접촉 (추정) · FL"
    # 동그라미가 사진을 거의 채워 위·아래 자리가 없으면 → 짧은 라벨
    full = {"w": 720, "h": 959, "mark": [0.5, 0.5, 0.66]}
    assert label_of(overlay_svg(full, "loose", "danger", "FL", min_font_px=11, scale=0.3)) == "발 접촉 (추정) · FL"
    assert label_of(overlay_svg(full, "loose", "danger", "FL")) == "발 접촉 위치 (추정) · 앞 왼발(FL)"  # 크게 보기는 그대로
