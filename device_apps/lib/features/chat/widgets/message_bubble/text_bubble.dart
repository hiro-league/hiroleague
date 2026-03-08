import 'package:flutter/material.dart';

import '../../../../core/ui/theme/app_text_styles.dart';
import '../../../../domain/models/message/message.dart';
import '../../../../domain/models/message/message_content.dart';

class TextBubble extends StatelessWidget {
  const TextBubble({
    super.key,
    required this.message,
    required this.content,
  });

  final Message message;
  final TextContent content;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final isOut = message.isOutbound;

    final bubbleColor = isOut ? cs.primary : cs.surfaceContainerHigh;
    final textColor = isOut ? cs.onPrimary : cs.onSurface;
    final metaColor =
        isOut ? cs.onPrimary.withValues(alpha: 0.7) : cs.onSurfaceVariant;

    return Align(
      alignment: isOut ? Alignment.centerRight : Alignment.centerLeft,
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxWidth: MediaQuery.sizeOf(context).width * 0.75,
        ),
        child: Container(
          margin: EdgeInsets.only(
            left: isOut ? 56 : 8,
            right: isOut ? 8 : 56,
            top: 2,
            bottom: 2,
          ),
          padding:
              const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          decoration: BoxDecoration(
            color: bubbleColor,
            borderRadius: BorderRadius.only(
              topLeft: const Radius.circular(18),
              topRight: const Radius.circular(18),
              bottomLeft: Radius.circular(isOut ? 18 : 4),
              bottomRight: Radius.circular(isOut ? 4 : 18),
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              if (!isOut) ...[
                Text(
                  _shortId(message.senderId),
                  style: AppTextStyles.messageTimestamp.copyWith(
                    color: cs.primary,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 2),
              ],
              Text(
                content.text,
                style: AppTextStyles.messageBody.copyWith(color: textColor),
              ),
              const SizedBox(height: 4),
              Align(
                alignment: Alignment.bottomRight,
                child: Text(
                  _formatTime(message.timestamp),
                  style: AppTextStyles.messageTimestamp
                      .copyWith(color: metaColor),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  /// Show the last 8 chars of the device-id as the sender label.
  String _shortId(String id) {
    if (id.length <= 8) return id;
    return '…${id.substring(id.length - 8)}';
  }

  String _formatTime(DateTime dt) {
    final local = dt.toLocal();
    final h = local.hour.toString().padLeft(2, '0');
    final m = local.minute.toString().padLeft(2, '0');
    return '$h:$m';
  }
}
