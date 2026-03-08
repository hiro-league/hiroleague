import 'package:flutter/material.dart';

abstract final class AppColors {
  // Brand palette — deep teal primary, warm accent
  static const Color primary = Color(0xFF00697A);
  static const Color primaryContainer = Color(0xFFAEECF8);
  static const Color onPrimary = Color(0xFFFFFFFF);
  static const Color onPrimaryContainer = Color(0xFF001F25);

  static const Color secondary = Color(0xFF4B6269);
  static const Color secondaryContainer = Color(0xFFCEE7EF);
  static const Color onSecondary = Color(0xFFFFFFFF);
  static const Color onSecondaryContainer = Color(0xFF051F25);

  static const Color tertiary = Color(0xFF545D7E);
  static const Color tertiaryContainer = Color(0xFFDBE1FF);
  static const Color onTertiary = Color(0xFFFFFFFF);
  static const Color onTertiaryContainer = Color(0xFF111A38);

  static const Color error = Color(0xFFBA1A1A);
  static const Color errorContainer = Color(0xFFFFDAD6);

  // Message bubbles
  static const Color outboundBubble = Color(0xFF00697A);
  static const Color inboundBubble = Color(0xFFE8F4F6);
  static const Color outboundBubbleDark = Color(0xFF004F5E);
  static const Color inboundBubbleDark = Color(0xFF1E3035);

  // Status indicators
  static const Color statusOnline = Color(0xFF4CAF50);
  static const Color statusOffline = Color(0xFF9E9E9E);
  static const Color statusWarning = Color(0xFFFFC107);
}
