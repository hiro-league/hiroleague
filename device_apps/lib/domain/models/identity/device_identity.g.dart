// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'device_identity.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$DeviceIdentityImpl _$$DeviceIdentityImplFromJson(Map<String, dynamic> json) =>
    _$DeviceIdentityImpl(
      deviceId: json['device_id'] as String,
      seedBase64: json['seed_base64'] as String,
      publicKeyBase64: json['public_key_base64'] as String,
      gatewayUrl: json['gateway_url'] as String,
      attestation: json['attestation'] == null
          ? null
          : DeviceAttestation.fromJson(
              json['attestation'] as Map<String, dynamic>,
            ),
      desktopDeviceId: json['desktop_device_id'] as String?,
    );

Map<String, dynamic> _$$DeviceIdentityImplToJson(
  _$DeviceIdentityImpl instance,
) => <String, dynamic>{
  'device_id': instance.deviceId,
  'seed_base64': instance.seedBase64,
  'public_key_base64': instance.publicKeyBase64,
  'gateway_url': instance.gatewayUrl,
  'attestation': instance.attestation,
  'desktop_device_id': instance.desktopDeviceId,
};
