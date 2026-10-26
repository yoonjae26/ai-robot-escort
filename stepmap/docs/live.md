# StepMap live: 로봇 측정 결과를 실시간으로 대시보드에

Phase A의 `merge` → `map` → `report` 흐름을 그대로 쓰되, 측정 결과가 들어오는 즉시 합쳐서 대시보드를 갱신한다.
대시보드는 로봇(현장)과 노트북(팀) 두 곳에서 같은 내용으로 볼 수 있고, 네트워크가 끊겨도 데이터가 사라지지 않는다.

## 구성

```
로봇 (Jetson, ROS 2 Foxy, Python 3.8)
  terrain_geometry_node.py ─┐ 경사, 카메라 단차 (/terrain_geometry/slope)
  inspect_node.py ──────────┤ 블록 함몰·돌출·구멍 + 사진 (logs/inspect/<세션>/state.json)
  /utlidar/robot_odom ──────┤ 이동 궤적, 측정 위치 계산
  auto_recorder 상태 ───────┤ 배터리
                            ▼
  robot/stepmap_bridge.py   events.csv 형식으로 바꿔 outbox.jsonl에 먼저 저장(fsync) → 순서대로 전송
                            ▼  POST /api/ingest, /api/file
  stepmap live (포트 8060)  stream.jsonl에 순번과 함께 저장 → merge_events → events.csv·trajectory.csv
                            → 측정 지점이 바뀌면 live/dashboard.html 갱신 (궤적만 늘면 30초마다)
                            ▲  GET /api/since?seq=마지막&now=노트북시각 (1초마다)
노트북  stepmap live --pull http://<로봇>:8060   같은 stream을 복제, 사진도 받아 같은 대시보드
```

- 대시보드 왼쪽 아래 배지: `● 실시간 · 측정 지점 N개 (위험 · 주의) · 배터리` (2초마다 확인, 새 측정이 있으면 새로고침,
  연결이 끊기면 `● 연결 끊김 · 마지막 수신 시각`).
- **끊김에 강함**: bridge는 보내기 전에 디스크에 쓰고(`outbox.jsonl`, `sent.txt`), 서버는 받은 즉시 디스크에
  쓰고(`stream.jsonl`), 노트북은 마지막으로 받은 순번 다음부터 다시 받는다. 어느 쪽이 꺼졌다 켜져도 이어진다.
- **결과는 오프라인과 같다**: CSV는 `stepmap merge`와 같은 함수로 만든다. 같은 입력이면 `events.csv`가
  바이트 단위로 같다 (`tests/test_live.py`).
- **로봇 시계**: Jetson은 RTC 배터리가 없어 인터넷이 없으면 1970년부터 센다. 노트북이 처음 연결될 때 노트북
  시각으로 보정값을 정하고, 로봇과 노트북 모두 보정한 시각을 CSV에 쓴다.

## 실행

로봇 (센서와 측정 노드는 따로 켠다):
```bash
ros2 launch ~/terrain_dataset/sensors.launch.py                  # 창 1
python3 ~/terrain_dataset/terrain_geometry_node.py               # 창 2 (경사·단차)
~/terrain_dataset/inspect.sh -p location:="제주시 연동 ..."      # 창 3 (블록 함몰·돌출, 선택)
~/terrain_dataset/stepmap_live.sh 20261026_yeondong_A            # 창 4: live 서버 + bridge
```
로봇 대시보드: `http://<로봇 주소>:8060/` (같은 공유기 또는 Tailscale `http://100.65.117.65:8060/`)

노트북:
```bash
pip install -e ".[test]"
stepmap live -d sessions/20261026_yeondong_A --pull http://192.168.123.18:8060 --port 8060
```
노트북 대시보드: `http://localhost:8060/`. 신고서: `http://localhost:8060/report` (geo 필요).

케이블 없이 받으려면 `--pull`에 주소를 여러 개 준다 (끊기면 다음 주소로 자동 전환). 경로와 시험 방법: [network.md](network.md).

## 실제 위치 (GPS 보정)

Go2에는 GPS가 없다. 로봇과 함께 다니는 **휴대폰(또는 노트북)의 GPS**로 지도 위치를 맞춘다.

1. 대시보드 오른쪽 위 **`위치 미확인 · 내 위치로 보정`**을 누르고 위치 권한을 허용한다.
2. 브라우저가 2초마다 기기 위치를 `POST /api/gps`로 보내고, 로봇 서버가 그 순간의 odom 위치와 짝지어
   `stream.jsonl`에 저장한다 (`gps` 항목, 노트북 복제본은 받은 위치를 로봇으로 넘기고 pull로 다시 받는다).
3. 짝이 하나면 **로봇 위치**만 맞춘다 (`GPS 위치 · 방향 확인 중`). 로봇이 5 m 이상 움직이면 **방향(방위각)**까지
   최소제곱으로 맞춘다 (`gps.py`). 정확도 50 m보다 나쁜 위치는 버리고, 크게 튄 위치는 뺀다.
4. 위치가 2 m 이상 바뀔 때만 대시보드를 다시 그린다. 로봇 마커는 2초마다 다시 그리지 않고 옮긴다.

- 브라우저는 **https 또는 localhost**에서만 위치를 알려 준다. 노트북은 `http://localhost:8061/`이면 되고,
  휴대폰은 로봇의 `https://<로봇 주소>:8443/`로 연다 (자체 서명 인증서, 처음 한 번 "고급 → 계속").
  http 주소에서 버튼을 누르면 https 주소로 자동으로 옮긴다.
- 휴대폰은 로봇 가까이(1~2 m) 들고 다닌다. 결과 위치 오차는 GPS 오차 수준(수 m)이다.
- `config.yaml geo`나 `--geo`가 있으면 그 값을 그대로 쓴다 (GPS 보정보다 먼저).

## 측정 항목 대응

| 측정 노드 | StepMap kind | value | 위치 | 비고 |
|---|---|---|---|---|
| terrain_geometry_node 경사 | `slope` | 종단 경사 절댓값 [°] | 로봇 + 관심영역 가운데 | `slope_every_m`(2 m)마다 OK 추정값 중앙값. 횡단 경사는 note에 |
| terrain_geometry_node 단차 (3회 연속 확인) | `step` (`camera`) | \|dz\| [cm] | 로봇 + 단차까지 거리 | 같은 0.5 m 칸이면 더 가까이서 본 값으로 갱신 |
| inspect_node 함몰·돌출·구멍 | `step` (`camera`) | \|높이\| [cm] | 블록 위치 | 사진 `img/<세션>_E<n>.jpg` |
| inspect_node + 손상 AI 파손 | `step` (`camera`) | \|높이\| [cm] | 손상 영역 | SegFormer(서피스마스킹 학습) 손상 영역 중 깊이로 10mm 이상 꺼지거나 솟은 곳 |
| inspect_node + 손상 AI 균열 | `crack` (`camera`) | AI 점수 (0~1) | 손상 영역 | 손상 영역인데 평평한 곳 |
| surface_seg_node 요철 | `uneven` (`camera`) | 바닥 높이 편차 [mm] | 앞 0.8m | 앞 0.4~1.2m 바닥 높이의 95%−5%, 10mm 이상이 3회 이상 |
| foot_node (발 접촉) | `loose` (`foot`) | 추가 침하 [mm] | 접지한 발 위치 | 블록(0.3m)마다 다른 발 2개 이상이 기준 이상 침하. `foot_traces`, 이전 사진에 `image_mark` |

## 팀 결정이 필요한 것

- **요철 기준**: `uneven` 10mm / 20mm는 임시값이다 (휠체어 회피 기준 2cm에 맞춤). 실제 보도 주행으로 조정해야 한다.
- **횡단 경사**: 법정 기준(권장 ≤2 %, 위험 >4 %)은 종단 경사와 다르다. 지금은 `slope` 하나만 있어 횡단 값은 note에만
  있다. `cross_slope` 종류를 추가할지 정해야 한다.
- **경사 기준값**: `config.yaml`(4.76° / 7.13°)과 hazard_criteria.yaml(5.56 % = 3.18° / 8.33 % = 4.76°)이 다르다.
- **geo**: GPS 보정을 쓰지 않을 때는 출발점 위도·경도·방위각을 `config.yaml`에 넣는다 (둘 다 없으면 기준점 대비 상대 위치).
