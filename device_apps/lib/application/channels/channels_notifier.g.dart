// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'channels_notifier.dart';

// **************************************************************************
// RiverpodGenerator
// **************************************************************************

String _$channelsHash() => r'be06361c99de758e9c838074db1d95c81e9c2752';

/// Emits the live list of channels from the local DB.
/// On first build, seeds the default "General" channel if the DB is empty.
///
/// Copied from [channels].
@ProviderFor(channels)
final channelsProvider = AutoDisposeStreamProvider<List<Channel>>.internal(
  channels,
  name: r'channelsProvider',
  debugGetCreateSourceHash: const bool.fromEnvironment('dart.vm.product')
      ? null
      : _$channelsHash,
  dependencies: null,
  allTransitiveDependencies: null,
);

@Deprecated('Will be removed in 3.0. Use Ref instead')
// ignore: unused_element
typedef ChannelsRef = AutoDisposeStreamProviderRef<List<Channel>>;
// ignore_for_file: type=lint
// ignore_for_file: subtype_of_sealed_class, invalid_use_of_internal_member, invalid_use_of_visible_for_testing_member, deprecated_member_use_from_same_package
