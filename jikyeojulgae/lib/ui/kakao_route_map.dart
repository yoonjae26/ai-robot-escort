import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:kakao_map_sdk/kakao_map_sdk.dart';

import 'scene.dart';

const kakaoNativeAppKey = String.fromEnvironment('KAKAO_NATIVE_APP_KEY');
const kakaoJavaScriptAppKey = String.fromEnvironment(
  'KAKAO_JAVASCRIPT_APP_KEY',
);

String get kakaoMapAppKey => kIsWeb ? kakaoJavaScriptAppKey : kakaoNativeAppKey;

bool get isKakaoMapConfigured => kakaoMapAppKey.isNotEmpty;
bool kakaoMapInitialized = false;

/// Kakao map centered on the service area. Route coordinates are generated
/// from the same path used by the animated Flutter marker.
class KakaoRouteMap extends StatefulWidget {
  const KakaoRouteMap({super.key, required this.onUnavailable});

  final VoidCallback onUnavailable;

  @override
  State<KakaoRouteMap> createState() => _KakaoRouteMapState();
}

class _KakaoRouteMapState extends State<KakaoRouteMap> {
  static const _center = LatLng(33.4771278, 126.4753953);
  bool _routeAdded = false;

  LatLng _coordinateForScreenPoint(Offset point) => LatLng(
    _center.latitude + (140 - point.dy) * .0000045,
    _center.longitude + (point.dx - 180) * .0000054,
  );

  Future<void> _configure(KakaoMapController controller) async {
    if (_routeAdded) return;
    _routeAdded = true;
    final points = List.generate(
      25,
      (index) => _coordinateForScreenPoint(routePosition(index / 24)),
    );
    await controller.routeLayer.addRoute(
      points,
      RouteStyle(
        const Color(0xFF18CDB5),
        7,
        strokeColor: const Color(0xFF0B2540).withValues(alpha: .72),
        strokeWidth: 3,
      ),
    );
  }

  @override
  Widget build(BuildContext context) => KakaoMap(
    option: const KakaoMapOption(
      position: _center,
      zoomLevel: 17,
      viewName: 'jikyeojulgae-route-map',
    ),
    forceGesture: true,
    onMapReady: (controller) {
      _configure(controller).catchError((_) => widget.onUnavailable());
    },
    onMapError: (_) => widget.onUnavailable(),
  );
}
