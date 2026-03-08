import 'dart:math';

/// Exponential backoff policy for gateway reconnect attempts.
class ReconnectPolicy {
  const ReconnectPolicy({
    this.initialDelay = const Duration(seconds: 2),
    this.maxDelay = const Duration(seconds: 30),
    this.multiplier = 2.0,
  });

  final Duration initialDelay;
  final Duration maxDelay;
  final double multiplier;

  /// Returns the delay before attempt [n] (0-indexed).
  Duration delayFor(int attempt) {
    if (attempt <= 0) return initialDelay;
    final ms = initialDelay.inMilliseconds * pow(multiplier, attempt);
    return Duration(milliseconds: min(ms.round(), maxDelay.inMilliseconds));
  }
}
