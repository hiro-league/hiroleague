import 'package:flex_color_scheme/flex_color_scheme.dart';
import 'package:flutter/material.dart';

import 'app_colors.dart';

abstract final class AppTheme {
  static const _colors = FlexSchemeColor(
    primary: AppColors.primary,
    primaryContainer: AppColors.primaryContainer,
    secondary: AppColors.secondary,
    secondaryContainer: AppColors.secondaryContainer,
    tertiary: AppColors.tertiary,
    tertiaryContainer: AppColors.tertiaryContainer,
    error: AppColors.error,
    errorContainer: AppColors.errorContainer,
  );

  static const _subThemes = FlexSubThemesData(
    blendOnLevel: 10,
    useM2StyleDividerInM3: true,
    navigationBarSelectedLabelSchemeColor: SchemeColor.primary,
    navigationBarUnselectedLabelSchemeColor: SchemeColor.onSurfaceVariant,
    navigationBarSelectedIconSchemeColor: SchemeColor.primary,
    navigationBarIndicatorSchemeColor: SchemeColor.primaryContainer,
    navigationRailSelectedLabelSchemeColor: SchemeColor.primary,
    navigationRailUnselectedLabelSchemeColor: SchemeColor.onSurfaceVariant,
    navigationRailSelectedIconSchemeColor: SchemeColor.primary,
    navigationRailIndicatorSchemeColor: SchemeColor.primaryContainer,
  );

  static ThemeData get light => FlexThemeData.light(
        colors: _colors,
        surfaceMode: FlexSurfaceMode.levelSurfacesLowScaffold,
        blendLevel: 7,
        subThemesData: _subThemes,
        useMaterial3: true,
      );

  static ThemeData get dark => FlexThemeData.dark(
        colors: _colors,
        surfaceMode: FlexSurfaceMode.levelSurfacesLowScaffold,
        blendLevel: 13,
        subThemesData: _subThemes.copyWith(blendOnLevel: 20),
        useMaterial3: true,
      );
}
