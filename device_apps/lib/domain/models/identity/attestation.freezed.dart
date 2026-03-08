// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'attestation.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

T _$identity<T>(T value) => value;

final _privateConstructorUsedError = UnsupportedError(
  'It seems like you constructed your class using `MyClass._()`. This constructor is only meant to be used by freezed and you are not supposed to need it nor use it.\nPlease check the documentation here for more information: https://github.com/rrousselGit/freezed#adding-getters-and-methods-to-our-models',
);

DeviceAttestation _$DeviceAttestationFromJson(Map<String, dynamic> json) {
  return _DeviceAttestation.fromJson(json);
}

/// @nodoc
mixin _$DeviceAttestation {
  String get blob => throw _privateConstructorUsedError;
  String get desktopSignature => throw _privateConstructorUsedError;

  /// Serializes this DeviceAttestation to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of DeviceAttestation
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $DeviceAttestationCopyWith<DeviceAttestation> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $DeviceAttestationCopyWith<$Res> {
  factory $DeviceAttestationCopyWith(
    DeviceAttestation value,
    $Res Function(DeviceAttestation) then,
  ) = _$DeviceAttestationCopyWithImpl<$Res, DeviceAttestation>;
  @useResult
  $Res call({String blob, String desktopSignature});
}

/// @nodoc
class _$DeviceAttestationCopyWithImpl<$Res, $Val extends DeviceAttestation>
    implements $DeviceAttestationCopyWith<$Res> {
  _$DeviceAttestationCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of DeviceAttestation
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? blob = null, Object? desktopSignature = null}) {
    return _then(
      _value.copyWith(
            blob: null == blob
                ? _value.blob
                : blob // ignore: cast_nullable_to_non_nullable
                      as String,
            desktopSignature: null == desktopSignature
                ? _value.desktopSignature
                : desktopSignature // ignore: cast_nullable_to_non_nullable
                      as String,
          )
          as $Val,
    );
  }
}

/// @nodoc
abstract class _$$DeviceAttestationImplCopyWith<$Res>
    implements $DeviceAttestationCopyWith<$Res> {
  factory _$$DeviceAttestationImplCopyWith(
    _$DeviceAttestationImpl value,
    $Res Function(_$DeviceAttestationImpl) then,
  ) = __$$DeviceAttestationImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({String blob, String desktopSignature});
}

/// @nodoc
class __$$DeviceAttestationImplCopyWithImpl<$Res>
    extends _$DeviceAttestationCopyWithImpl<$Res, _$DeviceAttestationImpl>
    implements _$$DeviceAttestationImplCopyWith<$Res> {
  __$$DeviceAttestationImplCopyWithImpl(
    _$DeviceAttestationImpl _value,
    $Res Function(_$DeviceAttestationImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of DeviceAttestation
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? blob = null, Object? desktopSignature = null}) {
    return _then(
      _$DeviceAttestationImpl(
        blob: null == blob
            ? _value.blob
            : blob // ignore: cast_nullable_to_non_nullable
                  as String,
        desktopSignature: null == desktopSignature
            ? _value.desktopSignature
            : desktopSignature // ignore: cast_nullable_to_non_nullable
                  as String,
      ),
    );
  }
}

/// @nodoc

@JsonSerializable(fieldRename: FieldRename.snake)
class _$DeviceAttestationImpl implements _DeviceAttestation {
  const _$DeviceAttestationImpl({
    required this.blob,
    required this.desktopSignature,
  });

  factory _$DeviceAttestationImpl.fromJson(Map<String, dynamic> json) =>
      _$$DeviceAttestationImplFromJson(json);

  @override
  final String blob;
  @override
  final String desktopSignature;

  @override
  String toString() {
    return 'DeviceAttestation(blob: $blob, desktopSignature: $desktopSignature)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$DeviceAttestationImpl &&
            (identical(other.blob, blob) || other.blob == blob) &&
            (identical(other.desktopSignature, desktopSignature) ||
                other.desktopSignature == desktopSignature));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, blob, desktopSignature);

  /// Create a copy of DeviceAttestation
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$DeviceAttestationImplCopyWith<_$DeviceAttestationImpl> get copyWith =>
      __$$DeviceAttestationImplCopyWithImpl<_$DeviceAttestationImpl>(
        this,
        _$identity,
      );

  @override
  Map<String, dynamic> toJson() {
    return _$$DeviceAttestationImplToJson(this);
  }
}

abstract class _DeviceAttestation implements DeviceAttestation {
  const factory _DeviceAttestation({
    required final String blob,
    required final String desktopSignature,
  }) = _$DeviceAttestationImpl;

  factory _DeviceAttestation.fromJson(Map<String, dynamic> json) =
      _$DeviceAttestationImpl.fromJson;

  @override
  String get blob;
  @override
  String get desktopSignature;

  /// Create a copy of DeviceAttestation
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$DeviceAttestationImplCopyWith<_$DeviceAttestationImpl> get copyWith =>
      throw _privateConstructorUsedError;
}
