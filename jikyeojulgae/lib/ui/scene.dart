import 'dart:math' as math;

import 'package:flutter/material.dart';

const _mint = Color(0xFF18CDB5);

Path _routePath() => Path()
  ..moveTo(78, 200)
  ..lineTo(106, 143)
  ..quadraticBezierTo(112, 130, 127, 137)
  ..lineTo(230, 167)
  ..quadraticBezierTo(244, 172, 250, 156)
  ..lineTo(290, 61);

Offset routePosition(double progress) {
  final metric = _routePath().computeMetrics().first;
  return metric
      .getTangentForOffset(metric.length * progress.clamp(0.0, 1.0))!
      .position;
}

/// Detailed local map artwork used until live map tiles are connected.
class RoutePainter extends CustomPainter {
  const RoutePainter({this.active = false, this.progress = 0});
  final bool active;
  final double progress;
  @override
  void paint(Canvas canvas, Size size) {
    canvas.save();
    canvas.scale(size.width / 360, size.height / 280);
    canvas.drawRect(
      const Rect.fromLTWH(0, 0, 360, 280),
      Paint()
        ..shader = const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xFF28495C), Color(0xFF172E40)],
        ).createShader(const Rect.fromLTWH(0, 0, 360, 280)),
    );

    // Park and residential land parcels.
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        const Rect.fromLTWH(132, 82, 100, 79),
        const Radius.circular(18),
      ),
      Paint()..color = const Color(0xFF285B52),
    );
    canvas.drawPath(
      Path()
        ..moveTo(0, 16)
        ..lineTo(72, 0)
        ..lineTo(95, 52)
        ..lineTo(17, 70)
        ..close(),
      Paint()..color = const Color(0xFF29485A),
    );
    canvas.drawPath(
      Path()
        ..moveTo(270, 190)
        ..lineTo(360, 166)
        ..lineTo(360, 280)
        ..lineTo(305, 280)
        ..close(),
      Paint()..color = const Color(0xFF244456),
    );

    final boulevard = Path()
      ..moveTo(-20, 239)
      ..cubicTo(76, 216, 165, 221, 380, 176);
    _drawRoad(canvas, boulevard, 30, 22);
    final northRoad = Path()
      ..moveTo(40, 300)
      ..cubicTo(68, 221, 89, 164, 112, 102)
      ..cubicTo(128, 59, 141, 22, 153, -20);
    _drawRoad(canvas, northRoad, 22, 15);
    final diagonalRoad = Path()
      ..moveTo(205, 300)
      ..cubicTo(221, 221, 253, 145, 326, -15);
    _drawRoad(canvas, diagonalRoad, 19, 13);
    final eastRoad = Path()
      ..moveTo(88, 76)
      ..cubicTo(170, 58, 249, 54, 380, 81);
    _drawRoad(canvas, eastRoad, 14, 9);

    for (final alley in [
      Path()
        ..moveTo(-10, 127)
        ..lineTo(105, 145)
        ..lineTo(177, 183),
      Path()
        ..moveTo(170, -10)
        ..lineTo(193, 83)
        ..lineTo(256, 112),
      Path()
        ..moveTo(276, 111)
        ..lineTo(360, 130),
      Path()
        ..moveTo(19, 184)
        ..lineTo(92, 176),
    ]) {
      _drawRoad(canvas, alley, 8, 5);
    }

    // Buildings use varied footprints to resemble a real neighborhood.
    for (final building in <Rect>[
      const Rect.fromLTWH(13, 77, 35, 27),
      const Rect.fromLTWH(55, 70, 31, 39),
      const Rect.fromLTWH(15, 139, 52, 28),
      const Rect.fromLTWH(25, 250, 45, 23),
      const Rect.fromLTWH(86, 232, 37, 35),
      const Rect.fromLTWH(127, 237, 58, 28),
      const Rect.fromLTWH(178, 194, 34, 28),
      const Rect.fromLTWH(228, 207, 49, 31),
      const Rect.fromLTWH(291, 189, 47, 34),
      const Rect.fromLTWH(270, 91, 38, 29),
      const Rect.fromLTWH(312, 100, 39, 31),
      const Rect.fromLTWH(218, 18, 43, 27),
      const Rect.fromLTWH(276, 24, 54, 31),
    ]) {
      _drawBuilding(canvas, building);
    }

    // Park paths, trees and small map details.
    final parkPath = Paint()
      ..color = const Color(0xFF769083)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.2
      ..strokeCap = StrokeCap.round;
    canvas.drawOval(const Rect.fromLTWH(147, 96, 70, 46), parkPath);
    canvas.drawLine(const Offset(144, 145), const Offset(217, 93), parkPath);
    for (final point in [
      const Offset(143, 99),
      const Offset(162, 91),
      const Offset(184, 102),
      const Offset(211, 91),
      const Offset(221, 126),
      const Offset(152, 141),
      const Offset(196, 147),
      const Offset(345, 237),
    ]) {
      canvas.drawLine(
        point,
        point + const Offset(0, 7),
        Paint()
          ..color = const Color(0xFF668A7D)
          ..strokeWidth = 2,
      );
      canvas.drawCircle(point, 5.5, Paint()..color = const Color(0xFF3C7969));
    }
    _drawCrosswalk(canvas, const Offset(88, 220), -.16);
    _drawCrosswalk(canvas, const Offset(248, 181), -.28);
    _drawMapLabel(canvas, '중앙공원', const Offset(174, 119), emphasized: true);
    _drawMapLabel(canvas, '중앙로', const Offset(135, 215), angle: -.12);
    _drawMapLabel(canvas, '은행나무길', const Offset(275, 61), angle: .12);
    _drawMapLabel(canvas, '주민센터', const Offset(300, 111));
    _drawMapLabel(canvas, '편의점', const Offset(235, 26));
    final path = _routePath();
    final stroke = Paint()
      ..color = _mint
      ..strokeWidth = 4
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round;
    for (final metric in path.computeMetrics()) {
      for (double d = 0; d < metric.length; d += 12) {
        canvas.drawPath(metric.extractPath(d, d + 5), stroke);
      }
    }
    final current = active ? routePosition(progress) : const Offset(78, 200);
    if (active) {
      _paintActiveHalo(canvas, current);
    } else {
      canvas.drawCircle(
        current,
        27,
        Paint()..color = _mint.withValues(alpha: .12),
      );
      canvas.drawCircle(
        current,
        17,
        Paint()..color = _mint.withValues(alpha: .2),
      );
      canvas.drawCircle(current, 9, Paint()..color = _mint);
      canvas.drawCircle(current, 4, Paint()..color = const Color(0xFF0A2732));
    }
    canvas.drawCircle(
      const Offset(290, 61),
      19,
      Paint()..color = const Color(0xFF102839),
    );
    final house = Path()
      ..moveTo(277, 60)
      ..lineTo(290, 49)
      ..lineTo(303, 60)
      ..lineTo(300, 60)
      ..lineTo(300, 72)
      ..lineTo(293, 72)
      ..lineTo(293, 64)
      ..lineTo(287, 64)
      ..lineTo(287, 72)
      ..lineTo(280, 72)
      ..lineTo(280, 60)
      ..close();
    canvas.drawPath(house, Paint()..color = Colors.white);
    canvas.restore();
  }

  void _drawRoad(
    Canvas canvas,
    Path path,
    double outerWidth,
    double innerWidth,
  ) {
    canvas.drawPath(
      path,
      Paint()
        ..color = const Color(0xFF172A38).withValues(alpha: .45)
        ..style = PaintingStyle.stroke
        ..strokeWidth = outerWidth
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round,
    );
    canvas.drawPath(
      path,
      Paint()
        ..color = const Color(0xFF607383)
        ..style = PaintingStyle.stroke
        ..strokeWidth = innerWidth
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round,
    );
  }

  void _drawBuilding(Canvas canvas, Rect rect) {
    final shape = RRect.fromRectAndRadius(rect, const Radius.circular(3));
    canvas.drawRRect(
      shape.shift(const Offset(1.5, 2.5)),
      Paint()..color = const Color(0xFF102735).withValues(alpha: .45),
    );
    canvas.drawRRect(shape, Paint()..color = const Color(0xFF36576A));
    canvas.drawRRect(
      shape,
      Paint()
        ..color = const Color(0xFF78909E).withValues(alpha: .42)
        ..style = PaintingStyle.stroke
        ..strokeWidth = .8,
    );
  }

  void _drawCrosswalk(Canvas canvas, Offset center, double angle) {
    canvas.save();
    canvas.translate(center.dx, center.dy);
    canvas.rotate(angle);
    for (double x = -10; x <= 10; x += 5) {
      canvas.drawRect(
        Rect.fromCenter(center: Offset(x, 0), width: 2.4, height: 12),
        Paint()..color = const Color(0xFFDCE5EA).withValues(alpha: .58),
      );
    }
    canvas.restore();
  }

  void _drawMapLabel(
    Canvas canvas,
    String text,
    Offset center, {
    double angle = 0,
    bool emphasized = false,
  }) {
    final painter = TextPainter(
      text: TextSpan(
        text: text,
        style: TextStyle(
          color: emphasized ? const Color(0xFFE2F3EE) : const Color(0xFFCAD7DF),
          fontSize: emphasized ? 9 : 7.5,
          fontWeight: emphasized ? FontWeight.w700 : FontWeight.w500,
          shadows: const [Shadow(color: Color(0xCC0A1D29), blurRadius: 3)],
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    canvas.save();
    canvas.translate(center.dx, center.dy);
    canvas.rotate(angle);
    painter.paint(canvas, Offset(-painter.width / 2, -painter.height / 2));
    canvas.restore();
  }

  void _paintActiveHalo(Canvas canvas, Offset anchor) {
    canvas.save();
    canvas.translate(anchor.dx, anchor.dy);

    // Shared location halo: the person and companion robot are moving as one.
    canvas.drawCircle(
      const Offset(0, 3),
      31,
      Paint()..color = _mint.withValues(alpha: .13),
    );
    canvas.drawCircle(
      const Offset(0, 3),
      21,
      Paint()..color = _mint.withValues(alpha: .20),
    );
    canvas.drawCircle(const Offset(0, 10), 10, Paint()..color = _mint);
    canvas.restore();
  }

  @override
  bool shouldRepaint(RoutePainter oldDelegate) =>
      active != oldDelegate.active || progress != oldDelegate.progress;
}

class CompanionPainter extends CustomPainter {
  const CompanionPainter();
  @override
  void paint(Canvas canvas, Size size) {
    canvas.save();
    canvas.scale(size.width / 360, size.height / 220);
    canvas.drawRect(
      const Rect.fromLTWH(0, 0, 360, 220),
      Paint()
        ..shader = const LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [Color(0xFF173C4D), Color(0xFF0C2332)],
        ).createShader(const Rect.fromLTWH(0, 0, 360, 220)),
    );
    final random = math.Random(4);
    for (var i = 0; i < 24; i++) {
      canvas.drawCircle(
        Offset(random.nextDouble() * 360, random.nextDouble() * 135),
        1,
        Paint()..color = const Color(0xFF8FAEB5).withValues(alpha: .35),
      );
    }
    canvas.drawCircle(
      const Offset(298, 37),
      15,
      Paint()..color = const Color(0xFFC1DCCE),
    );
    for (var i = 0; i < 9; i++) {
      final x = i * 45.0;
      final h = 35 + random.nextDouble() * 50;
      canvas.drawRRect(
        RRect.fromRectAndRadius(
          Rect.fromLTWH(x, 150 - h, 31, h),
          const Radius.circular(4),
        ),
        Paint()..color = const Color(0xFF1E3A48),
      );
      for (var j = 0; j < 3; j++) {
        canvas.drawRect(
          Rect.fromLTWH(x + 7, 158 - h + j * 15, 4, 5),
          Paint()..color = const Color(0xFF56766D),
        );
      }
    }
    canvas.drawPath(
      Path()
        ..moveTo(135, 133)
        ..lineTo(228, 133)
        ..lineTo(345, 220)
        ..lineTo(14, 220)
        ..close(),
      Paint()..color = const Color(0xFF28454D),
    );
    for (final x in [42.0, 322.0]) {
      canvas.drawLine(
        Offset(x, 86),
        Offset(x, 162),
        Paint()
          ..color = const Color(0xFF72928F)
          ..strokeWidth = 3,
      );
      canvas.drawCircle(
        Offset(x, 86),
        18,
        Paint()
          ..shader = RadialGradient(
            colors: [
              const Color(0xFFFFDA8E).withValues(alpha: .25),
              Colors.transparent,
            ],
          ).createShader(Rect.fromCircle(center: Offset(x, 86), radius: 18)),
      );
      canvas.drawCircle(
        Offset(x, 86),
        5,
        Paint()..color = const Color(0xFFFFE2A5),
      );
    }
    canvas.drawOval(
      const Rect.fromLTWH(118, 159, 142, 20),
      Paint()..color = Colors.black.withValues(alpha: .25),
    );
    void box(Rect rect, double radius, Color color) => canvas.drawRRect(
      RRect.fromRectAndRadius(rect, Radius.circular(radius)),
      Paint()..color = color,
    );
    for (final x in [163.0, 226.0]) {
      box(Rect.fromLTWH(x, 130, 15, 38), 7, const Color(0xFF8AABB2));
      box(Rect.fromLTWH(x - 4, 160, 23, 10), 5, const Color(0xFF0B202C));
    }
    box(const Rect.fromLTWH(156, 102, 94, 46), 22, const Color(0xFFD6E3DF));
    canvas.drawCircle(
      const Offset(234, 124),
      13,
      Paint()..color = const Color(0xFF7D9DA3),
    );
    canvas.drawCircle(const Offset(234, 124), 7, Paint()..color = _mint);
    canvas.drawPath(
      Path()
        ..moveTo(248, 112)
        ..quadraticBezierTo(269, 104, 259, 93),
      Paint()
        ..color = const Color(0xFFBBD3D2)
        ..strokeWidth = 8
        ..style = PaintingStyle.stroke
        ..strokeCap = StrokeCap.round,
    );
    box(const Rect.fromLTWH(111, 66, 78, 65), 26, const Color(0xFFE4ECE6));
    box(const Rect.fromLTWH(106, 77, 13, 34), 7, const Color(0xFF6A929A));
    box(const Rect.fromLTWH(181, 77, 13, 34), 7, const Color(0xFF6A929A));
    box(const Rect.fromLTWH(117, 74, 66, 46), 19, const Color(0xFF0A222C));
    final face = Paint()
      ..color = _mint
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3
      ..strokeCap = StrokeCap.round;
    for (final x in [131.0, 158.0]) {
      canvas.drawArc(
        Rect.fromLTWH(x, 89, 11, 12),
        math.pi,
        math.pi,
        false,
        face,
      );
    }
    canvas.drawArc(
      const Rect.fromLTWH(143, 98, 11, 9),
      0,
      math.pi,
      false,
      face..strokeWidth = 2,
    );
    box(const Rect.fromLTWH(157, 129, 11, 12), 5, _mint);
    canvas.restore();
  }

  @override
  bool shouldRepaint(CompanionPainter oldDelegate) => false;
}
