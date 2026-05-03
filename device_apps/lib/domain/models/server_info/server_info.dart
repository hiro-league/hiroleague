library;

int _requireInt(Map<String, dynamic> json, String key, String context) {
  final value = json[key];
  if (value is int) return value;
  if (value is num) return value.toInt();
  throw FormatException(
    '$context: "$key" must be an int, got ${value?.runtimeType}',
  );
}

String _requireString(Map<String, dynamic> json, String key, String context) {
  final value = json[key];
  if (value is String && value.isNotEmpty) return value;
  throw FormatException(
    '$context: "$key" must be a non-empty string, got ${value?.runtimeType}',
  );
}

Map<String, dynamic> _asStringMap(dynamic value, String context) {
  if (value is Map) return Map<String, dynamic>.from(value);
  throw FormatException('$context must be a JSON object, got ${value.runtimeType}');
}

class ModalityFlags {
  const ModalityFlags({
    required this.voice,
    required this.image,
    required this.video,
    required this.file,
  });

  const ModalityFlags.defaults()
    : voice = false,
      image = false,
      video = false,
      file = false;

  final bool voice;
  final bool image;
  final bool video;
  final bool file;

  factory ModalityFlags.fromJson(Map<String, dynamic> json) {
    return ModalityFlags(
      voice: json['voice'] as bool? ?? false,
      image: json['image'] as bool? ?? false,
      video: json['video'] as bool? ?? false,
      file: json['file'] as bool? ?? false,
    );
  }

  Map<String, dynamic> toJson() => {
    'voice': voice,
    'image': image,
    'video': video,
    'file': file,
  };
}

class MediaCapabilities {
  const MediaCapabilities({required this.input, required this.output});

  const MediaCapabilities.defaults()
    : input = const ModalityFlags.defaults(),
      output = const ModalityFlags.defaults();

  final ModalityFlags input;
  final ModalityFlags output;

  factory MediaCapabilities.fromJson(Map<String, dynamic> json) {
    return MediaCapabilities(
      input: ModalityFlags.fromJson(
        _asStringMap(json['input'], 'MediaCapabilities.input'),
      ),
      output: ModalityFlags.fromJson(
        _asStringMap(json['output'], 'MediaCapabilities.output'),
      ),
    );
  }

  Map<String, dynamic> toJson() => {
    'input': input.toJson(),
    'output': output.toJson(),
  };
}

class ServerInfoCharacter {
  const ServerInfoCharacter({required this.id, required this.name});

  final String id;
  final String name;

  factory ServerInfoCharacter.fromJson(Map<String, dynamic> json) {
    return ServerInfoCharacter(
      id: _requireString(json, 'id', 'ServerInfoCharacter'),
      name: _requireString(json, 'name', 'ServerInfoCharacter'),
    );
  }

  Map<String, dynamic> toJson() => {'id': id, 'name': name};
}

class ServerInfoChannel {
  const ServerInfoChannel({
    required this.id,
    required this.name,
    required this.character,
    required this.capabilities,
  });

  final int id;
  final String name;
  final ServerInfoCharacter character;
  final MediaCapabilities capabilities;

  String get localChannelId => 'server-$id';

  factory ServerInfoChannel.fromJson(Map<String, dynamic> json) {
    return ServerInfoChannel(
      id: _requireInt(json, 'id', 'ServerInfoChannel'),
      name: _requireString(json, 'name', 'ServerInfoChannel'),
      character: ServerInfoCharacter.fromJson(
        _asStringMap(json['character'], 'ServerInfoChannel.character'),
      ),
      capabilities: MediaCapabilities.fromJson(
        _asStringMap(json['capabilities'], 'ServerInfoChannel.capabilities'),
      ),
    );
  }

  Map<String, dynamic> toJson() => {
    'id': id,
    'name': name,
    'character': character.toJson(),
    'capabilities': capabilities.toJson(),
  };
}

class ServerInfoSnapshot {
  const ServerInfoSnapshot({
    required this.version,
    required this.policy,
    required this.channels,
  });

  final int version;
  final MediaCapabilities policy;
  final List<ServerInfoChannel> channels;

  factory ServerInfoSnapshot.fromJson(Map<String, dynamic> json) {
    final channelsRaw = json['channels'];
    if (channelsRaw is! List) {
      throw FormatException(
        'ServerInfoSnapshot: "channels" must be a JSON array, got ${channelsRaw.runtimeType}',
      );
    }
    return ServerInfoSnapshot(
      version: _requireInt(json, 'version', 'ServerInfoSnapshot'),
      policy: MediaCapabilities.fromJson(
        _asStringMap(json['policy'], 'ServerInfoSnapshot.policy'),
      ),
      channels: channelsRaw.map((entry) {
        if (entry is! Map) {
          throw FormatException(
            'ServerInfoSnapshot: channel entry must be a JSON object, got ${entry.runtimeType}',
          );
        }
        return ServerInfoChannel.fromJson(Map<String, dynamic>.from(entry));
      }).toList(),
    );
  }

  Map<String, dynamic> toJson() => {
    'version': version,
    'policy': policy.toJson(),
    'channels': channels.map((channel) => channel.toJson()).toList(),
  };

  ServerInfoChannel? channelForLocalId(String channelId) {
    for (final channel in channels) {
      if (channel.localChannelId == channelId) return channel;
    }
    return null;
  }
}
