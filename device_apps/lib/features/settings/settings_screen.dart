import 'package:flutter/material.dart';

import '../../core/constants/app_strings.dart';

// Placeholder — full implementation in Settings phase.
class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text(AppStrings.navSettings)),
      body: Center(
        child: Text(
          AppStrings.settingsPlaceholder,
          style: Theme.of(context).textTheme.bodyLarge,
        ),
      ),
    );
  }
}
