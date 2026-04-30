import 'package:device_apps/core/config/hiro_environment.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('defaults to production', () {
    final config = HiroEnvironmentConfig.fromValues(hiroEnv: 'prod');

    expect(config.hiroEnv, 'prod');
    expect(config.isProd, isTrue);
    expect(config.isDev, isFalse);
  });

  test('dev environment is detected', () {
    final config = HiroEnvironmentConfig.fromValues(hiroEnv: 'dev');

    expect(config.hiroEnv, 'dev');
    expect(config.isDev, isTrue);
    expect(config.isProd, isFalse);
  });

  test('development aliases are treated as dev', () {
    final config = HiroEnvironmentConfig.fromValues(hiroEnv: 'local');

    expect(config.hiroEnv, 'dev');
  });
}
