import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../application/messages/messages_provider.dart';
import 'message_bubble/message_bubble.dart';

class MessageList extends ConsumerStatefulWidget {
  const MessageList({super.key, required this.channelId});

  final String channelId;

  @override
  ConsumerState<MessageList> createState() => _MessageListState();
}

class _MessageListState extends ConsumerState<MessageList> {
  final _scrollController = ScrollController();
  int _prevCount = 0;

  void _scrollToBottom({bool animated = true}) {
    if (!_scrollController.hasClients) return;
    final pos = _scrollController.position;
    if (!pos.hasContentDimensions) return;

    if (animated) {
      _scrollController.animateTo(
        pos.maxScrollExtent,
        duration: const Duration(milliseconds: 250),
        curve: Curves.easeOut,
      );
    } else {
      _scrollController.jumpTo(pos.maxScrollExtent);
    }
  }

  @override
  Widget build(BuildContext context) {
    final messagesAsync =
        ref.watch(channelMessagesProvider(widget.channelId));

    return messagesAsync.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Center(
        child: Text(
          'Failed to load messages',
          style: TextStyle(
            color: Theme.of(context).colorScheme.error,
          ),
        ),
      ),
      data: (messages) {
        // Scroll to bottom when new messages arrive.
        if (messages.length != _prevCount) {
          _prevCount = messages.length;
          WidgetsBinding.instance.addPostFrameCallback(
            (_) => _scrollToBottom(animated: _prevCount > 1),
          );
        }

        if (messages.isEmpty) {
          return Center(
            child: Text(
              'No messages yet.\nSend the first one!',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
            ),
          );
        }

        return ListView.builder(
          controller: _scrollController,
          padding:
              const EdgeInsets.symmetric(horizontal: 4, vertical: 8),
          itemCount: messages.length,
          itemBuilder: (context, index) =>
              MessageBubble(message: messages[index]),
        );
      },
    );
  }

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }
}
