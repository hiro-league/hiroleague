import 'package:go_router/go_router.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../application/router_notifier.dart';
import '../../core/constants/route_names.dart';
import '../../features/channels/channel_list_screen.dart';
import '../../features/chat/chat_screen.dart';
import '../../features/onboarding/onboarding_screen.dart';
import '../../features/onboarding/qr_scan_screen.dart';
import '../../features/debug/app_logs_screen.dart';
import '../../features/settings/settings_screen.dart';
import '../../features/shell/app_shell.dart';

part 'app_router.g.dart';

@Riverpod(keepAlive: true)
GoRouter appRouter(Ref ref) {
  // Read (not watch) — the ChangeNotifier interface handles refresh.
  final notifier = ref.read(routerProvider.notifier);

  final router = GoRouter(
    initialLocation: RouteNames.channels,
    refreshListenable: notifier,
    redirect: notifier.redirect,
    routes: [
      GoRoute(
        path: RouteNames.onboarding,
        builder: (context, state) => const OnboardingScreen(),
        routes: [
          GoRoute(
            path: 'scan',
            builder: (context, state) => const QrScanScreen(),
          ),
        ],
      ),
      ShellRoute(
        builder: (context, state, child) => AppShell(child: child),
        routes: [
          GoRoute(
            path: RouteNames.channels,
            builder: (context, state) => const ChannelListScreen(),
            routes: [
              // Chat is nested under channels so the nav bar always stays visible.
              GoRoute(
                path: ':channelId',
                builder: (context, state) => ChatScreen(
                  channelId: state.pathParameters['channelId']!,
                ),
              ),
            ],
          ),
          GoRoute(
            path: RouteNames.settings,
            builder: (context, state) => const SettingsScreen(),
          ),
          GoRoute(
            path: RouteNames.appLogs,
            builder: (context, state) => const AppLogsScreen(),
          ),
        ],
      ),
    ],
  );

  ref.onDispose(router.dispose);
  return router;
}
