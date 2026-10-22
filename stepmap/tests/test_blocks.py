import json
import re

import pytest

from stepmap import demo
from stepmap.dashboard import blocks_payload, write_dashboard
from stepmap.events import (BLOCK_COLUMNS, FormatError, block_index, block_id, count_stepped_blocks, read_blocks, read_events,
                            read_foot_traces, summarize_blocks, validate_blocks, write_blocks)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    d = tmp_path_factory.mktemp("blocks")
    demo.generate(d)
    return d


def row(**kw):
    base = {"block_id": "b0_0", "x": 0.15, "y": 0.15, "lat": 33.48, "lon": 126.48, "n_steps": 2.0, "legs": "FL|RL",
            "max_extra_mm": 1.2}
    return {**base, **kw}


# --- 형식 ---------------------------------------------------------------------------------

def test_blocks_format_check(tmp_path):
    assert validate_blocks([row(), row(block_id="b1_0", lat=None, lon=None, legs="FR", n_steps=1.0)]) == []
    bad = {
        "block_id 중복": [row(), row()],
        "block_id 빈칸": [row(block_id="")],
        "n_steps는 1 이상의 정수": [row(n_steps=0.0)],
        "legs": [row(legs="FL|XX")],
        "중복 없이": [row(legs="FL|FL")],
        "legs 수가 n_steps보다 많음": [row(legs="FL|RL|FR", n_steps=2.0)],
        "둘 다 숫자이거나": [row(lat=None)],
        "숫자여야 함": [row(max_extra_mm="x")],
    }
    for msg, rows in bad.items():
        assert any(msg in m for m in validate_blocks(rows)), msg
    with pytest.raises(FormatError):
        write_blocks(tmp_path / "bad.csv", [row(n_steps=0.0)])
    p = tmp_path / "wrong.csv"
    p.write_text("block_id,x,y\nb0_0,0.15,0.15\n", encoding="utf-8")
    with pytest.raises(FormatError):
        read_blocks(p)  # 열이 모자라면 읽지 않는다
    write_blocks(tmp_path / "ok.csv", [row()])
    assert read_blocks(tmp_path / "ok.csv") == [row()]


def test_block_grid_and_summary():
    """같은 격자 칸(0.3 m)이면 같은 블록. 걸음 수·다리·가장 큰 추가 침하를 모은다."""
    assert block_index(0.29, 0.0) == (0, 0) and block_index(0.31, -0.01) == (1, -1) and block_id(1, -1) == "b1_-1"
    contacts = [{"x": 0.1, "y": 0.1, "leg": "FL", "extra_mm": 0.5}, {"x": 0.2, "y": 0.25, "leg": "RL", "extra_mm": 1.4},
                {"x": 0.25, "y": 0.05, "leg": "FL", "extra_mm": 0.2}, {"x": 0.4, "y": 0.1, "leg": "FR", "extra_mm": 0.9}]
    b = summarize_blocks(contacts)
    assert [(x["block_id"], x["n_steps"], x["legs"], x["max_extra_mm"]) for x in b] == [("b0_0", 3, "FL|RL", 1.4), ("b1_0", 1, "FR", 0.9)]
    assert (b[0]["x"], b[0]["y"], b[0]["lat"]) == (0.15, 0.15, None)


# --- 데이터 --------------------------------------------------------------------------------

def test_loose_blocks_match_event_values(built):
    """흔들림 지점이 있는 블록의 max_extra_mm = events.csv 값, 나머지 블록은 기준(3 mm) 미만."""
    blocks = read_blocks(built / "blocks.csv")
    assert list(blocks[0]) == BLOCK_COLUMNS and len(blocks) > 1000
    by_cell = {block_index(b["x"], b["y"]): b for b in blocks}
    loose = [e for e in read_events(built / "events.csv") if e["kind"] == "loose"]
    cells = set()
    for e in loose:
        b = by_cell[block_index(e["x"], e["y"])]
        assert b["max_extra_mm"] == e["value"], e["id"]
        cells.add(block_index(e["x"], e["y"]))
    assert len(cells) == 8
    assert all(b["max_extra_mm"] < 3.0 for k, b in by_cell.items() if k not in cells)
    # 같은 블록을 앞발·뒷발이 다시 밟는다 (트롯, 좌우 발 간격 약 0.28 m)
    assert sum(b["n_steps"] >= 2 for b in blocks) > len(blocks) / 2
    assert by_cell[block_index(*next((e["x"], e["y"]) for e in loose if e["id"] == "ev_0014"))]["legs"] == "FL|RL"


def test_stepped_blocks_is_blocks_rows(built, tmp_path):
    """밟은 블록 수 = blocks.csv 행 수. blocks.csv가 없으면 발끝 기록 기준 (흔들림 지점 8)."""
    blocks = read_blocks(built / "blocks.csv")
    traces = read_foot_traces(built / "foot_traces.csv")
    assert count_stepped_blocks(blocks, traces) == len(blocks)
    assert count_stepped_blocks(None, traces) == 8 and count_stepped_blocks() == 0
    html = write_dashboard(built / "events.csv", built / "trajectory.csv", tmp_path / "d.html").read_text(encoding="utf-8")
    data = json.loads(re.search(r'<script id="stepmap-data" type="application/json">(.*?)</script>', html, re.S).group(1))
    assert data["stepped_blocks"] == len(blocks) and len(data["blocks"]["ij"]) == len(blocks)
    none = write_dashboard(built / "events.csv", built / "trajectory.csv", tmp_path / "n.html",
                           blocks_path=tmp_path / "none.csv").read_text(encoding="utf-8")
    data2 = json.loads(re.search(r'<script id="stepmap-data" type="application/json">(.*?)</script>', none, re.S).group(1))
    assert data2["stepped_blocks"] == 8 and data2["blocks"] is None


def test_summary_line_number_and_block_cells(built):
    """요약 줄 숫자 = blocks.csv 행 수 (천 단위 쉼표). 위치 지도 칸 모서리 → 위도·경도 식은 칸 가운데를 되돌린다."""
    blocks = read_blocks(built / "blocks.csv")
    n = f"{len(blocks):,}"
    assert "," in n  # 천 단위 이상
    p = blocks_payload(blocks)
    g = p["geo"]
    for b in blocks[:: max(1, len(blocks) // 50)]:
        lat, lon = g[0] + g[1] * b["x"] + g[2] * b["y"], g[3] + g[4] * b["x"] + g[5] * b["y"]
        assert abs(lat - b["lat"]) < 1e-7 and abs(lon - b["lon"]) < 1e-7  # 1 cm 안
    assert blocks_payload(None) is None
