import 'package:flame/game.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../application/gateway/gateway_notifier.dart';
import '../experiments/dot_matrix/dot_matrix_game.dart';
import 'chat_app_bar.dart';
import 'widgets/input_bar/message_input_bar.dart';
import 'widgets/message_list.dart';

class ChatScreen extends ConsumerStatefulWidget {
  const ChatScreen({super.key, required this.channelId});

  final String channelId;

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  // Created in State (not static) so hot restart always picks up the latest
  // DotMatrixGame constructor, including any config changes made in code.
  late final DotMatrixGame _dotMatrixGame = DotMatrixGame();

  // Dot-matrix panel starts collapsed; user can reveal it with the arrow.
  bool _flameExpanded = false;

  void _toggleFlame() => setState(() => _flameExpanded = !_flameExpanded);

  @override
  void initState() {
    super.initState();
    // Same stale-while-revalidate hook as channel list — capabilities/policy may have changed while away.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(gatewayProvider.notifier).revalidateResourcesIfStale(
            const ['channels', 'policy'],
          );
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: ChatAppBar(channelId: widget.channelId),
      body: Column(
        children: [
          // --- Dot matrix panel: collapsible ---
          AnimatedSize(
            duration: const Duration(milliseconds: 300),
            curve: Curves.easeInOut,
            child: _flameExpanded
                ? SizedBox(
                    height: MediaQuery.sizeOf(context).height * 0.28,
                    child: ClipRect(child: GameWidget(game: _dotMatrixGame)),
                  )
                : const SizedBox.shrink(),
          ),
          // Arrow toggle button
          GestureDetector(
            onTap: _toggleFlame,
            child: Container(
              width: double.infinity,
              alignment: Alignment.center,
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: AnimatedRotation(
                turns: _flameExpanded ? 0.5 : 0.0,
                duration: const Duration(milliseconds: 300),
                child: const Icon(Icons.keyboard_arrow_down_rounded, size: 20),
              ),
            ),
          ),
          // --- Message list ---
          Expanded(
            child: MessageList(channelId: widget.channelId),
          ),
          MessageInputBar(channelId: widget.channelId),
        ],
      ),
    );
  }
}
