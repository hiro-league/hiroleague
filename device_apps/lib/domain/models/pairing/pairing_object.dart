import 'package:freezed_annotation/freezed_annotation.dart';

part 'pairing_object.freezed.dart';
part 'pairing_object.g.dart';

/// Pairing invitation object emitted by the gateway CLI.
/// JSON shape: {"gateway_url":"ws://...","code":"123456","expires_at":"...Z"}
@freezed
abstract class PairingObject with _$PairingObject {
  @JsonSerializable(fieldRename: FieldRename.snake)
  const factory PairingObject({
    required String gatewayUrl,
    required String code,
    required DateTime expiresAt,
  }) = _PairingObject;

  factory PairingObject.fromJson(Map<String, dynamic> json) =>
      _$PairingObjectFromJson(json);
}
