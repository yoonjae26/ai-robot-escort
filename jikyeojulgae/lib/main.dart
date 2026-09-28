import 'package:flutter/material.dart';
import 'package:kakao_map_sdk/kakao_map_sdk.dart';

import 'ui/kakao_route_map.dart';
import 'ui/prototype.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  if (isKakaoMapConfigured) {
    try {
      await KakaoMapSdk.instance.initialize(kakaoMapAppKey);
      kakaoMapInitialized = true;
    } catch (_) {
      kakaoMapInitialized = false;
    }
  }
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: '지켜줄개 · 안심동행',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      brightness: Brightness.dark,
      useMaterial3: true,
      scaffoldBackgroundColor: const Color(0xFF061625),
      fontFamily: 'Malgun Gothic',
      colorScheme: const ColorScheme.dark(
        primary: Color(0xFF18CDB5),
        onPrimary: Color(0xFF082C31),
        secondary: Color(0xFF92AEFF),
        surface: Color(0xFF102A42),
        onSurface: Color(0xFFF4FAFF),
        error: Color(0xFFFF3F58),
      ),
      textTheme: const TextTheme(
        bodyMedium: TextStyle(
          color: Color(0xFFF4FAFF),
          fontSize: 14,
          height: 1.5,
        ),
      ),
      dividerTheme: const DividerThemeData(color: Color(0x26FFFFFF)),
      dialogTheme: const DialogThemeData(
        backgroundColor: Color(0xFF102A42),
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.all(Radius.circular(28)),
        ),
      ),
      bottomSheetTheme: const BottomSheetThemeData(
        backgroundColor: Color(0xFF102A42),
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(32)),
        ),
      ),
      snackBarTheme: const SnackBarThemeData(
        backgroundColor: Color(0xF21A3550),
        contentTextStyle: TextStyle(color: Colors.white),
        behavior: SnackBarBehavior.floating,
        shape: StadiumBorder(),
      ),
    ),
    home: const Prototype(),
  );
}
