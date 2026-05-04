library;

int _requireInt(Map<String, dynamic> json, String key, String context) {
  final value = json[key];
  if (value is int) return value;
  if (value is num) return value.toInt();
  throw FormatException(
    '$context: "$key" must be an int, got ${value?.runtimeType}',
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

/// Workspace-wide saved media policy — channel rows live on `channels.list`.
class PolicySnapshot {
  const PolicySnapshot({
    required this.version,
    required this.policy,
  });

  final int version;
  final MediaCapabilities policy;

  factory PolicySnapshot.fromJson(Map<String, dynamic> json) {
    return PolicySnapshot(
      version: _requireInt(json, 'version', 'PolicySnapshot'),
      policy: MediaCapabilities.fromJson(
        _asStringMap(json['policy'], 'PolicySnapshot.policy'),
      ),
    );
  }

  Map<String, dynamic> toJson() => {
    'version': version,
    'policy': policy.toJson(),
  };
}
