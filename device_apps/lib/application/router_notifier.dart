import 'package:flutter/widgets.dart';
import 'package:go_router/go_router.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../core/constants/route_names.dart';
import 'auth/auth_notifier.dart';
import 'auth/auth_state.dart';

part 'router_notifier.g.dart';

/// Bridges Riverpod auth state → go_router redirect.
/// Acts as the single source of truth for route guards.
@Riverpod(keepAlive: true)
class RouterNotifier extends _$RouterNotifier with ChangeNotifier {
  @override
  void build() {
    // Notify go_router whenever auth state changes so redirect is re-evaluated.
    ref.listen(authProvider, (_, __) => notifyListeners());
  }

  String? redirect(BuildContext context, GoRouterState state) {
    final authAsync = ref.read(authProvider);

    // Don't redirect while the identity is loading from storage.
    if (authAsync.isLoading) return null;

    final auth = authAsync.value;
    if (auth == null) return null;

    final isOnboarding = state.uri.path.startsWith(RouteNames.onboarding);

    return auth.when(
      unauthenticated: () => isOnboarding ? null : RouteNames.onboarding,
      pairing: () => isOnboarding ? null : RouteNames.onboarding,
      // Once authenticated, leave the onboarding route.
      authenticated: (_) => isOnboarding ? RouteNames.channels : null,
      error: (_) => isOnboarding ? null : RouteNames.onboarding,
    );
  }
}
