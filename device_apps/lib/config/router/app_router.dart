import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../application/router_notifier.dart';
import '../../core/constants/route_names.dart';
import '../../features/channels/channel_list_screen.dart';
import '../../features/chat/chat_screen.dart';
import '../../features/onboarding/onboarding_screen.dart';
import '../../features/settings/settings_screen.dart';
import '../../features/shell/app_shell.dart';

part 'app_router.g.dart';

@Riverpod(keepAlive: true)
GoRouter appRouter(Ref ref) {
  // Read (not watch) — the ChangeNotifier interface handles refresh.
  final notifier = ref.read(routerNotifierProvider.notifier);

  final router = GoRouter(
    initialLocation: RouteNames.channels,
    refreshListenable: notifier,
    redirect: notifier.redirect,
    routes: [
      GoRoute(
        path: RouteNames.onboarding,
        builder: (context, state) => const OnboardingScreen(),
      ),
      // Chat lives outside the ShellRoute so the nav bar is hidden during conversation.
      GoRoute(
        path: RouteNames.chat,
        builder: (context, state) => ChatScreen(
          channelId: state.pathParameters['channelId']!,
        ),
      ),
      ShellRoute(
        builder: (context, state, child) => AppShell(child: child),
        routes: [
          GoRoute(
            path: RouteNames.channels,
            builder: (context, state) => const ChannelListScreen(),
          ),
          GoRoute(
            path: RouteNames.settings,
            builder: (context, state) => const SettingsScreen(),
          ),
        ],
      ),
    ],
  );

  ref.onDispose(router.dispose);
  return router;
}
