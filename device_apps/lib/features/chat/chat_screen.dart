import 'package:flutter/material.dart';

import 'chat_app_bar.dart';
import 'widgets/input_bar/message_input_bar.dart';
import 'widgets/message_list.dart';

class ChatScreen extends StatelessWidget {
  const ChatScreen({super.key, required this.channelId});

  final String channelId;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: ChatAppBar(channelId: channelId),
      body: Column(
        children: [
          Expanded(
            child: MessageList(channelId: channelId),
          ),
          MessageInputBar(channelId: channelId),
        ],
      ),
    );
  }
}
