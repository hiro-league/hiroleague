import 'package:drift/drift.dart';

@DataClassName('MessageRecord')
class Messages extends Table {
  TextColumn get id => text()();
  TextColumn get channelId => text()();
  TextColumn get senderId => text()();

  /// 'text' | 'image' | etc. — determines which bubble widget to render.
  TextColumn get contentType => text()();

  /// Serialized payload body. For 'text' this is the plain string.
  TextColumn get body => text()();

  /// Milliseconds since Unix epoch (UTC).
  IntColumn get timestampMs => integer()();

  /// MessageStatus enum name ('sending', 'sent', 'delivered', 'read', 'failed').
  TextColumn get status => text()();

  BoolColumn get isOutbound =>
      boolean().withDefault(const Constant(false))();

  /// JSON-encoded metadata for non-text content.
  /// Audio: {"duration_ms": int, "mime_type": str, "local_path": str?, "transcript": str?}
  TextColumn get metadata => text().nullable()();

  @override
  Set<Column> get primaryKey => {id};
}
