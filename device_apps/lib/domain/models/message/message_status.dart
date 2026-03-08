enum MessageStatus {
  sending,
  sent,
  delivered,
  read,
  failed;

  static MessageStatus fromName(String name) =>
      MessageStatus.values.firstWhere(
        (s) => s.name == name,
        orElse: () => MessageStatus.sent,
      );
}
