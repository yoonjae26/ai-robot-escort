import 'dart:async';
import 'dart:ui';

import 'package:flutter/material.dart';

import 'kakao_route_map.dart';
import 'scene.dart';

const mint = Color(0xFF18CDB5);
const muted = Color(0xFFA7BACB);
const coral = Color(0xFFFF3F58);
const ink = Color(0xFFF4FAFF);
const deepNavy = Color(0xFF0B2540);

enum Journey { home, route, verify, walking, help, done }

enum VerifyPhase { approaching, scanning, recognized }

class Prototype extends StatefulWidget {
  const Prototype({super.key});
  @override
  State<Prototype> createState() => _PrototypeState();
}

class _PrototypeState extends State<Prototype>
    with SingleTickerProviderStateMixin {
  Journey stage = Journey.home;
  int tab = 0;
  String origin = '중앙공원 정문';
  String destination = '우리 집';
  bool paused = false;
  bool verified = false;
  bool _kakaoMapUnavailable = false;
  VerifyPhase verifyPhase = VerifyPhase.approaching;
  Timer? _approachTimer;
  Timer? _recognitionTimer;
  late final AnimationController _routeController;
  int rating = -1;
  final List<({String from, String to, int rating})> trips = [];

  @override
  void initState() {
    super.initState();
    _routeController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 18),
    );
  }

  void go(Journey next) {
    _approachTimer?.cancel();
    _recognitionTimer?.cancel();
    setState(() {
      stage = next;
      if (next == Journey.verify) {
        verified = false;
        verifyPhase = VerifyPhase.approaching;
      }
    });
    if (next == Journey.walking) {
      _routeController.repeat();
    } else {
      _routeController.stop();
      if (next == Journey.home || next == Journey.verify) {
        _routeController.reset();
      }
    }
    if (next == Journey.verify) {
      _approachTimer = Timer(const Duration(milliseconds: 900), () {
        if (!mounted || stage != Journey.verify) return;
        setState(() => verifyPhase = VerifyPhase.scanning);
        _recognitionTimer = Timer(const Duration(milliseconds: 1500), () {
          if (!mounted || stage != Journey.verify) return;
          setState(() {
            verifyPhase = VerifyPhase.recognized;
            verified = true;
          });
        });
      });
    }
  }

  @override
  void dispose() {
    _approachTimer?.cancel();
    _recognitionTimer?.cancel();
    _routeController.dispose();
    super.dispose();
  }

  void togglePause() {
    setState(() => paused = !paused);
    if (paused) {
      _routeController.stop();
    } else {
      _routeController.repeat();
    }
  }

  void notice(String message) => ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(content: Text(message), behavior: SnackBarBehavior.floating),
  );

  Future<void> selectPlace(bool start) async {
    final places = start
        ? ['중앙공원 정문', '안심센터 앞', '도서관 입구']
        : ['우리 집', '지하철 2번 출구', '안심센터'];
    final value = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                start ? '어디에서 만날까요?' : '어디까지 함께 갈까요?',
                style: const TextStyle(
                  fontSize: 22,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 8),
              const Text(
                '서비스 지역 내 장소를 선택해 주세요.',
                style: TextStyle(color: muted),
              ),
              const SizedBox(height: 16),
              for (final place in places)
                ListTile(
                  leading: Icon(
                    start ? Icons.location_on_outlined : Icons.flag_outlined,
                    color: mint,
                  ),
                  title: Text(place),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => Navigator.pop(context, place),
                ),
            ],
          ),
        ),
      ),
    );
    if (value != null && mounted) {
      setState(() {
        if (start) {
          origin = value;
        } else {
          destination = value;
        }
      });
    }
  }

  Future<void> confirmEnd() async {
    final result = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('동행을 종료할까요?'),
        content: const Text('진행 중인 동행을 종료하고 홈으로 돌아갑니다.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('계속 동행'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('종료하기'),
          ),
        ],
      ),
    );
    if (result == true && mounted) {
      _routeController.stop();
      _routeController.reset();
      setState(() {
        stage = Journey.home;
        paused = false;
        verified = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final root = stage == Journey.home;
    return Scaffold(
      backgroundColor: const Color(0xFF071522),
      body: LayoutBuilder(
        builder: (context, constraints) {
          final app = Container(
            decoration: const BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: [Color(0xFF102E49), deepNavy, Color(0xFF061625)],
                stops: [0, .58, 1],
              ),
            ),
            child: SafeArea(
              child: Center(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 480),
                  child: Column(
                    children: [
                      Padding(
                        padding: const EdgeInsets.fromLTRB(14, 10, 14, 8),
                        child: JellySurface(
                          radius: 26,
                          padding: const EdgeInsets.fromLTRB(12, 9, 8, 9),
                          child: Row(
                            children: [
                              if (stage == Journey.route ||
                                  stage == Journey.verify)
                                IconButton(
                                  tooltip: '뒤로',
                                  onPressed: () => go(
                                    stage == Journey.verify
                                        ? Journey.route
                                        : Journey.home,
                                  ),
                                  icon: const Icon(Icons.arrow_back_rounded),
                                )
                              else
                                Container(
                                  width: 42,
                                  height: 42,
                                  decoration: BoxDecoration(
                                    shape: BoxShape.circle,
                                    gradient: const LinearGradient(
                                      begin: Alignment.topLeft,
                                      end: Alignment.bottomRight,
                                      colors: [Color(0xFF62EAD8), mint],
                                    ),
                                    border: Border.all(
                                      color: Colors.white.withValues(
                                        alpha: .75,
                                      ),
                                    ),
                                    boxShadow: [
                                      BoxShadow(
                                        color: mint.withValues(alpha: .34),
                                        blurRadius: 14,
                                        offset: const Offset(0, 6),
                                      ),
                                    ],
                                  ),
                                  child: const Icon(
                                    Icons.pets_rounded,
                                    color: deepNavy,
                                    size: 22,
                                  ),
                                ),
                              const SizedBox(width: 10),
                              const Text(
                                '지켜줄개',
                                style: TextStyle(
                                  color: ink,
                                  fontSize: 21,
                                  fontWeight: FontWeight.w800,
                                  letterSpacing: -1,
                                ),
                              ),
                              const Spacer(),
                              JellyIconButton(
                                tooltip: '알림',
                                onPressed: () =>
                                    notice('새로운 알림이 없어요. 오늘도 안전한 하루 보내세요.'),
                                icon: Icons.notifications_none_rounded,
                              ),
                            ],
                          ),
                        ),
                      ),
                      Expanded(
                        child: SingleChildScrollView(
                          key: ValueKey('$stage-$tab'),
                          padding: const EdgeInsets.fromLTRB(24, 8, 24, 24),
                          child: root
                              ? (tab == 0
                                    ? home()
                                    : tab == 1
                                    ? history()
                                    : profile())
                              : switch (stage) {
                                  Journey.route => route(),
                                  Journey.verify => verify(),
                                  Journey.walking => walking(),
                                  Journey.help => help(),
                                  Journey.done => done(),
                                  _ => home(),
                                },
                        ),
                      ),
                      if (root)
                        Padding(
                          padding: const EdgeInsets.fromLTRB(14, 2, 14, 10),
                          child: JellySurface(
                            radius: 30,
                            padding: EdgeInsets.zero,
                            child: NavigationBar(
                              height: 72,
                              backgroundColor: Colors.transparent,
                              surfaceTintColor: Colors.transparent,
                              indicatorColor: mint.withValues(alpha: .38),
                              selectedIndex: tab,
                              onDestinationSelected: (value) =>
                                  setState(() => tab = value),
                              destinations: const [
                                NavigationDestination(
                                  icon: Icon(Icons.home_outlined),
                                  selectedIcon: Icon(
                                    Icons.home_rounded,
                                    color: mint,
                                  ),
                                  label: '홈',
                                ),
                                NavigationDestination(
                                  icon: Icon(Icons.receipt_long_outlined),
                                  selectedIcon: Icon(
                                    Icons.receipt_long,
                                    color: mint,
                                  ),
                                  label: '이용 내역',
                                ),
                                NavigationDestination(
                                  icon: Icon(Icons.person_outline),
                                  selectedIcon: Icon(Icons.person, color: mint),
                                  label: '내 정보',
                                ),
                              ],
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
              ),
            ),
          );
          if (constraints.maxWidth < 700) return app;

          final frameHeight = constraints.maxHeight > 920
              ? 900.0
              : constraints.maxHeight - 28;
          return Container(
            decoration: const BoxDecoration(
              gradient: RadialGradient(
                center: Alignment.topCenter,
                radius: 1.3,
                colors: [Color(0xFF18354B), Color(0xFF06111D)],
              ),
            ),
            child: Center(
              child: Container(
                key: const ValueKey('phone-frame'),
                width: 446,
                height: frameHeight,
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: const Color(0xFF02080E),
                  borderRadius: BorderRadius.circular(48),
                  border: Border.all(
                    color: Colors.white.withValues(alpha: .16),
                    width: 1.2,
                  ),
                  boxShadow: const [
                    BoxShadow(
                      color: Color(0x99000000),
                      blurRadius: 52,
                      offset: Offset(0, 28),
                    ),
                    BoxShadow(
                      color: Color(0x2618CDB5),
                      blurRadius: 34,
                      spreadRadius: 2,
                    ),
                  ],
                ),
                child: Stack(
                  alignment: Alignment.topCenter,
                  children: [
                    Positioned.fill(
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(40),
                        child: app,
                      ),
                    ),
                    Positioned(
                      top: 9,
                      child: IgnorePointer(
                        child: Container(
                          width: 102,
                          height: 25,
                          decoration: BoxDecoration(
                            color: const Color(0xFF02070C),
                            borderRadius: BorderRadius.circular(20),
                            border: Border.all(
                              color: Colors.white.withValues(alpha: .06),
                            ),
                            boxShadow: const [
                              BoxShadow(
                                color: Color(0x66000000),
                                blurRadius: 8,
                              ),
                            ],
                          ),
                          child: Align(
                            alignment: const Alignment(.48, 0),
                            child: Container(
                              width: 7,
                              height: 7,
                              decoration: const BoxDecoration(
                                color: Color(0xFF102738),
                                shape: BoxShape.circle,
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          );
        },
      ),
    );
  }

  Widget heading(String eyebrow, String title, String subtitle) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(
        eyebrow,
        style: const TextStyle(
          color: mint,
          fontSize: 12,
          letterSpacing: 1.5,
          fontWeight: FontWeight.w700,
        ),
      ),
      const SizedBox(height: 10),
      Text(
        title,
        style: const TextStyle(
          fontSize: 29,
          fontWeight: FontWeight.w800,
          height: 1.3,
          letterSpacing: -1.3,
        ),
      ),
      const SizedBox(height: 10),
      Text(subtitle, style: const TextStyle(color: muted, height: 1.6)),
      const SizedBox(height: 22),
    ],
  );
  Widget home() => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      heading(
        'YOUR SAFE COMPANION',
        '집으로 가는 길,\n혼자가 아니니까.',
        '오늘도 지켜줄개와 함께 안심하고 걸어요.',
      ),
      Container(
        height: 220,
        clipBehavior: Clip.antiAlias,
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(24),
          border: Border.all(color: const Color(0xFF2A4657)),
        ),
        child: Stack(
          children: [
            const Positioned.fill(
              child: CustomPaint(painter: CompanionPainter()),
            ),
            const Positioned(
              top: 17,
              left: 17,
              child: BadgeLabel('●  동행 준비 완료'),
            ),
            Positioned(
              bottom: 16,
              left: 18,
              right: 18,
              child: Row(
                children: [
                  const Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '든든한 나의 동행 친구',
                        style: TextStyle(color: muted, fontSize: 12),
                      ),
                      Text(
                        '지켜줄개 01',
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ],
                  ),
                  const Spacer(),
                  Container(
                    padding: const EdgeInsets.all(9),
                    decoration: BoxDecoration(
                      color: mint.withValues(alpha: .12),
                      shape: BoxShape.circle,
                    ),
                    child: const Icon(Icons.pets, color: mint, size: 20),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
      const SizedBox(height: 24),
      const Text(
        '어디까지 함께 갈까요?',
        style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
      ),
      const SizedBox(height: 14),
      Panel(
        child: Column(
          children: [
            placeRow(true),
            const Divider(color: Color(0xFF2B4355), height: 25),
            placeRow(false),
          ],
        ),
      ),
      const SizedBox(height: 18),
      action('안심 동행 요청하기', () {
        verified = false;
        paused = false;
        rating = -1;
        go(Journey.route);
      }, icon: Icons.arrow_forward_rounded),
      const SizedBox(height: 14),
      const Text(
        '♧  지정된 서비스 지역에서 함께해요',
        textAlign: TextAlign.center,
        style: TextStyle(color: muted, fontSize: 12),
      ),
    ],
  );
  Widget placeRow(bool start) => InkWell(
    borderRadius: BorderRadius.circular(12),
    onTap: () => selectPlace(start),
    child: Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: (start ? mint : coral).withValues(alpha: .18),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Icon(
              start ? Icons.location_on_rounded : Icons.flag_rounded,
              color: start ? mint : coral,
            ),
          ),
          const SizedBox(width: 13),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  start ? '출발지' : '목적지',
                  style: const TextStyle(color: muted, fontSize: 11),
                ),
                Text(
                  start ? origin : destination,
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
          ),
          const Icon(Icons.chevron_right, color: muted),
        ],
      ),
    ),
  );
  Widget route() => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      heading('01  /  동행 요청', '이 길로 함께 갈게요', '밝은 길을 따라 목적지까지 안내할게요.'),
      Panel(
        child: Column(
          children: [
            placeRow(true),
            const Divider(color: Color(0xFF2B4355), height: 24),
            placeRow(false),
          ],
        ),
      ),
      const SizedBox(height: 16),
      map(),
      const SizedBox(height: 16),
      Panel(
        child: Row(
          children: [
            const Icon(Icons.directions_walk, color: mint, size: 30),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    '도보 약 7분 · 450m',
                    style: TextStyle(fontSize: 19, fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '$origin → $destination',
                    style: const TextStyle(color: muted, fontSize: 12),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
      const SizedBox(height: 16),
      const Text(
        'ⓘ 교통 상황에 따라 거리와 이동 시간이 달라질 수 있어요.',
        style: TextStyle(color: muted, fontSize: 12),
      ),
      const SizedBox(height: 24),
      action(
        '이 경로로 동행 요청',
        () => go(Journey.verify),
        icon: Icons.arrow_forward,
      ),
    ],
  );
  Widget verify() {
    final scanning = verifyPhase == VerifyPhase.scanning;
    final recognized = verifyPhase == VerifyPhase.recognized;
    final distance = verifyPhase == VerifyPhase.approaching ? '3.4m' : '1.6m';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        heading('02  /  동행자 확인', '반가워요, 기다렸어요!', '지켜줄개 가까이에서 동행을 준비해 주세요.'),
        ClipRRect(
          borderRadius: BorderRadius.circular(22),
          child: SizedBox(
            height: 220,
            child: Stack(
              fit: StackFit.expand,
              children: [
                const CustomPaint(painter: CompanionPainter()),
                if (scanning || recognized) ...[
                  Container(
                    color: const Color(0xFF031522).withValues(alpha: .32),
                  ),
                  Center(
                    child: AnimatedContainer(
                      duration: const Duration(milliseconds: 350),
                      width: recognized ? 142 : 168,
                      height: recognized ? 142 : 168,
                      decoration: BoxDecoration(
                        borderRadius: BorderRadius.circular(30),
                        border: Border.all(
                          color: recognized ? mint : Colors.white,
                          width: recognized ? 3 : 2,
                        ),
                        boxShadow: [
                          BoxShadow(
                            color: mint.withValues(
                              alpha: recognized ? .34 : .18,
                            ),
                            blurRadius: 24,
                          ),
                        ],
                      ),
                      child: Icon(
                        recognized
                            ? Icons.check_circle_rounded
                            : Icons.center_focus_strong_rounded,
                        color: recognized ? mint : Colors.white,
                        size: 44,
                      ),
                    ),
                  ),
                  Positioned(
                    left: 16,
                    right: 16,
                    bottom: 14,
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(
                          recognized
                              ? Icons.verified_rounded
                              : Icons.videocam_rounded,
                          color: recognized ? mint : Colors.white,
                          size: 18,
                        ),
                        const SizedBox(width: 7),
                        Text(
                          recognized ? '지켜줄개 인식 완료' : '카메라로 지켜줄개를 인식하고 있어요',
                          style: const TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.w700,
                            fontSize: 13,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
        const SizedBox(height: 16),
        Panel(
          child: Row(
            children: [
              Icon(
                scanning || recognized ? Icons.videocam_rounded : Icons.radar,
                color: mint,
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  '로봇과의 거리 $distance',
                  style: const TextStyle(
                    fontSize: 17,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
              BadgeLabel(
                recognized
                    ? '인식 완료'
                    : scanning
                    ? '인식 중'
                    : '접근 중',
              ),
            ],
          ),
        ),
        const SizedBox(height: 20),
        const Text(
          '동행 전 확인해 주세요',
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
        ),
        const SizedBox(height: 8),
        Text(
          recognized
              ? '지켜줄개와 동행자가 확인됐어요. 이제 안전 동행을 시작할 수 있어요.'
              : scanning
              ? '카메라가 자동으로 켜졌어요. 잠시 정면에서 기다려 주세요.'
              : '로봇에서 2m 이내로 가까이 와 주세요. 가까워지면 카메라가 자동으로 켜져요.',
          style: const TextStyle(color: muted, height: 1.7),
        ),
        const SizedBox(height: 18),
        Panel(
          child: Row(
            children: [
              Icon(
                recognized
                    ? Icons.check_circle_rounded
                    : Icons.hourglass_top_rounded,
                color: recognized ? mint : muted,
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  recognized ? '동행자 확인 완료' : '동행자를 자동으로 확인하고 있어요',
                  style: const TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        action(
          '지켜줄개와 동행 시작',
          verified ? () => go(Journey.walking) : null,
          icon: Icons.pets,
        ),
        const SizedBox(height: 10),
        action(
          '로봇을 찾을 수 없어요',
          () => notice('지켜줄개는 $origin 안내판 옆에서 기다리고 있어요.'),
          secondary: true,
        ),
      ],
    );
  }

  Widget map({bool active = false}) => Container(
    height: 280,
    clipBehavior: Clip.antiAlias,
    decoration: BoxDecoration(
      borderRadius: BorderRadius.circular(22),
      border: Border.all(color: const Color(0xFF385366)),
    ),
    child: LayoutBuilder(
      builder: (context, constraints) {
        final useKakaoMap = kakaoMapInitialized && !_kakaoMapUnavailable;
        final markerSize = (constraints.maxWidth * .22)
            .clamp(68.0, 84.0)
            .toDouble();
        Widget kakaoMap() => KakaoRouteMap(
          onUnavailable: () {
            if (mounted && !_kakaoMapUnavailable) {
              setState(() => _kakaoMapUnavailable = true);
            }
          },
        );

        Widget buildMap(double progress, Widget? mapChild) {
          final marker = routePosition(progress);
          return Stack(
            children: [
              Positioned.fill(
                child: useKakaoMap
                    ? mapChild!
                    : CustomPaint(
                        painter: RoutePainter(
                          active: active,
                          progress: progress,
                        ),
                      ),
              ),
              if (useKakaoMap && !active)
                Positioned(
                  left: constraints.maxWidth * (78 / 360) - 15,
                  top: constraints.maxHeight * (200 / 280) - 30,
                  child: const _MapPin(icon: Icons.directions_bus_rounded),
                ),
              if (useKakaoMap)
                Positioned(
                  left: constraints.maxWidth * (290 / 360) - 15,
                  top: constraints.maxHeight * (61 / 280) - 30,
                  child: const _MapPin(icon: Icons.home_rounded),
                ),
              if (active)
                Positioned(
                  left:
                      constraints.maxWidth * (marker.dx / 360) - markerSize / 2,
                  top:
                      constraints.maxHeight * (marker.dy / 280) -
                      markerSize / 2,
                  width: markerSize,
                  height: markerSize,
                  child: Semantics(
                    image: true,
                    label: '사람과 지켜줄개의 현재 위치',
                    child: Image.asset(
                      'assets/images/current_location_marker.png',
                      fit: BoxFit.contain,
                      filterQuality: FilterQuality.high,
                    ),
                  ),
                ),
              const Positioned(top: 14, left: 14, child: BadgeLabel('추천 경로')),
              Positioned(
                top: 15,
                right: 15,
                child: Text(
                  destination,
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
              Positioned(
                bottom: 0,
                left: 0,
                right: 0,
                child: DefaultTextStyle.merge(
                  style: const TextStyle(color: Colors.white),
                  child: IconTheme(
                    data: const IconThemeData(color: Colors.white),
                    child: Container(
                      padding: const EdgeInsets.all(14),
                      color: const Color(0xEE102535),
                      child: Row(
                        children: [
                          const Icon(Icons.location_on, color: mint, size: 19),
                          const SizedBox(width: 6),
                          Expanded(
                            child: Text(
                              active ? '지켜줄개와 함께 이동 중' : origin,
                              style: const TextStyle(fontSize: 12),
                            ),
                          ),
                          const Icon(Icons.home_rounded, size: 18),
                          const SizedBox(width: 5),
                          const Text('목적지', style: TextStyle(fontSize: 12)),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ],
          );
        }

        if (!active) return buildMap(0, useKakaoMap ? kakaoMap() : null);
        return AnimatedBuilder(
          animation: _routeController,
          builder: (context, child) => buildMap(
            Curves.easeInOut.transform(_routeController.value),
            child,
          ),
          child: useKakaoMap ? kakaoMap() : null,
        );
      },
    ),
  );
  Widget walking() => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      heading(
        '03  /  안심 동행',
        paused ? '잠시 쉬어 가요' : '함께 걷고 있어요',
        paused ? '준비되면 다시 출발해요.' : '서두르지 않아도 괜찮아요. 곁에 있을게요.',
      ),
      const Wrap(
        spacing: 8,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          BadgeLabel('●  지켜줄개 01'),
          Text('안심 동행 중', style: TextStyle(color: muted, fontSize: 12)),
        ],
      ),
      const SizedBox(height: 16),
      map(active: true),
      const SizedBox(height: 16),
      Panel(
        child: Row(
          children: [
            Icon(
              paused ? Icons.pause_circle_outline : Icons.schedule,
              color: mint,
              size: 30,
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    paused ? '동행을 잠시 멈췄어요' : '목적지까지 약 5분',
                    style: const TextStyle(
                      fontSize: 19,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const Text(
                    '안전한 발걸음, 끝까지 함께해요.',
                    style: TextStyle(color: muted, fontSize: 12),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
      const SizedBox(height: 24),
      Row(
        children: [
          Expanded(
            child: action(
              paused ? '다시 출발' : '잠시 멈추기',
              togglePause,
              secondary: true,
              icon: paused ? Icons.play_arrow : Icons.pause,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: action(
              '동행 종료',
              confirmEnd,
              secondary: true,
              icon: Icons.close,
            ),
          ),
        ],
      ),
      const SizedBox(height: 12),
      action(
        '긴급 도움 요청',
        () => go(Journey.help),
        danger: true,
        icon: Icons.sos_rounded,
      ),
      const SizedBox(height: 12),
      TextButton(
        onPressed: paused
            ? null
            : () {
                trips.insert(0, (from: origin, to: destination, rating: -1));
                go(Journey.done);
              },
        child: const Text('목적지에 도착했어요 →'),
      ),
    ],
  );
  Widget help() => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      heading('도움 요청', '도움이 필요할 때,\n곁에서 지켜줄게요.', '위치와 동행 정보를 관제 담당자에게 전달해요.'),
      const Panel(
        color: Color(0xFF492934),
        child: Column(
          children: [
            Icon(Icons.error_rounded, color: coral, size: 48),
            SizedBox(height: 12),
            Text(
              '도움 요청을 보냈어요',
              style: TextStyle(fontSize: 21, fontWeight: FontWeight.bold),
            ),
            SizedBox(height: 6),
            Text(
              '관제 담당자가 요청 내용을 확인하고 있어요.',
              style: TextStyle(color: Color(0xFFE3BCC4)),
            ),
          ],
        ),
      ),
      const SizedBox(height: 16),
      Panel(
        child: Column(
          children: [
            info('요청 유형', '동행 중 도움 필요'),
            const Divider(),
            info('마지막 확인 위치', origin),
            const Divider(),
            info('위치 갱신', '방금 전'),
          ],
        ),
      ),
      const SizedBox(height: 16),
      const Panel(
        child: Column(
          children: [
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: Icon(Icons.check_circle, color: mint),
              title: Text('요청 전송 단계'),
              subtitle: Text('위치와 동행 정보를 전달했어요'),
            ),
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: Icon(Icons.radio_button_checked, color: mint),
              title: Text('담당자 확인 단계'),
              subtitle: Text('담당자가 내용을 확인하고 있어요'),
            ),
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: Icon(Icons.phone_outlined, color: muted),
              title: Text('연락 연결 단계'),
              subtitle: Text('필요하면 담당자와 바로 연결할 수 있어요'),
            ),
          ],
        ),
      ),
      const SizedBox(height: 22),
      action(
        '관제 담당자에게 연락',
        () => notice('관제 담당자에게 연결하고 있어요.'),
        icon: Icons.call,
      ),
      const SizedBox(height: 12),
      action('요청 취소 · 동행으로 돌아가기', () => go(Journey.walking), secondary: true),
    ],
  );
  Widget done() => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      const SizedBox(height: 16),
      const Center(
        child: CircleAvatar(
          radius: 38,
          backgroundColor: mint,
          child: Icon(Icons.check_rounded, color: Color(0xFF09212B), size: 48),
        ),
      ),
      const SizedBox(height: 25),
      const Text(
        '무사히 도착했어요',
        textAlign: TextAlign.center,
        style: TextStyle(fontSize: 29, fontWeight: FontWeight.w800),
      ),
      const SizedBox(height: 10),
      const Text(
        '함께 걸어서 더 든든했던 길.\n오늘도 편안한 밤 보내세요.',
        textAlign: TextAlign.center,
        style: TextStyle(color: muted, height: 1.7),
      ),
      const SizedBox(height: 28),
      Panel(
        child: Column(
          children: [
            info('도착 장소', destination),
            const Divider(height: 28),
            info('동행 시간 · 거리', '7분 · 450m'),
            const Divider(height: 28),
            info('함께한 친구', '지켜줄개 01'),
          ],
        ),
      ),
      const SizedBox(height: 16),
      Panel(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              '오늘의 동행은 어땠나요?',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 6),
            Text(
              rating < 0 ? '의견을 들려주시면 더 좋은 친구가 될게요.' : '소중한 의견 고마워요!',
              style: const TextStyle(color: muted, fontSize: 12),
            ),
            const SizedBox(height: 18),
            Row(
              children: [
                for (var i = 0; i < 3; i++)
                  Expanded(
                    child: Padding(
                      padding: EdgeInsets.only(right: i == 2 ? 0 : 8),
                      child: OutlinedButton(
                        style: OutlinedButton.styleFrom(
                          padding: const EdgeInsets.symmetric(vertical: 16),
                          backgroundColor: rating == i
                              ? mint.withValues(alpha: .22)
                              : null,
                          side: BorderSide(
                            color: rating == i ? mint : const Color(0x33405E79),
                          ),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(12),
                          ),
                        ),
                        onPressed: () => setState(() {
                          rating = i;
                          trips[0] = (from: origin, to: destination, rating: i);
                        }),
                        child: Column(
                          children: [
                            Icon(
                              [
                                Icons.sentiment_dissatisfied,
                                Icons.sentiment_neutral,
                                Icons.sentiment_satisfied_alt,
                              ][i],
                              color: rating == i ? mint : muted,
                              size: 34,
                            ),
                            const SizedBox(height: 8),
                            Text(
                              ['아쉬워요', '괜찮아요', '만족해요'][i],
                              style: TextStyle(
                                fontSize: 12,
                                color: rating == i ? mint : ink,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ],
        ),
      ),
      const SizedBox(height: 24),
      action('홈으로', () {
        tab = 0;
        go(Journey.home);
      }, icon: Icons.home_rounded),
      const SizedBox(height: 10),
      action('이용 내역 보기', () {
        tab = 1;
        go(Journey.home);
      }, secondary: true),
    ],
  );
  Widget history() => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      heading('OUR FOOTPRINTS', '함께 걸어온 길', '지켜줄개와의 안심 동행 기록이에요.'),
      if (trips.isNotEmpty) ...[
        const Text('최근 동행', style: TextStyle(color: mint)),
        const SizedBox(height: 12),
        for (final trip in trips) ...[
          historyCard(trip.from, trip.to, '7분 · 450m', trip.rating),
          const SizedBox(height: 12),
        ],
        const SizedBox(height: 12),
      ],
      const Text('지난 동행', style: TextStyle(color: muted)),
      const SizedBox(height: 12),
      historyCard('도서관 입구', '우리 집', '9월 25일 · 9분 · 620m', 2),
      const SizedBox(height: 12),
      historyCard('지하철 2번 출구', '우리 집', '9월 23일 · 6분 · 380m', 2),
    ],
  );
  Widget historyCard(String from, String to, String detail, int review) =>
      Panel(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.check_circle_outline, color: mint, size: 18),
                const SizedBox(width: 8),
                const Text(
                  '동행 완료',
                  style: TextStyle(color: mint, fontWeight: FontWeight.bold),
                ),
                const Spacer(),
                if (review >= 0)
                  Text(
                    ['아쉬워요', '괜찮아요', '만족해요'][review],
                    style: const TextStyle(color: muted, fontSize: 12),
                  ),
              ],
            ),
            const SizedBox(height: 15),
            Text(
              '$from → $to',
              style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
            ),
            const SizedBox(height: 8),
            Text(detail, style: const TextStyle(color: muted, fontSize: 12)),
          ],
        ),
      );
  Widget profile() => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      heading('MY COMPANION', '안녕하세요, 동행님', '당신의 평범한 하루가 더 안전하도록.'),
      const Panel(
        child: Row(
          children: [
            CircleAvatar(
              radius: 28,
              backgroundColor: Color(0xFF234B51),
              child: Icon(Icons.person_outline, color: mint, size: 30),
            ),
            SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '동행님',
                    style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
                  ),
                  Text('지켜줄개 이용자', style: TextStyle(color: muted)),
                ],
              ),
            ),
          ],
        ),
      ),
      const SizedBox(height: 18),
      Panel(
        child: Column(
          children: [
            info('나의 동행 친구', '지켜줄개 01'),
            const Divider(height: 30),
            info('서비스 지역', '중앙공원 일대'),
            const Divider(height: 30),
            info('앱 버전', '1.0.0'),
          ],
        ),
      ),
      const SizedBox(height: 24),
      const Text(
        '위치 정보는 안심 동행 서비스를 제공하고 긴급 상황에 대응하기 위해 사용돼요.',
        style: TextStyle(color: muted, height: 1.8),
      ),
    ],
  );
  Widget info(String label, String value) => Row(
    children: [
      Text(label, style: const TextStyle(color: muted, fontSize: 13)),
      const SizedBox(width: 12),
      Expanded(
        child: Text(
          value,
          textAlign: TextAlign.right,
          style: const TextStyle(fontWeight: FontWeight.w600),
        ),
      ),
    ],
  );
  Widget action(
    String label,
    VoidCallback? onPressed, {
    bool secondary = false,
    bool danger = false,
    IconData? icon,
  }) {
    final disabled = onPressed == null;
    final radius = BorderRadius.circular(19);
    final colors = disabled
        ? const [Color(0xFF344B60), Color(0xFF263A4E)]
        : danger
        ? const [Color(0xFFFF7082), coral]
        : secondary
        ? const [Color(0xFF2B4A63), Color(0xFF17334C)]
        : const [Color(0xFF5DE5D2), mint];
    return Container(
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: colors,
        ),
        borderRadius: radius,
        border: Border.all(color: Colors.white.withValues(alpha: .28)),
        boxShadow: [
          BoxShadow(
            color: (danger ? coral : mint).withValues(alpha: .30),
            blurRadius: 20,
            offset: const Offset(0, 9),
          ),
          BoxShadow(
            color: Colors.white.withValues(alpha: .30),
            blurRadius: 2,
            offset: const Offset(0, 1),
            blurStyle: BlurStyle.inner,
          ),
        ],
      ),
      child: FilledButton(
        onPressed: onPressed,
        style: FilledButton.styleFrom(
          minimumSize: const Size(double.infinity, 58),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 16),
          backgroundColor: Colors.transparent,
          disabledBackgroundColor: Colors.transparent,
          shadowColor: Colors.transparent,
          foregroundColor: danger || secondary ? Colors.white : deepNavy,
          disabledForegroundColor: muted,
          shape: RoundedRectangleBorder(borderRadius: radius),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            if (icon != null) ...[
              Icon(icon, size: 21),
              const SizedBox(width: 8),
            ],
            Flexible(
              child: Text(
                label,
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: secondary ? 14 : 16,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _MapPin extends StatelessWidget {
  const _MapPin({required this.icon});

  final IconData icon;

  @override
  Widget build(BuildContext context) => Container(
    width: 30,
    height: 30,
    decoration: BoxDecoration(
      color: deepNavy,
      shape: BoxShape.circle,
      border: Border.all(color: Colors.white, width: 2),
      boxShadow: const [
        BoxShadow(
          color: Color(0x66000000),
          blurRadius: 8,
          offset: Offset(0, 3),
        ),
      ],
    ),
    child: Icon(icon, color: mint, size: 17),
  );
}

class Panel extends StatelessWidget {
  const Panel({super.key, required this.child, this.color});
  final Widget child;
  final Color? color;
  @override
  Widget build(BuildContext context) => DefaultTextStyle.merge(
    style: TextStyle(color: color == null ? ink : Colors.white),
    child: IconTheme(
      data: IconThemeData(color: color == null ? ink : Colors.white),
      child: JellySurface(
        radius: 24,
        padding: const EdgeInsets.all(18),
        tint: color,
        child: child,
      ),
    ),
  );
}

class BadgeLabel extends StatelessWidget {
  const BadgeLabel(this.text, {super.key});
  final String text;
  @override
  Widget build(BuildContext context) => JellySurface(
    radius: 99,
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
    tint: mint.withValues(alpha: .30),
    child: Text(
      text,
      style: const TextStyle(
        color: mint,
        fontSize: 10,
        fontWeight: FontWeight.w800,
        letterSpacing: .5,
      ),
    ),
  );
}

class JellySurface extends StatelessWidget {
  const JellySurface({
    super.key,
    required this.child,
    required this.radius,
    required this.padding,
    this.tint,
  });

  final Widget child;
  final double radius;
  final EdgeInsetsGeometry padding;
  final Color? tint;

  @override
  Widget build(BuildContext context) {
    final customTint = tint;
    return ClipRRect(
      borderRadius: BorderRadius.circular(radius),
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 18, sigmaY: 18),
        child: Container(
          padding: padding,
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: customTint == null
                  ? const [Color(0xD91A3A55), Color(0xB30B2540)]
                  : [
                      Colors.white.withValues(alpha: .16),
                      customTint,
                      customTint.withValues(alpha: .88),
                    ],
              stops: customTint == null ? null : const [0, .38, 1],
            ),
            borderRadius: BorderRadius.circular(radius),
            border: Border.all(color: Colors.white.withValues(alpha: .22)),
            boxShadow: [
              BoxShadow(
                color: Colors.white.withValues(alpha: .28),
                blurRadius: 2,
                offset: const Offset(0, 1),
                blurStyle: BlurStyle.inner,
              ),
              BoxShadow(
                color: Colors.black.withValues(alpha: .22),
                blurRadius: 24,
                offset: const Offset(0, 10),
              ),
            ],
          ),
          child: child,
        ),
      ),
    );
  }
}

class JellyIconButton extends StatelessWidget {
  const JellyIconButton({
    super.key,
    required this.tooltip,
    required this.onPressed,
    required this.icon,
  });

  final String tooltip;
  final VoidCallback onPressed;
  final IconData icon;

  @override
  Widget build(BuildContext context) => JellySurface(
    radius: 99,
    padding: EdgeInsets.zero,
    tint: const Color(0x6615344E),
    child: IconButton(
      tooltip: tooltip,
      onPressed: onPressed,
      icon: Icon(icon, color: ink, size: 21),
    ),
  );
}
