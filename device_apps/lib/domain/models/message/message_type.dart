/// Payload content type tag — used for routing to the right bubble widget.
/// Only [text] is implemented in the Chat phase; others are stubs for future phases.
enum MessageType {
  text,
  image,
  video,
  voice,
  location,
  file;

  static MessageType fromString(String value) =>
      MessageType.values.firstWhere(
        (t) => t.name == value,
        orElse: () => MessageType.text,
      );
}
