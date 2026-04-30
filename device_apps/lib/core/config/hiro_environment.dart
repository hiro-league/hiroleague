enum HiroEnvironment {
  dev,
  prod,
  custom;

  static HiroEnvironment parse(String value) {
    final normalized = value.trim().toLowerCase();
    if (normalized == 'dev' ||
        normalized == 'development' ||
        normalized == 'local') {
      return HiroEnvironment.dev;
    }
    if (normalized.isEmpty ||
        normalized == 'prod' ||
        normalized == 'production') {
      return HiroEnvironment.prod;
    }
    return HiroEnvironment.custom;
  }
}

class HiroEnvironmentConfig {
  const HiroEnvironmentConfig({required this.hiroEnv});

  static const rawHiroEnv = String.fromEnvironment(
    'HIRO_ENV',
    defaultValue: 'prod',
  );

  static final current = HiroEnvironmentConfig.fromValues(hiroEnv: rawHiroEnv);

  final String hiroEnv;

  bool get isDev => hiroEnv == 'dev';

  bool get isProd => hiroEnv == 'prod';

  factory HiroEnvironmentConfig.fromValues({required String hiroEnv}) {
    final normalizedEnv = HiroEnvironment.parse(hiroEnv);
    return HiroEnvironmentConfig(
      hiroEnv: normalizedEnv == HiroEnvironment.dev
          ? 'dev'
          : normalizedEnv == HiroEnvironment.prod
          ? 'prod'
          : hiroEnv.trim().toLowerCase(),
    );
  }
}
