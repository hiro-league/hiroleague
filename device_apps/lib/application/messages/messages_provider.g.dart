// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'messages_provider.dart';

// **************************************************************************
// RiverpodGenerator
// **************************************************************************

String _$channelMessagesHash() => r'832fcef3ca8bb5c1e8a06e2659bc16b253432aee';

/// Copied from Dart SDK
class _SystemHash {
  _SystemHash._();

  static int combine(int hash, int value) {
    // ignore: parameter_assignments
    hash = 0x1fffffff & (hash + value);
    // ignore: parameter_assignments
    hash = 0x1fffffff & (hash + ((0x0007ffff & hash) << 10));
    return hash ^ (hash >> 6);
  }

  static int finish(int hash) {
    // ignore: parameter_assignments
    hash = 0x1fffffff & (hash + ((0x03ffffff & hash) << 3));
    // ignore: parameter_assignments
    hash = hash ^ (hash >> 11);
    return 0x1fffffff & (hash + ((0x00003fff & hash) << 15));
  }
}

/// Live stream of messages for [channelId], sorted oldest→newest.
///
/// Copied from [channelMessages].
@ProviderFor(channelMessages)
const channelMessagesProvider = ChannelMessagesFamily();

/// Live stream of messages for [channelId], sorted oldest→newest.
///
/// Copied from [channelMessages].
class ChannelMessagesFamily extends Family<AsyncValue<List<Message>>> {
  /// Live stream of messages for [channelId], sorted oldest→newest.
  ///
  /// Copied from [channelMessages].
  const ChannelMessagesFamily();

  /// Live stream of messages for [channelId], sorted oldest→newest.
  ///
  /// Copied from [channelMessages].
  ChannelMessagesProvider call(String channelId) {
    return ChannelMessagesProvider(channelId);
  }

  @override
  ChannelMessagesProvider getProviderOverride(
    covariant ChannelMessagesProvider provider,
  ) {
    return call(provider.channelId);
  }

  static const Iterable<ProviderOrFamily>? _dependencies = null;

  @override
  Iterable<ProviderOrFamily>? get dependencies => _dependencies;

  static const Iterable<ProviderOrFamily>? _allTransitiveDependencies = null;

  @override
  Iterable<ProviderOrFamily>? get allTransitiveDependencies =>
      _allTransitiveDependencies;

  @override
  String? get name => r'channelMessagesProvider';
}

/// Live stream of messages for [channelId], sorted oldest→newest.
///
/// Copied from [channelMessages].
class ChannelMessagesProvider extends AutoDisposeStreamProvider<List<Message>> {
  /// Live stream of messages for [channelId], sorted oldest→newest.
  ///
  /// Copied from [channelMessages].
  ChannelMessagesProvider(String channelId)
    : this._internal(
        (ref) => channelMessages(ref as ChannelMessagesRef, channelId),
        from: channelMessagesProvider,
        name: r'channelMessagesProvider',
        debugGetCreateSourceHash: const bool.fromEnvironment('dart.vm.product')
            ? null
            : _$channelMessagesHash,
        dependencies: ChannelMessagesFamily._dependencies,
        allTransitiveDependencies:
            ChannelMessagesFamily._allTransitiveDependencies,
        channelId: channelId,
      );

  ChannelMessagesProvider._internal(
    super._createNotifier, {
    required super.name,
    required super.dependencies,
    required super.allTransitiveDependencies,
    required super.debugGetCreateSourceHash,
    required super.from,
    required this.channelId,
  }) : super.internal();

  final String channelId;

  @override
  Override overrideWith(
    Stream<List<Message>> Function(ChannelMessagesRef provider) create,
  ) {
    return ProviderOverride(
      origin: this,
      override: ChannelMessagesProvider._internal(
        (ref) => create(ref as ChannelMessagesRef),
        from: from,
        name: null,
        dependencies: null,
        allTransitiveDependencies: null,
        debugGetCreateSourceHash: null,
        channelId: channelId,
      ),
    );
  }

  @override
  AutoDisposeStreamProviderElement<List<Message>> createElement() {
    return _ChannelMessagesProviderElement(this);
  }

  @override
  bool operator ==(Object other) {
    return other is ChannelMessagesProvider && other.channelId == channelId;
  }

  @override
  int get hashCode {
    var hash = _SystemHash.combine(0, runtimeType.hashCode);
    hash = _SystemHash.combine(hash, channelId.hashCode);

    return _SystemHash.finish(hash);
  }
}

@Deprecated('Will be removed in 3.0. Use Ref instead')
// ignore: unused_element
mixin ChannelMessagesRef on AutoDisposeStreamProviderRef<List<Message>> {
  /// The parameter `channelId` of this provider.
  String get channelId;
}

class _ChannelMessagesProviderElement
    extends AutoDisposeStreamProviderElement<List<Message>>
    with ChannelMessagesRef {
  _ChannelMessagesProviderElement(super.provider);

  @override
  String get channelId => (origin as ChannelMessagesProvider).channelId;
}

// ignore_for_file: type=lint
// ignore_for_file: subtype_of_sealed_class, invalid_use_of_internal_member, invalid_use_of_visible_for_testing_member, deprecated_member_use_from_same_package
