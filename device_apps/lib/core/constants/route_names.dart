abstract final class RouteNames {
  static const String root = '/';
  static const String onboarding = '/onboarding';
  // Nested under /onboarding — inherits the auth guard's onboarding branch.
  static const String qrScan = '/onboarding/scan';
  static const String channels = '/app/channels';
  static const String chat = '/app/channels/:channelId';
  static String chatChannelSettings(String channelId) =>
      '/app/channels/$channelId/settings';
  static String chatChannelInfo(String channelId) =>
      '/app/channels/$channelId/info';

  static const String settings = '/app/settings';
  static const String appLogs = '/app/logs';
}
