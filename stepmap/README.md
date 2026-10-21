# StepMap

사족보행 로봇(Unitree Go2 EDU)으로 보도의 단차·경사·균열·흔들리는 블럭을 측정하고, 결과를 위치별 지도와 신고서로 보여주는 CLI 도구.
자세한 설계는 [StepMap_계획서.md](StepMap_계획서.md) 참고.

> **현재 단계: Phase A (디자인) 완료.** `data/`의 측정 지점은 제주시 노형동·연동 실제 보도 경로 위에 만든 **디자인용 데이터**이며 실측값이 아니다.
> 실측(Phase B) 준비 항목은 [docs/phase_b_checklist.md](docs/phase_b_checklist.md).

## 1. 설치

Python 3.10 이상. 저장소 폴더에서:

```bash
pip install -e ".[test]"
stepmap --help
```

의존성: `pyyaml`, `pillow` (테스트: `pytest`). 대시보드를 열 브라우저(크롬 권장)가 필요하다.

## 2. 실행 (4단계)

저장소 폴더에서 순서대로 실행한다. 설정은 현재 폴더의 `config.yaml`을 읽는다 (`-c`로 바꿀 수 있음).

```bash
# 1) 데이터 만들기: 궤적·측정 지점·흔들림 발끝 기록 + 기능별 결과 파일(data/raw/) + 현장 사진 연결
stepmap demo -o data/ --split --photos data/photos

# 2) 기능별 결과 합치기 → data/events.csv (1)의 events.csv와 같은 내용이 나와야 한다)
stepmap merge "data/raw/*.csv" -o data/events.csv

# 3) 신고서 (HTML + CSV)
stepmap report data/events.csv data/trajectory.csv

# 4) 대시보드 (같은 폴더의 report.html이 있으면 점검 이력에 "신고서 열기" 버튼을 넣는다)
stepmap map data/events.csv data/trajectory.csv -o outputs/dashboard.html
```

신고서를 대시보드보다 나중에 만들었다면 `map`을 한 번 더 실행한다 (`report`가 알려 준다). 파일로 연 HTML은 옆 파일이 있는지 브라우저가 확인할 수 없어서, `map`이 만들 때 확인한다.

와일드카드(`data/raw/*.csv`)는 따옴표로 감싸서 넘긴다. PowerShell도 그대로 동작한다 (명령이 직접 펼친다).

## 3. 결과 파일 열기

| 파일 | 여는 법 | 내용 |
|---|---|---|
| `outputs/dashboard.html` | 브라우저로 직접 열기 (더블클릭, Windows `start outputs\dashboard.html`) | 아래 "대시보드" 참고 |
| `outputs/report.html` | 브라우저로 열고 인쇄(A4) | 요약, 위치 확인용 경로 그림, 위험·주의 지점 목록 |
| `outputs/report.csv` | 엑셀 등 | 신고서 목록과 같은 지점·순서·번호 (지자체 데이터 제공용, 위험·주의만) |
| `data/events.csv` | 엑셀 등 | 전체 측정 지점 (정상 포함). 전체 지점은 events.csv를 쓴다 |
| `outputs/screens/` | 이미지 뷰어 | 발표용 화면 21장 (2배율): 종합 현황 선택 없음·흔들림 ev_0014 선택·단차 ev_0012 선택 (각각 1440·1920·1280 폭), 외관 검사(ev_0012), 물리적 안정성(ev_0014 그래프), 점검 이력(1440), 점검 이력 최근 날짜·2026-09-15 (각각 1920·1280 폭), 모바일, 라이트, 인터넷 없을 때, 신고서 1·2쪽 |

현재 디자인 데이터: 측정 지점 40개 (위험 4 · 주의 5 · 정상 31), 이동 거리 912m, 신고서 A4 4쪽 (신고 대상 9건), 사진 연결 3곳.

웹 서버 없이 파일을 직접 열어도 된다. 인터넷이 없으면 대시보드는 지도 배경 대신 odom (x, y) 평면 지도로 자동 전환되고 글꼴은 시스템 한글 글꼴을 쓴다. 신고서는 외부 자원을 쓰지 않는다.

### 대시보드

왼쪽 사이드바로 4페이지를 오간다. 주소 해시(`#visual/ev_0012` 등)로 페이지·지점이 유지되고 뒤로 가기가 동작한다. 네이비 테마, 다크 기본(사이드바 아래 버튼으로 라이트 전환, 브라우저에 기억). 자세한 화면 규칙은 계획서 8장.

| 페이지 | 내용 |
|---|---|
| 종합 현황 | KPI 4개(점검 거리·외관 이상·흔들림 의심·정상 지점), 지도(경로 양 끝 출발·도착, 판정 색 + 종류 모양 마커, 오른쪽 위 **밝은 지도 / 어두운 지도** 전환), 범례, 위험·주의 지점 목록. 데스크톱은 스크롤 없이 한 화면. 마커·목록을 누르면 흔들림은 물리적 안정성, 나머지는 외관 검사로 이동. 최대 확대에서도 묶인 마커는 누르면 부채꼴로 펼침 |
| 외관 검사 | 흔들림을 뺀 지점 목록(탭: 전체·단차·경사·균열, 정상 포함 선택) + 상세(사진, 값, 기준과 배수, 교차 측정 카드, 측정 근거, 지도에서 위치 보기) |
| 물리적 안정성 검사 | 흔들림 지점 목록 + 상세(사진 위 발 접촉 위치, 발끝 높이 그래프와 추가 침하, 측정 근거, 1m 안 외관 이상 비교) |
| 점검 이력 | 필터(세션·종류·판정·측정 방식), 요약 카드 5개, 종류별 판정 누적 막대, 점검 세션 표, 지점 목록 표(열 머리 정렬, 행 클릭 이동, 모바일은 카드형). **CSV 다운로드**: 현재 필터 결과를 events.csv와 같은 열로 (BOM, 필터가 없으면 events.csv와 같은 파일). **신고서 열기**: 같은 폴더의 report.html (인쇄 → PDF로 저장 가능) |

## 4. 테스트

```bash
pytest
```

## 5. 명령별 입력·출력

| 명령 | 입력 | 출력 |
|---|---|---|
| `stepmap demo -o DIR [--split] [--photos PHOTOS]` | `config.yaml` (판정 기준), `PHOTOS/` 사진 | `DIR/trajectory.csv`, `DIR/events.csv`, `DIR/foot_traces.csv` (흔들림 발끝 기록), `DIR/history/<YYYY-MM-DD>/events.csv`·`trajectory.csv` (지난 점검 4회: 09-15, 09-29, 10-06, 10-13), `--split`: `DIR/raw/camera_step.csv`, `camera_slope.csv`, `camera_crack.csv`, `foot.csv` |
| `stepmap merge 입력들 -o OUT` | 기능별 결과 CSV (id·level 빈칸 가능), 발끝 기록 CSV (id 빈칸, `t_event`로 연결, 머리줄로 자동 구분), `config.yaml` (`thresholds`, `merge`, `geo`) | `OUT` (events.csv 형식), 발끝 기록이 있으면 `OUT 폴더/foot_traces.csv` (흔들림 지점 시각·다리로 id 연결, 짝 없는 기록은 경고) |
| `stepmap map EVENTS TRAJ -o OUT [--traces CSV] [--history DIR]` | events.csv, trajectory.csv (가장 최근 점검), 발끝 기록 (기본: events.csv와 같은 폴더의 `foot_traces.csv`, 없으면 그래프 대신 안내), 지난 점검 (기본: events.csv와 같은 폴더의 `history/<YYYY-MM-DD>/`, 점검 이력 페이지만 사용), `config.yaml` (`thresholds`, `report.area`, `robot.name`) | `OUT` (HTML 1개), `OUT 폴더/photos/` 사진 사본 |
| `stepmap report EVENTS TRAJ [-o OUT]` | events.csv, trajectory.csv, `config.yaml` (`thresholds`, `report.area`) | `outputs/report.html`, 같은 이름의 `.csv`, `photos/` 사진 사본 |

`events.csv`·`trajectory.csv`·`foot_traces.csv` 형식은 계획서 6장(발끝 기록과 추가 침하 계산은 6.4), 병합 규칙은 9.3, 신고서 구성은 8.3.

## 6. `config.yaml`

| 항목 | 설명 | 지금 값 |
|---|---|---|
| `thresholds` | 판정 기준 (warn·danger). 단차 cm, 경사 °, 균열 점수, 흔들림 mm. `demo`·`merge`가 판정할 때, `map`·`report`가 기준 문구를 쓸 때 사용 | 단차 1.0/2.0, 경사 4.76/7.13, 균열 0.5/0.8, 흔들림 3.0/6.0 (흔들림은 임시값) |
| `merge` | 카메라 단차↔발 단차를 한 건으로 합치는 거리·시간 (`step_radius_m`, `step_window_s`), 균열·경사 중복 제거 거리·시간 (`dedup_radius_m`, `dedup_window_s`). 거리는 경계 포함 | 1.0m, 10초 |
| `geo` | odom → 위도·경도 변환. 출발점 위도·경도와 odom x축 방위각(북=0, 동=90). `merge`가 비어 있는 lat/lon을 채울 때 사용 | `<...>` 자리표시자 (Phase B에서 채움. 디자인 데이터는 자체 기준점을 씀) |
| `report.area` | 신고서 요약·대시보드 측정 세션의 '구간' | 제주시 노형동·연동 |
| `robot.name` | 대시보드 측정 세션의 '로봇' | Unitree Go2 EDU |
| `topics`, `frames`, `calib`, `robot` | 실측(Phase B)용 토픽·좌표계·보정값·다리 치수 | 토픽·frame_id는 `<...>` |

## 7. 폴더 구조

```
stepmap/
├── README.md, StepMap_계획서.md, config.yaml, pyproject.toml
├── stepmap/
│   ├── cli.py         # 명령 (demo, merge, map, report)
│   ├── events.py      # 공통 형식·형식 검사, 판정·기준 문구, 좌표 변환, 이동 거리, 병합
│   ├── demo.py        # 디자인 데이터 (노형동·연동 경로), 기능별 분할, 사진 연결
│   ├── dashboard.py   # HTML 대시보드
│   ├── report.py      # 신고서 HTML·CSV
│   └── photos.py      # 사진 사본, 사진 위 위치 표시 (대시보드·신고서 공통)
├── tests/
├── data/
│   ├── photos/        # 현장 사진 원본 (수정하지 않음)
│   ├── raw/           # 기능별 결과 (merge 입력, 발끝 기록 포함)
│   ├── history/       # 지난 점검 (날짜별 events.csv, trajectory.csv)
│   ├── events.csv, trajectory.csv, foot_traces.csv
├── outputs/
│   ├── dashboard.html, report.html, report.csv
│   ├── photos/        # 사진 사본 (생성물, git 제외)
│   └── screens/       # 발표용 화면 (git 포함)
└── docs/phase_b_checklist.md
```

## 8. 외부 주소와 지도 출처

대시보드만 아래 주소를 쓴다 (신고서는 외부 자원 없음). 라이브러리·글꼴은 버전을 고정하고 SRI로 내용을 확인한다. 하나라도 못 받으면 대체 동작으로 계속 보인다.

| 주소 | 용도 | 못 받으면 |
|---|---|---|
| `https://unpkg.com/leaflet@1.9.4/dist/leaflet.css`, `leaflet.js` | 지도 라이브러리 (SRI) | odom 평면 지도 |
| `https://{a,b,c}.tile.opentopomap.org/{z}/{x}/{y}.png` | 배경 지도 타일 | odom 평면 지도 |
| `https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css` (+ 같은 곳의 글꼴 파일) | 글꼴 Pretendard (SRI, SIL OFL 1.1) | 시스템 한글 글꼴 |


대시보드 배경은 [OpenTopoMap](https://opentopomap.org) 타일을 회색조로 표시한다 (판정 색과 섞이지 않게). 밝은 지도는 옅은 회청색, 어두운 지도는 반전 네이비 톤.
화면 오른쪽 아래에 **© OpenStreetMap contributors, SRTM | © OpenTopoMap (CC-BY-SA)** 를 항상 표기한다. 발표 화면에서도 이 표기가 보이게 둔다.
디자인 데이터의 보도 경로는 OpenStreetMap 도로 중심선(© OpenStreetMap contributors, ODbL)에서 만들었다.
OSM 공식 타일 서버(Referer 없는 요청 거부)와 CARTO basemap(키 없는 요청에 워터마크)은 HTML을 파일로 직접 여는 이 용도에 쓸 수 없다.

## 9. 사진 규칙

- `events.csv`의 `image`는 **events.csv 기준 상대 경로** (예: `photos/step_curb_gap.jpg`).
- `stepmap map`·`report`가 원본을 찾아 **짧은 변 720px 이하 사본**을 HTML 옆 `photos/`에 만들고 HTML 기준 상대 경로로 연결한다. 원본은 바꾸지 않는다. 사본에는 EXIF(촬영 위치 등)를 넣지 않는다.
- 원본이 없으면 그 지점은 사진 영역을 만들지 않는다.
- `image_mark` (`u,v,r`, 0~1 비율)는 **흔들림 지점의 발 접촉 위치 표시용**이다. 흔들림 사진 위에만 점선 동그라미 + "발 접촉 위치 (추정)"를 겹쳐 그리고, 사진 아래에 "외관 정상, 발 접촉으로 확인"을 자동으로 붙인다. 단차·균열은 문제가 사진에 보이므로 동그라미 없이 사진만 보여 준다.
