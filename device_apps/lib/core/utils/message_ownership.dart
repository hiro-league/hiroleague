/// Conversation-side ownership rules for the single-user chat model.
///
/// Server-originated messages render on the other side. Any device-originated
/// user message renders on the user's side, regardless of which paired device
/// produced it.
library;

const String serverSenderId = 'server';
const String userSenderType = 'user';
const String agentSenderType = 'agent';

bool isUserSideSenderId(String? senderId) {
  final normalized = senderId?.trim();
  return normalized != null &&
      normalized.isNotEmpty &&
      normalized != serverSenderId;
}

bool isUserSideHistoryMessage({
  required String? senderType,
  required String? senderId,
}) {
  final normalizedType = senderType?.trim();
  if (normalizedType == userSenderType) return true;
  if (normalizedType == agentSenderType) return false;
  return isUserSideSenderId(senderId);
}
