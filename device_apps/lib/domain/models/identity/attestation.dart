import 'package:freezed_annotation/freezed_annotation.dart';

part 'attestation.freezed.dart';
part 'attestation.g.dart';

@freezed
class DeviceAttestation with _$DeviceAttestation {
  // fieldRename: snake maps desktopSignature → desktop_signature (matches server protocol).
  @JsonSerializable(fieldRename: FieldRename.snake)
  const factory DeviceAttestation({
    required String blob,
    required String desktopSignature,
  }) = _DeviceAttestation;

  factory DeviceAttestation.fromJson(Map<String, dynamic> json) =>
      _$DeviceAttestationFromJson(json);
}
