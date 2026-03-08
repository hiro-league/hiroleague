import 'package:flutter/widgets.dart';

import '../constants/app_constants.dart';

/// Single source of truth for layout breakpoints.
/// Always use this instead of inline MediaQuery width checks.
abstract final class AdaptiveLayout {
  /// Wide layout: tablet, desktop, web (NavigationRail + split panel).
  /// Narrow layout: mobile (NavigationBar + stacked navigation).
  static bool isWide(BuildContext context) =>
      MediaQuery.sizeOf(context).width >= AppConstants.wideLayoutBreakpoint;
}
