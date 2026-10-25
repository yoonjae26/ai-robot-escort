"""VWorld 3D 지도 (map3d.html): 측정 지점·이동 경로·로봇 위치를 VWorld WebGL 3D 지도(API 3.0, Cesium 기반) 위에.

대시보드와 같은 폴더에 만들고, 대시보드의 '3D 지도' 버튼이 화면 위에 띄운다. VWorld 인증키가 있을 때만 만든다
(키는 3D 지도 서비스용으로 발급·등록된 주소에서만 동작). 초기화는 브이월드 공식 예제와 같은 순서
(vw.Map → setOption → start, 준비되면 vw.ws3dInitCallBack, ws3d.viewer = Cesium Viewer).
"""
from __future__ import annotations

import html
import json

from .photos import LEVEL_COLOR

MAP3D_NAME = "map3d.html"
KIND_KO = {"step": "단차", "slope": "경사", "crack": "균열", "loose": "흔들림"}
LEVEL_KO = {"danger": "위험", "warn": "주의", "ok": "정상"}

_TEMPLATE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<script src="https://map.vworld.kr/js/webglMapInit.js.do?version=3.0&apiKey=__KEY__"></script>
<style>
  html, body { margin: 0; height: 100%; background: #1f1c1f; font-family: "Pretendard Variable", "Malgun Gothic", sans-serif; }
  #vmap { position: absolute; inset: 0; }
  .legend { position: absolute; left: 12px; top: 12px; z-index: 10; background: rgba(255,255,255,.94); border-radius: 12px;
            padding: 10px 12px; font-size: 12px; color: #2f2a2f; box-shadow: 0 2px 8px rgba(0,0,0,.2); }
  .legend b { display: block; font-size: 13px; margin-bottom: 6px; }
  .legend span { display: inline-flex; align-items: center; gap: 4px; margin-right: 10px; }
  .legend i { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
  #msg { position: absolute; left: 50%; top: 45%; transform: translate(-50%, -50%); color: #fff; font-size: 14px; z-index: 5; }
</style>
</head>
<body>
<div id="msg">3D 지도를 불러오는 중…</div>
<div id="vmap"></div>
<div class="legend"><b>3D 지도 · 측정 지점 __N__개</b>
  <span><i style="background:__C_DANGER__"></i>위험</span><span><i style="background:__C_WARN__"></i>주의</span>
  <span><i style="background:__C_OK__"></i>정상</span><span><i style="background:#2f2a2f;border:2px solid #fff"></i>로봇</span></div>
<script id="map3d-data" type="application/json">__DATA__</script>
<script>
(function () {
  var D = JSON.parse(document.getElementById("map3d-data").textContent);
  var msg = document.getElementById("msg");
  if (!window.vw) { msg.textContent = "3D 지도를 불러오지 못했습니다 (인터넷 연결 또는 VWorld 키·등록 주소 확인)"; return; }
  // 처음 보이는 곳: 로봇 마지막 위치(없으면 첫 지점)를 남쪽에서 비스듬히 내려다본다
  var c = D.robot || (D.events.length ? [D.events[0].lat, D.events[0].lon] : [37.5665, 126.9780]);
  var map = new vw.Map();
  map.setOption({ mapId: "vmap", logo: true, navigation: true,
                  initPosition: new vw.CameraPosition(new vw.CoordZ(c[1], c[0] - 0.0016, 180), new vw.Direction(0, -40, 0)) });
  map.start();
  vw.ws3dInitCallBack = function () {
    msg.remove();
    var viewer = ws3d.viewer, C = Cesium;
    // 처음 위치: setOption의 initPosition이 무시될 때가 있어 Cesium 카메라로 직접 옮긴다.
    // 그 자리 지형 고도(VWorld 지형) + 250 m에서 40° 내려다봄. 지형을 못 읽으면 D.ground
    function look(h) {
      viewer.camera.setView({ destination: C.Cartesian3.fromDegrees(c[1], c[0] - 0.0022, h + 250),
                              orientation: { heading: 0, pitch: C.Math.toRadians(-40), roll: 0 } });
    }
    look(D.ground);
    try {
      C.sampleTerrainMostDetailed(viewer.terrainProvider, [C.Cartographic.fromDegrees(c[1], c[0])])
        .then(function (r) { if (r && r[0] && isFinite(r[0].height)) look(r[0].height); }, function () {});
    } catch (e) {}
    var GROUND = C.HeightReference.CLAMP_TO_GROUND, NO_DEPTH = Number.POSITIVE_INFINITY;
    if (D.trajectory.length > 1) {
      viewer.entities.add({ polyline: { positions: D.trajectory.map(function (p) { return C.Cartesian3.fromDegrees(p[1], p[0]); }),
                                        width: 4, clampToGround: true, material: C.Color.fromCssColorString("#2f2a2f").withAlpha(0.75) } });
    }
    D.events.forEach(function (e) {
      viewer.entities.add({
        position: C.Cartesian3.fromDegrees(e.lon, e.lat),
        point: { pixelSize: e.level === "ok" ? 10 : 15, color: C.Color.fromCssColorString(e.color), outlineColor: C.Color.WHITE,
                 outlineWidth: 2, heightReference: GROUND, disableDepthTestDistance: NO_DEPTH },
        label: e.level === "ok" ? undefined : { text: e.label, font: "600 13px sans-serif", fillColor: C.Color.WHITE,
                 outlineColor: C.Color.BLACK, outlineWidth: 3, style: C.LabelStyle.FILL_AND_OUTLINE, heightReference: GROUND,
                 verticalOrigin: C.VerticalOrigin.BOTTOM, pixelOffset: new C.Cartesian2(0, -14), disableDepthTestDistance: NO_DEPTH },
        description: e.desc,
      });
    });
    if (D.robot) {
      viewer.entities.add({ position: C.Cartesian3.fromDegrees(D.robot[1], D.robot[0]),
        point: { pixelSize: 16, color: C.Color.fromCssColorString("#2f2a2f"), outlineColor: C.Color.WHITE, outlineWidth: 3,
                 heightReference: GROUND, disableDepthTestDistance: NO_DEPTH },
        label: { text: "로봇", font: "600 12px sans-serif", fillColor: C.Color.WHITE, outlineColor: C.Color.BLACK, outlineWidth: 3,
                 style: C.LabelStyle.FILL_AND_OUTLINE, heightReference: GROUND, verticalOrigin: C.VerticalOrigin.BOTTOM,
                 pixelOffset: new C.Cartesian2(0, -14), disableDepthTestDistance: NO_DEPTH } });
    }
  };
})();
</script>
</body>
</html>
"""


def _num(v) -> str:
    s = f"{v:.1f}".rstrip("0").rstrip(".")
    return s or "0"


def build_map3d_html(events: list[dict], traj: list[dict], key: str, title: str = "StepMap 3D 지도") -> str:
    """events·traj: events.csv·trajectory.csv 행 (lat·lon 있음)."""
    ev = []
    for e in events:
        kind = KIND_KO.get(e["kind"], e["kind"])
        label = f"{kind} {_num(e['value'])}{e['unit'] if e['unit'] != 'deg' else '°'}"
        ev.append({"lat": e["lat"], "lon": e["lon"], "level": e["level"], "color": LEVEL_COLOR.get(e["level"], "#888"),
                   "label": label,
                   "desc": html.escape(f"{e['id']} · {LEVEL_KO.get(e['level'], e['level'])} · {label} · {e.get('note') or ''}")})
    data = {"ground": 100.0,             # 지형 고도를 못 읽을 때 쓰는 카메라 기준 높이 [m]
            "events": ev, "trajectory": [[round(p["lat"], 7), round(p["lon"], 7)] for p in traj],
            "robot": [traj[-1]["lat"], traj[-1]["lon"]] if traj else None}
    return (_TEMPLATE.replace("__TITLE__", html.escape(title))
            .replace("__KEY__", html.escape(key, quote=True))
            .replace("__N__", str(len(events)))
            .replace("__C_DANGER__", LEVEL_COLOR["danger"]).replace("__C_WARN__", LEVEL_COLOR["warn"])
            .replace("__C_OK__", LEVEL_COLOR["ok"])
            .replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")))
