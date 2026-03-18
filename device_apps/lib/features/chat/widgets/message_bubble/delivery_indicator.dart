import 'package:flutter/material.dart';

import '../../../../domain/models/message/message_status.dart';

/// WhatsApp-style delivery status indicator shown on outbound message bubbles.
///
/// | Status    | Icon          | Color          |
/// |-----------|---------------|----------------|
/// | sending   | clock outline | gray           |
/// | sent      | single check  | gray           |
/// | delivered | double check  | gray           |
/// | read      | double check  | primary (blue) |
/// | failed    | error outline | error          |
class DeliveryIndicator extends StatelessWidget {
  const DeliveryIndicator({
    super.key,
    required this.status,
    this.readColor,
    this.defaultColor,
  });

  final MessageStatus status;

  /// Color for the double-check when status is [MessageStatus.read].
  /// Defaults to [ColorScheme.primary].
  final Color? readColor;

  /// Color for all other check states. Defaults to a medium-gray.
  final Color? defaultColor;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final gray = defaultColor ?? cs.onSurface.withValues(alpha: 0.45);
    final blue = readColor ?? cs.primary;

    return switch (status) {
      MessageStatus.sending => Icon(Icons.access_time_rounded, size: 13, color: gray),
      MessageStatus.sent => Icon(Icons.check_rounded, size: 13, color: gray),
      MessageStatus.delivered => _DoubleCheck(color: gray),
      MessageStatus.read => _DoubleCheck(color: blue),
      MessageStatus.failed => Icon(Icons.error_outline_rounded, size: 13, color: cs.error),
    };
  }
}

/// Two overlapping check marks — mimics the WhatsApp double-tick.
class _DoubleCheck extends StatelessWidget {
  const _DoubleCheck({required this.color});

  final Color color;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 20,
      height: 13,
      child: Stack(
        children: [
          Positioned(
            left: 0,
            child: Icon(Icons.check_rounded, size: 13, color: color),
          ),
          Positioned(
            left: 6,
            child: Icon(Icons.check_rounded, size: 13, color: color),
          ),
        ],
      ),
    );
  }
}
