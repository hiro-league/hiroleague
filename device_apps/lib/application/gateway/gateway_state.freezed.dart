// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'gateway_state.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

T _$identity<T>(T value) => value;

final _privateConstructorUsedError = UnsupportedError(
  'It seems like you constructed your class using `MyClass._()`. This constructor is only meant to be used by freezed and you are not supposed to need it nor use it.\nPlease check the documentation here for more information: https://github.com/rrousselGit/freezed#adding-getters-and-methods-to-our-models',
);

/// @nodoc
mixin _$GatewayState {
  @optionalTypeArgs
  TResult when<TResult extends Object?>({
    required TResult Function() disconnected,
    required TResult Function() connecting,
    required TResult Function(String deviceId) connected,
    required TResult Function(String message) error,
  }) => throw _privateConstructorUsedError;
  @optionalTypeArgs
  TResult? whenOrNull<TResult extends Object?>({
    TResult? Function()? disconnected,
    TResult? Function()? connecting,
    TResult? Function(String deviceId)? connected,
    TResult? Function(String message)? error,
  }) => throw _privateConstructorUsedError;
  @optionalTypeArgs
  TResult maybeWhen<TResult extends Object?>({
    TResult Function()? disconnected,
    TResult Function()? connecting,
    TResult Function(String deviceId)? connected,
    TResult Function(String message)? error,
    required TResult orElse(),
  }) => throw _privateConstructorUsedError;
  @optionalTypeArgs
  TResult map<TResult extends Object?>({
    required TResult Function(GatewayDisconnected value) disconnected,
    required TResult Function(GatewayConnecting value) connecting,
    required TResult Function(GatewayConnected value) connected,
    required TResult Function(GatewayError value) error,
  }) => throw _privateConstructorUsedError;
  @optionalTypeArgs
  TResult? mapOrNull<TResult extends Object?>({
    TResult? Function(GatewayDisconnected value)? disconnected,
    TResult? Function(GatewayConnecting value)? connecting,
    TResult? Function(GatewayConnected value)? connected,
    TResult? Function(GatewayError value)? error,
  }) => throw _privateConstructorUsedError;
  @optionalTypeArgs
  TResult maybeMap<TResult extends Object?>({
    TResult Function(GatewayDisconnected value)? disconnected,
    TResult Function(GatewayConnecting value)? connecting,
    TResult Function(GatewayConnected value)? connected,
    TResult Function(GatewayError value)? error,
    required TResult orElse(),
  }) => throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $GatewayStateCopyWith<$Res> {
  factory $GatewayStateCopyWith(
    GatewayState value,
    $Res Function(GatewayState) then,
  ) = _$GatewayStateCopyWithImpl<$Res, GatewayState>;
}

/// @nodoc
class _$GatewayStateCopyWithImpl<$Res, $Val extends GatewayState>
    implements $GatewayStateCopyWith<$Res> {
  _$GatewayStateCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of GatewayState
  /// with the given fields replaced by the non-null parameter values.
}

/// @nodoc
abstract class _$$GatewayDisconnectedImplCopyWith<$Res> {
  factory _$$GatewayDisconnectedImplCopyWith(
    _$GatewayDisconnectedImpl value,
    $Res Function(_$GatewayDisconnectedImpl) then,
  ) = __$$GatewayDisconnectedImplCopyWithImpl<$Res>;
}

/// @nodoc
class __$$GatewayDisconnectedImplCopyWithImpl<$Res>
    extends _$GatewayStateCopyWithImpl<$Res, _$GatewayDisconnectedImpl>
    implements _$$GatewayDisconnectedImplCopyWith<$Res> {
  __$$GatewayDisconnectedImplCopyWithImpl(
    _$GatewayDisconnectedImpl _value,
    $Res Function(_$GatewayDisconnectedImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of GatewayState
  /// with the given fields replaced by the non-null parameter values.
}

/// @nodoc

class _$GatewayDisconnectedImpl implements GatewayDisconnected {
  const _$GatewayDisconnectedImpl();

  @override
  String toString() {
    return 'GatewayState.disconnected()';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$GatewayDisconnectedImpl);
  }

  @override
  int get hashCode => runtimeType.hashCode;

  @override
  @optionalTypeArgs
  TResult when<TResult extends Object?>({
    required TResult Function() disconnected,
    required TResult Function() connecting,
    required TResult Function(String deviceId) connected,
    required TResult Function(String message) error,
  }) {
    return disconnected();
  }

  @override
  @optionalTypeArgs
  TResult? whenOrNull<TResult extends Object?>({
    TResult? Function()? disconnected,
    TResult? Function()? connecting,
    TResult? Function(String deviceId)? connected,
    TResult? Function(String message)? error,
  }) {
    return disconnected?.call();
  }

  @override
  @optionalTypeArgs
  TResult maybeWhen<TResult extends Object?>({
    TResult Function()? disconnected,
    TResult Function()? connecting,
    TResult Function(String deviceId)? connected,
    TResult Function(String message)? error,
    required TResult orElse(),
  }) {
    if (disconnected != null) {
      return disconnected();
    }
    return orElse();
  }

  @override
  @optionalTypeArgs
  TResult map<TResult extends Object?>({
    required TResult Function(GatewayDisconnected value) disconnected,
    required TResult Function(GatewayConnecting value) connecting,
    required TResult Function(GatewayConnected value) connected,
    required TResult Function(GatewayError value) error,
  }) {
    return disconnected(this);
  }

  @override
  @optionalTypeArgs
  TResult? mapOrNull<TResult extends Object?>({
    TResult? Function(GatewayDisconnected value)? disconnected,
    TResult? Function(GatewayConnecting value)? connecting,
    TResult? Function(GatewayConnected value)? connected,
    TResult? Function(GatewayError value)? error,
  }) {
    return disconnected?.call(this);
  }

  @override
  @optionalTypeArgs
  TResult maybeMap<TResult extends Object?>({
    TResult Function(GatewayDisconnected value)? disconnected,
    TResult Function(GatewayConnecting value)? connecting,
    TResult Function(GatewayConnected value)? connected,
    TResult Function(GatewayError value)? error,
    required TResult orElse(),
  }) {
    if (disconnected != null) {
      return disconnected(this);
    }
    return orElse();
  }
}

abstract class GatewayDisconnected implements GatewayState {
  const factory GatewayDisconnected() = _$GatewayDisconnectedImpl;
}

/// @nodoc
abstract class _$$GatewayConnectingImplCopyWith<$Res> {
  factory _$$GatewayConnectingImplCopyWith(
    _$GatewayConnectingImpl value,
    $Res Function(_$GatewayConnectingImpl) then,
  ) = __$$GatewayConnectingImplCopyWithImpl<$Res>;
}

/// @nodoc
class __$$GatewayConnectingImplCopyWithImpl<$Res>
    extends _$GatewayStateCopyWithImpl<$Res, _$GatewayConnectingImpl>
    implements _$$GatewayConnectingImplCopyWith<$Res> {
  __$$GatewayConnectingImplCopyWithImpl(
    _$GatewayConnectingImpl _value,
    $Res Function(_$GatewayConnectingImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of GatewayState
  /// with the given fields replaced by the non-null parameter values.
}

/// @nodoc

class _$GatewayConnectingImpl implements GatewayConnecting {
  const _$GatewayConnectingImpl();

  @override
  String toString() {
    return 'GatewayState.connecting()';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType && other is _$GatewayConnectingImpl);
  }

  @override
  int get hashCode => runtimeType.hashCode;

  @override
  @optionalTypeArgs
  TResult when<TResult extends Object?>({
    required TResult Function() disconnected,
    required TResult Function() connecting,
    required TResult Function(String deviceId) connected,
    required TResult Function(String message) error,
  }) {
    return connecting();
  }

  @override
  @optionalTypeArgs
  TResult? whenOrNull<TResult extends Object?>({
    TResult? Function()? disconnected,
    TResult? Function()? connecting,
    TResult? Function(String deviceId)? connected,
    TResult? Function(String message)? error,
  }) {
    return connecting?.call();
  }

  @override
  @optionalTypeArgs
  TResult maybeWhen<TResult extends Object?>({
    TResult Function()? disconnected,
    TResult Function()? connecting,
    TResult Function(String deviceId)? connected,
    TResult Function(String message)? error,
    required TResult orElse(),
  }) {
    if (connecting != null) {
      return connecting();
    }
    return orElse();
  }

  @override
  @optionalTypeArgs
  TResult map<TResult extends Object?>({
    required TResult Function(GatewayDisconnected value) disconnected,
    required TResult Function(GatewayConnecting value) connecting,
    required TResult Function(GatewayConnected value) connected,
    required TResult Function(GatewayError value) error,
  }) {
    return connecting(this);
  }

  @override
  @optionalTypeArgs
  TResult? mapOrNull<TResult extends Object?>({
    TResult? Function(GatewayDisconnected value)? disconnected,
    TResult? Function(GatewayConnecting value)? connecting,
    TResult? Function(GatewayConnected value)? connected,
    TResult? Function(GatewayError value)? error,
  }) {
    return connecting?.call(this);
  }

  @override
  @optionalTypeArgs
  TResult maybeMap<TResult extends Object?>({
    TResult Function(GatewayDisconnected value)? disconnected,
    TResult Function(GatewayConnecting value)? connecting,
    TResult Function(GatewayConnected value)? connected,
    TResult Function(GatewayError value)? error,
    required TResult orElse(),
  }) {
    if (connecting != null) {
      return connecting(this);
    }
    return orElse();
  }
}

abstract class GatewayConnecting implements GatewayState {
  const factory GatewayConnecting() = _$GatewayConnectingImpl;
}

/// @nodoc
abstract class _$$GatewayConnectedImplCopyWith<$Res> {
  factory _$$GatewayConnectedImplCopyWith(
    _$GatewayConnectedImpl value,
    $Res Function(_$GatewayConnectedImpl) then,
  ) = __$$GatewayConnectedImplCopyWithImpl<$Res>;
  @useResult
  $Res call({String deviceId});
}

/// @nodoc
class __$$GatewayConnectedImplCopyWithImpl<$Res>
    extends _$GatewayStateCopyWithImpl<$Res, _$GatewayConnectedImpl>
    implements _$$GatewayConnectedImplCopyWith<$Res> {
  __$$GatewayConnectedImplCopyWithImpl(
    _$GatewayConnectedImpl _value,
    $Res Function(_$GatewayConnectedImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of GatewayState
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? deviceId = null}) {
    return _then(
      _$GatewayConnectedImpl(
        deviceId: null == deviceId
            ? _value.deviceId
            : deviceId // ignore: cast_nullable_to_non_nullable
                  as String,
      ),
    );
  }
}

/// @nodoc

class _$GatewayConnectedImpl implements GatewayConnected {
  const _$GatewayConnectedImpl({required this.deviceId});

  @override
  final String deviceId;

  @override
  String toString() {
    return 'GatewayState.connected(deviceId: $deviceId)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$GatewayConnectedImpl &&
            (identical(other.deviceId, deviceId) ||
                other.deviceId == deviceId));
  }

  @override
  int get hashCode => Object.hash(runtimeType, deviceId);

  /// Create a copy of GatewayState
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$GatewayConnectedImplCopyWith<_$GatewayConnectedImpl> get copyWith =>
      __$$GatewayConnectedImplCopyWithImpl<_$GatewayConnectedImpl>(
        this,
        _$identity,
      );

  @override
  @optionalTypeArgs
  TResult when<TResult extends Object?>({
    required TResult Function() disconnected,
    required TResult Function() connecting,
    required TResult Function(String deviceId) connected,
    required TResult Function(String message) error,
  }) {
    return connected(deviceId);
  }

  @override
  @optionalTypeArgs
  TResult? whenOrNull<TResult extends Object?>({
    TResult? Function()? disconnected,
    TResult? Function()? connecting,
    TResult? Function(String deviceId)? connected,
    TResult? Function(String message)? error,
  }) {
    return connected?.call(deviceId);
  }

  @override
  @optionalTypeArgs
  TResult maybeWhen<TResult extends Object?>({
    TResult Function()? disconnected,
    TResult Function()? connecting,
    TResult Function(String deviceId)? connected,
    TResult Function(String message)? error,
    required TResult orElse(),
  }) {
    if (connected != null) {
      return connected(deviceId);
    }
    return orElse();
  }

  @override
  @optionalTypeArgs
  TResult map<TResult extends Object?>({
    required TResult Function(GatewayDisconnected value) disconnected,
    required TResult Function(GatewayConnecting value) connecting,
    required TResult Function(GatewayConnected value) connected,
    required TResult Function(GatewayError value) error,
  }) {
    return connected(this);
  }

  @override
  @optionalTypeArgs
  TResult? mapOrNull<TResult extends Object?>({
    TResult? Function(GatewayDisconnected value)? disconnected,
    TResult? Function(GatewayConnecting value)? connecting,
    TResult? Function(GatewayConnected value)? connected,
    TResult? Function(GatewayError value)? error,
  }) {
    return connected?.call(this);
  }

  @override
  @optionalTypeArgs
  TResult maybeMap<TResult extends Object?>({
    TResult Function(GatewayDisconnected value)? disconnected,
    TResult Function(GatewayConnecting value)? connecting,
    TResult Function(GatewayConnected value)? connected,
    TResult Function(GatewayError value)? error,
    required TResult orElse(),
  }) {
    if (connected != null) {
      return connected(this);
    }
    return orElse();
  }
}

abstract class GatewayConnected implements GatewayState {
  const factory GatewayConnected({required final String deviceId}) =
      _$GatewayConnectedImpl;

  String get deviceId;

  /// Create a copy of GatewayState
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$GatewayConnectedImplCopyWith<_$GatewayConnectedImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class _$$GatewayErrorImplCopyWith<$Res> {
  factory _$$GatewayErrorImplCopyWith(
    _$GatewayErrorImpl value,
    $Res Function(_$GatewayErrorImpl) then,
  ) = __$$GatewayErrorImplCopyWithImpl<$Res>;
  @useResult
  $Res call({String message});
}

/// @nodoc
class __$$GatewayErrorImplCopyWithImpl<$Res>
    extends _$GatewayStateCopyWithImpl<$Res, _$GatewayErrorImpl>
    implements _$$GatewayErrorImplCopyWith<$Res> {
  __$$GatewayErrorImplCopyWithImpl(
    _$GatewayErrorImpl _value,
    $Res Function(_$GatewayErrorImpl) _then,
  ) : super(_value, _then);

  /// Create a copy of GatewayState
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({Object? message = null}) {
    return _then(
      _$GatewayErrorImpl(
        null == message
            ? _value.message
            : message // ignore: cast_nullable_to_non_nullable
                  as String,
      ),
    );
  }
}

/// @nodoc

class _$GatewayErrorImpl implements GatewayError {
  const _$GatewayErrorImpl(this.message);

  @override
  final String message;

  @override
  String toString() {
    return 'GatewayState.error(message: $message)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$GatewayErrorImpl &&
            (identical(other.message, message) || other.message == message));
  }

  @override
  int get hashCode => Object.hash(runtimeType, message);

  /// Create a copy of GatewayState
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$GatewayErrorImplCopyWith<_$GatewayErrorImpl> get copyWith =>
      __$$GatewayErrorImplCopyWithImpl<_$GatewayErrorImpl>(this, _$identity);

  @override
  @optionalTypeArgs
  TResult when<TResult extends Object?>({
    required TResult Function() disconnected,
    required TResult Function() connecting,
    required TResult Function(String deviceId) connected,
    required TResult Function(String message) error,
  }) {
    return error(message);
  }

  @override
  @optionalTypeArgs
  TResult? whenOrNull<TResult extends Object?>({
    TResult? Function()? disconnected,
    TResult? Function()? connecting,
    TResult? Function(String deviceId)? connected,
    TResult? Function(String message)? error,
  }) {
    return error?.call(message);
  }

  @override
  @optionalTypeArgs
  TResult maybeWhen<TResult extends Object?>({
    TResult Function()? disconnected,
    TResult Function()? connecting,
    TResult Function(String deviceId)? connected,
    TResult Function(String message)? error,
    required TResult orElse(),
  }) {
    if (error != null) {
      return error(message);
    }
    return orElse();
  }

  @override
  @optionalTypeArgs
  TResult map<TResult extends Object?>({
    required TResult Function(GatewayDisconnected value) disconnected,
    required TResult Function(GatewayConnecting value) connecting,
    required TResult Function(GatewayConnected value) connected,
    required TResult Function(GatewayError value) error,
  }) {
    return error(this);
  }

  @override
  @optionalTypeArgs
  TResult? mapOrNull<TResult extends Object?>({
    TResult? Function(GatewayDisconnected value)? disconnected,
    TResult? Function(GatewayConnecting value)? connecting,
    TResult? Function(GatewayConnected value)? connected,
    TResult? Function(GatewayError value)? error,
  }) {
    return error?.call(this);
  }

  @override
  @optionalTypeArgs
  TResult maybeMap<TResult extends Object?>({
    TResult Function(GatewayDisconnected value)? disconnected,
    TResult Function(GatewayConnecting value)? connecting,
    TResult Function(GatewayConnected value)? connected,
    TResult Function(GatewayError value)? error,
    required TResult orElse(),
  }) {
    if (error != null) {
      return error(this);
    }
    return orElse();
  }
}

abstract class GatewayError implements GatewayState {
  const factory GatewayError(final String message) = _$GatewayErrorImpl;

  String get message;

  /// Create a copy of GatewayState
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$GatewayErrorImplCopyWith<_$GatewayErrorImpl> get copyWith =>
      throw _privateConstructorUsedError;
}
