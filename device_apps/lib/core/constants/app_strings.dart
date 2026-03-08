/// All user-facing strings. Use these in widgets — no hardcoded strings.
/// Will be migrated to ARB files when i18n is added.
abstract final class AppStrings {
  static const String appName = 'Private Home Box';

  // Navigation labels
  static const String navChannels = 'Channels';
  static const String navSettings = 'Settings';

  // Placeholder text (Foundation phase)
  static const String channelsPlaceholder = 'Channels — coming in Chat phase';
  static const String settingsPlaceholder = 'Settings — coming later';
  static const String onboardingPlaceholder = 'Onboarding — coming in Identity phase';

  // Common actions
  static const String retry = 'Retry';
  static const String cancel = 'Cancel';
  static const String confirm = 'Confirm';
  static const String close = 'Close';

  // Errors
  static const String errorGeneric = 'Something went wrong. Please try again.';
  static const String errorNetwork = 'Network error. Check your connection.';
  static const String errorAuth = 'Authentication failed.';
}
