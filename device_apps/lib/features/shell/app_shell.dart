import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/ui/adaptive_layout.dart';
import 'nav_destinations.dart';

class AppShell extends StatelessWidget {
  const AppShell({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return AdaptiveLayout.isWide(context)
        ? _WideShell(child: child)
        : _NarrowShell(child: child);
  }
}

int _selectedIndex(BuildContext context) {
  final location = GoRouterState.of(context).uri.path;
  final index = appNavDestinations.indexWhere(
    (d) => location.startsWith(d.route),
  );
  return index < 0 ? 0 : index;
}

class _WideShell extends StatelessWidget {
  const _WideShell({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    final selectedIndex = _selectedIndex(context);
    return Scaffold(
      body: Row(
        children: [
          NavigationRail(
            selectedIndex: selectedIndex,
            labelType: NavigationRailLabelType.all,
            destinations: appNavDestinations
                .map(
                  (d) => NavigationRailDestination(
                    icon: d.icon,
                    selectedIcon: d.selectedIcon,
                    label: Text(d.label),
                  ),
                )
                .toList(),
            onDestinationSelected: (index) =>
                context.go(appNavDestinations[index].route),
          ),
          const VerticalDivider(width: 1, thickness: 1),
          Expanded(child: child),
        ],
      ),
    );
  }
}

class _NarrowShell extends StatelessWidget {
  const _NarrowShell({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    final selectedIndex = _selectedIndex(context);
    return Scaffold(
      body: child,
      bottomNavigationBar: NavigationBar(
        selectedIndex: selectedIndex,
        destinations: appNavDestinations
            .map(
              (d) => NavigationDestination(
                icon: d.icon,
                selectedIcon: d.selectedIcon,
                label: d.label,
              ),
            )
            .toList(),
        onDestinationSelected: (index) =>
            context.go(appNavDestinations[index].route),
      ),
    );
  }
}
