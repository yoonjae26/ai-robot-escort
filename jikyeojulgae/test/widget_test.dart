import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jikyeojulgae/main.dart';

void main() {
  testWidgets('Journey: verification, pause, help, arrival and review', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(430, 1100);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(const MyApp());
    Future<void> tap(String text) async {
      final finder = find.text(text);
      await tester.ensureVisible(finder);
      await tester.tap(finder);
      await tester.pumpAndSettle();
    }

    await tap('안심 동행 요청하기');
    await tap('이 경로로 동행 요청');
    expect(
      tester
          .widget<FilledButton>(
            find.widgetWithText(FilledButton, '지켜줄개와 동행 시작'),
          )
          .onPressed,
      isNull,
    );
    await tester.pump(const Duration(milliseconds: 900));
    expect(find.text('카메라로 지켜줄개를 인식하고 있어요'), findsOneWidget);
    await tester.pump(const Duration(milliseconds: 1500));
    await tester.pumpAndSettle();
    expect(find.text('동행자 확인 완료'), findsOneWidget);
    final startButton = find.text('지켜줄개와 동행 시작');
    await tester.ensureVisible(startButton);
    await tester.tap(startButton);
    await tester.pump();
    final marker = find.bySemanticsLabel('사람과 지켜줄개의 현재 위치');
    final firstPosition = tester.getTopLeft(marker);
    await tester.pump(const Duration(seconds: 2));
    expect(tester.getTopLeft(marker), isNot(firstPosition));
    await tap('잠시 멈추기');
    expect(find.text('잠시 쉬어 가요'), findsOneWidget);
    final resumeButton = find.text('다시 출발');
    await tester.tap(resumeButton);
    await tester.pump();
    await tap('긴급 도움 요청');
    expect(find.text('도움 요청을 보냈어요'), findsOneWidget);
    final returnButton = find.text('요청 취소 · 동행으로 돌아가기');
    await tester.ensureVisible(returnButton);
    await tester.tap(returnButton);
    await tester.pump();
    await tap('목적지에 도착했어요 →');
    await tap('만족해요');
    expect(find.text('소중한 의견 고마워요!'), findsOneWidget);
    await tap('이용 내역 보기');
    expect(find.text('최근 동행'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets('Small screen: location selection and navigation', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(const MyApp());
    await tester.ensureVisible(find.text('중앙공원 정문'));
    await tester.tap(find.text('중앙공원 정문'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('도서관 입구'));
    await tester.pumpAndSettle();
    expect(find.text('도서관 입구'), findsOneWidget);
    await tester.tap(find.text('내 정보'));
    await tester.pumpAndSettle();
    expect(find.text('지켜줄개 이용자'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('Wide screen: app is presented inside a phone frame', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 960);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(const MyApp());

    final frame = find.byKey(const ValueKey('phone-frame'));
    expect(frame, findsOneWidget);
    expect(tester.getSize(frame), const Size(446, 900));
    expect(tester.takeException(), isNull);
  });
}
