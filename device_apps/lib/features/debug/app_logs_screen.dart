import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:talker_flutter/talker_flutter.dart';

import '../../core/constants/app_strings.dart';
import '../../core/logging/app_talker.dart';

/// In-app view of [appTalker] history (errors, framework failures, app [Logger] lines).
class AppLogsScreen extends StatelessWidget {
  const AppLogsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return TalkerScreen(
      talker: appTalker,
      appBarTitle: AppStrings.navAppLogs,
      theme: TalkerScreenTheme.fromTheme(theme),
      appBarLeading: IconButton(
        icon: const Icon(Icons.arrow_back_rounded),
        onPressed: () => context.pop(),
      ),
    );
  }
}
