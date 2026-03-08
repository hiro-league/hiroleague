// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'attestation.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$DeviceAttestationImpl _$$DeviceAttestationImplFromJson(
  Map<String, dynamic> json,
) => _$DeviceAttestationImpl(
  blob: json['blob'] as String,
  desktopSignature: json['desktop_signature'] as String,
);

Map<String, dynamic> _$$DeviceAttestationImplToJson(
  _$DeviceAttestationImpl instance,
) => <String, dynamic>{
  'blob': instance.blob,
  'desktop_signature': instance.desktopSignature,
};
