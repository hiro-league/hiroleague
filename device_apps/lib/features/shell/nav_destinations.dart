import 'package:flutter/material.dart';

import '../../core/constants/app_strings.dart';
import '../../core/constants/route_names.dart';

class NavDestination {
  const NavDestination({
    required this.label,
    required this.icon,
    required this.selectedIcon,
    required this.route,
  });

  final String label;
  final Widget icon;
  final Widget selectedIcon;
  final String route;
}

const List<NavDestination> appNavDestinations = [
  NavDestination(
    label: AppStrings.navChannels,
    icon: Icon(Icons.chat_bubble_outline),
    selectedIcon: Icon(Icons.chat_bubble),
    route: RouteNames.channels,
  ),
  NavDestination(
    label: AppStrings.navSettings,
    icon: Icon(Icons.settings_outlined),
    selectedIcon: Icon(Icons.settings),
    route: RouteNames.settings,
  ),
];
