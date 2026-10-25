"""StepMap 명령줄 진입점.

Phase A 하위 명령: demo, map, merge, report.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__


def _thresholds(config_path: str) -> dict | None:
    """config.yaml이 있으면 판정 기준을 읽고, 없으면 None(기본값 사용)."""
    if not Path(config_path).exists():
        return None
    from .events import load_config, thresholds_from_config

    return thresholds_from_config(load_config(config_path))


def _block_size(config_path: str) -> float:
    """config.yaml의 block.size_m (없으면 기본 0.3 m)."""
    from .events import BLOCK_SIZE_M, block_size_from_config, load_config

    return block_size_from_config(load_config(config_path)) if Path(config_path).exists() else BLOCK_SIZE_M


def cmd_demo(args: argparse.Namespace) -> int:
    from .demo import SESSION, generate
    from .events import display_meters, path_length

    traj, events = generate(args.output, _thresholds(args.config), split=args.split, photos_dir=args.photos,
                            block_size=_block_size(args.config))
    out = Path(args.output)
    print(f"세션 {SESSION}: 궤적 {len(traj)}점 ({display_meters(path_length(traj))} m), 측정 지점 {len(events)}개")
    print(f"  -> {out / 'trajectory.csv'}")
    print(f"  -> {out / 'events.csv'}")
    print(f"  -> {out / 'blocks.csv'} (밟은 블록)")
    for e in events:
        if e["image"]:
            print(f"  사진 {e['image']} → {e['id']} ({e['kind']} {e['value']}, {e['level']})")
    from .demo import generate_history

    for date, h_traj, h_events in generate_history(args.output, _thresholds(args.config)):
        n = {lv: sum(e["level"] == lv for e in h_events) for lv in ("danger", "warn", "ok")}
        print(f"지난 점검 {date}: {display_meters(path_length(h_traj))} m, 위험 {n['danger']} · 주의 {n['warn']} · 정상 {n['ok']}"
              f" -> {out / 'history' / date}")
    if args.split:
        from .demo import RAW_FILES, RAW_TRACES

        for name in RAW_FILES + (RAW_TRACES,):
            print(f"  -> {out / 'raw' / name}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from .events import FormatError, load_config, thresholds_from_config
    from .report import write_report

    cfg = load_config(args.config) if Path(args.config).exists() else {}
    area = str((cfg.get("report") or {}).get("area") or "")
    try:
        html_path, csv_path, sm = write_report(args.events, args.trajectory, args.output,
                                               thresholds_from_config(cfg), area)
    except (FormatError, ValueError) as e:
        print(f"stepmap report: {e}", file=sys.stderr)
        return 1
    bl = sm["by_level"]
    print(f"신고서: 이동 거리 {sm['distance_m']} m, 측정 지점 {sm['total']}개 → 신고 대상 위험 {bl['danger']} · 주의 {bl['warn']}")
    print(f"  -> {html_path}")
    print(f"  -> {csv_path}")
    # 대시보드의 "신고서 열기" 버튼은 map이 만들 때 같은 폴더의 report.html을 확인해 넣는다
    dash = Path(html_path).parent / "dashboard.html"
    if dash.is_file() and '"report":null' in dash.read_text(encoding="utf-8"):
        print(f"  참고: {dash}는 신고서보다 먼저 만들어져 '신고서 열기' 버튼이 없습니다. map을 다시 실행하면 연결됩니다.")
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    import glob

    from .events import (FormatError, georef_from_config, is_foot_traces_file, link_foot_traces, load_config,
                         merge_events, merge_from_config, read_events, read_foot_traces, thresholds_from_config,
                         write_events, write_foot_traces)

    # PowerShell은 와일드카드를 펼치지 않으므로 여기서 펼친다
    paths = []
    for pattern in args.inputs:
        found = sorted(glob.glob(pattern)) if any(ch in pattern for ch in "*?[") else [pattern]
        if not found:
            print(f"stepmap merge: 파일 없음 {pattern}", file=sys.stderr)
            return 1
        paths += found
    cfg = load_config(args.config) if Path(args.config).exists() else {}
    try:
        rows, trace_rows = [], []
        for path in paths:
            if is_foot_traces_file(path):  # 발끝 기록은 머리줄로 구분해 따로 읽는다
                part = read_foot_traces(path, raw=True)
                print(f"  {path}: 발끝 기록 {len(part)}행")
                trace_rows += part
                continue
            part = read_events(path, raw=True)
            print(f"  {path}: {len(part)}행")
            rows += part
        events, stats = merge_events(rows, thresholds_from_config(cfg), merge_from_config(cfg), georef_from_config(cfg))
        write_events(args.output, events)
        linked, unmatched = link_foot_traces(trace_rows, events) if trace_rows else ([], [])
        traces_out = Path(args.output).parent / "foot_traces.csv"
        if trace_rows:
            write_foot_traces(traces_out, linked)
    except FormatError as e:
        print(f"stepmap merge: {e}", file=sys.stderr)
        return 1
    print(f"입력 {stats['inputs']}행 → 측정 지점 {stats['events']}개 "
          f"(단차 교차 측정 {stats['pairs']}쌍, 균열·경사 중복 {stats['duplicates_dropped']}건 제거)")
    print(f"  -> {args.output}")
    if trace_rows:
        # 발끝 기록: 흔들림 지점의 시각·다리로 연결해 id를 채운다. 짝이 없는 기록은 경고만
        for u in unmatched:
            print(f"경고: 짝이 없는 발끝 기록 (접지 시각 {u['t_event']}, 다리 {u['leg']}, {u['rows']}행) — 저장하지 않음",
                  file=sys.stderr)
        print(f"발끝 기록 {len({r['id'] for r in linked})}개 지점 연결" + (f", 짝 없음 {len(unmatched)}개" if unmatched else ""))
        print(f"  -> {traces_out}")
    return 0


def cmd_map(args: argparse.Namespace) -> int:
    from .dashboard import MissingLatLon, write_dashboard
    from .events import FormatError, load_config

    cfg = load_config(args.config) if Path(args.config).exists() else {}
    robot = cfg.get("robot") or {}
    meta = {"area": str((cfg.get("report") or {}).get("area") or ""),
            "robot": str(robot.get("name") or ""),
            "model": str(robot.get("model") or ""),
            "sensors": [str(x) for x in robot.get("sensors") or []],
            "battery": robot.get("battery")}
    try:
        out = write_dashboard(args.events, args.trajectory, args.output, _thresholds(args.config), meta, args.traces,
                              args.history, args.blocks, _block_size(args.config))
    except (FormatError, MissingLatLon) as e:
        print(f"stepmap map: {e}", file=sys.stderr)
        return 1
    print(f"대시보드 -> {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stepmap",
        description="보도의 단차·경사·균열·흔들리는 블럭 측정 결과를 지도로 보여주는 도구",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser("demo", help="예시 데이터 생성 (events.csv, trajectory.csv)")
    p.add_argument("-o", "--output", default="data/", help="출력 디렉터리 (기본: data/)")
    p.add_argument("-c", "--config", default="config.yaml",
                   help="판정 기준을 읽을 설정 파일 (기본: config.yaml, 없으면 계획서 6.3 기본값)")
    p.add_argument("--photos", metavar="DIR",
                   help="현장 사진 폴더 (step_curb_gap.jpg, crack_broken_hole.jpg, loose_normal.jpg를 정해진 지점에 연결)")
    p.add_argument("--split", action="store_true",
                   help="기능별 결과 파일(카메라 단차·경사·균열, 발)로도 나눠 <출력>/raw/에 저장")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("map", help="HTML 대시보드 생성")
    p.add_argument("events", help="측정 지점 파일 (events.csv / all.csv)")
    p.add_argument("trajectory", help="이동 궤적 파일 (trajectory.csv)")
    p.add_argument("-o", "--output", default="dashboard.html", help="출력 HTML (기본: dashboard.html)")
    p.add_argument("-c", "--config", default="config.yaml",
                   help="판정 기준·세션 정보(report.area, robot.name)를 읽을 설정 파일 (기본: config.yaml)")
    p.add_argument("--traces", metavar="CSV",
                   help="흔들림 지점 발끝 기록 (기본: events.csv와 같은 폴더의 foot_traces.csv, 없으면 그래프 대신 안내)")
    p.add_argument("--blocks", metavar="CSV",
                   help="밟은 블록 요약 (기본: events.csv와 같은 폴더의 blocks.csv, 없으면 밟은 블록 수는 발끝 기록 기준)")
    p.add_argument("--history", metavar="DIR",
                   help="지난 점검 폴더 (기본: events.csv와 같은 폴더의 history/, 날짜별 하위 폴더에 events.csv·trajectory.csv)")
    p.set_defaults(func=cmd_map)

    p = sub.add_parser("report", help="자동 신고서 생성 (A4 인쇄용 HTML + 데이터 제공용 CSV)")
    p.add_argument("events", help="측정 지점 파일 (events.csv)")
    p.add_argument("trajectory", help="이동 궤적 파일 (trajectory.csv)")
    p.add_argument("-o", "--output", default="outputs/report.html",
                   help="출력 HTML (기본: outputs/report.html). CSV는 같은 이름 .csv로 함께 저장")
    p.add_argument("-c", "--config", default="config.yaml",
                   help="판정 기준·구간 이름(report.area)을 읽을 설정 파일 (기본: config.yaml)")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("merge", help="기능별 결과 CSV 합치기 (단차 교차 측정 묶기, 균열·경사 중복 제거)")
    p.add_argument("inputs", nargs="+", help="기능별 결과 CSV들 (와일드카드 가능, 예: data/raw/*.csv)")
    p.add_argument("-o", "--output", default="events.csv", help="출력 CSV (기본: events.csv)")
    p.add_argument("-c", "--config", default="config.yaml",
                   help="판정 기준·merge 거리/시간을 읽을 설정 파일 (기본: config.yaml, 없으면 기본값)")
    p.set_defaults(func=cmd_merge)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
