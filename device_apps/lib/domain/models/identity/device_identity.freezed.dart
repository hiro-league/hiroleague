// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'device_identity.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

T _$identity<T>(T value) => value;

final _privateConstructorUsedError = UnsupportedError(
  'It seems like you constructed your class using `MyClass._()`. This constructor is only meant to be used by freezed and you are not supposed to need it nor use it.\nPlease check the documentation here for more information: https://github.com/rrousselGit/freezed#adding-getters-and-methods-to-our-models',
);

DeviceIdentity _$DeviceIdentityFromJson(Map<String, dynamic> json) {
  return _DeviceIdentity.fromJson(json);
}

/// @nodoc
mixin _$DeviceIdentity {
  String get deviceId => throw _privateConstructorUsedError;
  String get seedBase64 => throw _privateConstructorUsedError;
  String get publicKeyBase64 => throw _privateConstructorUsedError;
  String get gatewayUrl =>
      throw _privateConstructorUsedError; // Null until the device completes pairing.
  DeviceAttestation? get attestation =>
      throw _privateConstructorUsedError; // Set by the server on pairing approval; may be null if not provided.
  String? get desktopDeviceId => throw _privateConstructorUsedError;

  /// Serializes this DeviceIdentity to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of DeviceIdentity
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $DeviceIdentityCopyWith<DeviceIdentity> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $DeviceIdentityCopyWith<$Res> {
  factory $DeviceIdentityCopyWith(
    DeviceIdentity value,
    $Res Function(DeviceIdentity) then,
  ) = _$DeviceIdentityCopyWithImpl<$Res, DeviceIdentity>;
  @useResult
  $Res call({
    String deviceId,
    String seedBase64,
    String publicKeyBase64,
    String gatewayUrl,
    DeviceAttestation? attestation,
    String? desktopDeviceId,
  });

  $DeviceAttestationCopyWith<$Res>? get attestation;
}

/// @nodoc
class _$DeviceIdentityCopyWithImpl<$Res, $Val extends DeviceIdentity>
    implements $DeviceIdentityCopyWith<$Res> {
  _$DeviceIdentityCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of DeviceIdentity
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? deviceId = null,
    Object? seedBase64 = null,
    Object? publicKeyBase64 = null,
    Object? gatewayUrl = null,
    Object? attestation = freezed,
    Object? desktopDeviceId = freezed,
  }) {
    return _then(
      _value.copyWith(
            deviceId: null == deviceId
                ? _value.deviceId
                : deviceId // ignore: cast_nullable_to_non_nullable
                      as String,
            seedBase64: null == seedBase64
                ? _value.seedBase64
                : seedBase64 // ignore: cast_nullable_to_non_nullable
                      as String,
            publicKeyBase64: null == publicKeyBase64
                ? _value.publicKeyBase64
                : publicKeyBase64 // ignore: cast_nullable_to_non_nullable
                      as String,
            gatewayUrl: null == gatewayUrl
                ? _value.gatewayUrl
                : gatewayUrl // ignore: cast_nullable_to_non_nullable
                      as String,
            attestation: freezed == attestation
                ? _value.attestation
                : attestation // ignore: cast_nullable_to_non_nullable
                      as DeviceAttestation?,
            desktopDeviceId: freezed == desktopDeviceId
                ? _value.desktopDeviceId
                : desktopDeviceId // ignore: cast_nullable_to_non_nullable
                      as String?,
          )
          as $Val,
    );
  }

  /// Create a copy of DeviceIdentity
  /// with the given fields replaced by the non-null parameter values.
  @override
  @pragma('vm:prefer-inline')
  $DeviceAttestationCopyWith<$Res>? get attestation {
    if (_value.attestation == null) {
      return null;
    }

    return $DeviceAttestationCopyWith<$Res>(_value.attestation!, (value) {
      return _then(_value.copyWith(attestation: value) as $Val);
    });
  }
}

/// @nodoc
abstract class _$$DeviceIdentityImplCopyWith<$Res>
    implements $DeviceIdentityCopyWith<$Res> {
  factory _$$DeviceIdentityImplCopyWith(
    _$DeviceIdentityImpl value,
    $Res Function(_$DeviceIdentityImpl) then,
  ) = __$$DeviceIdentityImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({
    String deviceId,
    String seedBase64,
    String publicKeyBase64,
    String gatewayUrl,
    DeviceAttestation? attestation,
    String? desktopDeviceId,
  });

  @override
  $DeviceAttestationCopyWith<$Res>? get attestation;
}

/// @nodoc
class __$$DeviceIdentityImplCopyWithImpl<$Res>
    extends _$DeviceIdentityCopyWithImpl<$Res, _$DeviceIdentityImpl>
    implements _$$DeviceIdentityImplCopyWith<$Res> {
  __$$DeviceIdentityImplCopyWithImpl(
    _$DeviceIdentityImpl _value,
    $Res Function(_$DeviceIdentityImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of DeviceIdentity
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? deviceId = null,
    Object? seedBase64 = null,
    Object? publicKeyBase64 = null,
    Object? gatewayUrl = null,
    Object? attestation = freezed,
    Object? desktopDeviceId = freezed,
  }) {
    return _then(
      _$DeviceIdentityImpl(
        deviceId: null == deviceId
            ? _value.deviceId
            : deviceId // ignore: cast_nullable_to_non_nullable
                  as String,
        seedBase64: null == seedBase64
            ? _value.seedBase64
            : seedBase64 // ignore: cast_nullable_to_non_nullable
                  as String,
        publicKeyBase64: null == publicKeyBase64
            ? _value.publicKeyBase64
            : publicKeyBase64 // ignore: cast_nullable_to_non_nullable
                  as String,
        gatewayUrl: null == gatewayUrl
            ? _value.gatewayUrl
            : gatewayUrl // ignore: cast_nullable_to_non_nullable
                  as String,
        attestation: freezed == attestation
            ? _value.attestation
            : attestation // ignore: cast_nullable_to_non_nullable
                  as DeviceAttestation?,
        desktopDeviceId: freezed == desktopDeviceId
            ? _value.desktopDeviceId
            : desktopDeviceId // ignore: cast_nullable_to_non_nullable
                  as String?,
      ),
    );
  }
}

/// @nodoc

@JsonSerializable(fieldRename: FieldRename.snake)
class _$DeviceIdentityImpl implements _DeviceIdentity {
  const _$DeviceIdentityImpl({
    required this.deviceId,
    required this.seedBase64,
    required this.publicKeyBase64,
    required this.gatewayUrl,
    this.attestation,
    this.desktopDeviceId,
  });

  factory _$DeviceIdentityImpl.fromJson(Map<String, dynamic> json) =>
      _$$DeviceIdentityImplFromJson(json);

  @override
  final String deviceId;
  @override
  final String seedBase64;
  @override
  final String publicKeyBase64;
  @override
  final String gatewayUrl;
  // Null until the device completes pairing.
  @override
  final DeviceAttestation? attestation;
  // Set by the server on pairing approval; may be null if not provided.
  @override
  final String? desktopDeviceId;

  @override
  String toString() {
    return 'DeviceIdentity(deviceId: $deviceId, seedBase64: $seedBase64, publicKeyBase64: $publicKeyBase64, gatewayUrl: $gatewayUrl, attestation: $attestation, desktopDeviceId: $desktopDeviceId)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$DeviceIdentityImpl &&
            (identical(other.deviceId, deviceId) ||
                other.deviceId == deviceId) &&
            (identical(other.seedBase64, seedBase64) ||
                other.seedBase64 == seedBase64) &&
            (identical(other.publicKeyBase64, publicKeyBase64) ||
                other.publicKeyBase64 == publicKeyBase64) &&
            (identical(other.gatewayUrl, gatewayUrl) ||
                other.gatewayUrl == gatewayUrl) &&
            (identical(other.attestation, attestation) ||
                other.attestation == attestation) &&
            (identical(other.desktopDeviceId, desktopDeviceId) ||
                other.desktopDeviceId == desktopDeviceId));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
    runtimeType,
    deviceId,
    seedBase64,
    publicKeyBase64,
    gatewayUrl,
    attestation,
    desktopDeviceId,
  );

  /// Create a copy of DeviceIdentity
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$DeviceIdentityImplCopyWith<_$DeviceIdentityImpl> get copyWith =>
      __$$DeviceIdentityImplCopyWithImpl<_$DeviceIdentityImpl>(
        this,
        _$identity,
      );

  @override
  Map<String, dynamic> toJson() {
    return _$$DeviceIdentityImplToJson(this);
  }
}

abstract class _DeviceIdentity implements DeviceIdentity {
  const factory _DeviceIdentity({
    required final String deviceId,
    required final String seedBase64,
    required final String publicKeyBase64,
    required final String gatewayUrl,
    final DeviceAttestation? attestation,
    final String? desktopDeviceId,
  }) = _$DeviceIdentityImpl;

  factory _DeviceIdentity.fromJson(Map<String, dynamic> json) =
      _$DeviceIdentityImpl.fromJson;

  @override
  String get deviceId;
  @override
  String get seedBase64;
  @override
  String get publicKeyBase64;
  @override
  String get gatewayUrl; // Null until the device completes pairing.
  @override
  DeviceAttestation? get attestation; // Set by the server on pairing approval; may be null if not provided.
  @override
  String? get desktopDeviceId;

  /// Create a copy of DeviceIdentity
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$DeviceIdentityImplCopyWith<_$DeviceIdentityImpl> get copyWith =>
      throw _privateConstructorUsedError;
}
