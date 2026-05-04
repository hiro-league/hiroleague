/// Wire-level constants shared by the Flutter gateway client.
///
/// These values mirror `hiro-channel-sdk` and the schemas under
/// `protocol/`. Keep user-facing domain constants out of this file.
library;

abstract final class UnifiedMessageWire {
  static const version = '0.1';

  static const typeMessage = 'message';
  static const typeEvent = 'event';
  static const typeRequest = 'request';
  static const typeResponse = 'response';
  static const typeStream = 'stream';

  static const directionInbound = 'inbound';
  static const directionOutbound = 'outbound';
}

abstract final class ContentWire {
  static const text = 'text';
  static const json = 'json';
  static const image = 'image';
  static const audio = 'audio';
  static const video = 'video';
  static const file = 'file';
  static const location = 'location';
}

abstract final class EventWire {
  static const messageReceived = 'message.received';
  static const messageTranscribed = 'message.transcribed';
  static const messageVoiced = 'message.voiced';
  static const messageContentAdded = 'message.content_added';
  static const resourceChanged = 'resource.changed';
}

abstract final class GatewayEnvelopeWire {
  static const senderDeviceId = 'sender_device_id';
  static const targetDeviceId = 'target_device_id';
  static const payload = 'payload';
}

abstract final class GatewayAuthWire {
  static const type = 'type';
  static const authChallenge = 'auth_challenge';
  static const authResponse = 'auth_response';
  static const authOk = 'auth_ok';
  static const authFailed = 'auth_failed';
  static const authMode = 'auth_mode';
  static const authModeDevice = 'device';
  static const nonce = 'nonce';
  static const nonceSignature = 'nonce_signature';
  static const attestation = 'attestation';
  static const deviceId = 'device_id';
  static const deviceName = 'device_name';
  static const reason = 'reason';
}

abstract final class GatewayPairingWire {
  static const pairingRequest = 'pairing_request';
  static const pairingPending = 'pairing_pending';
  static const pairingResponse = 'pairing_response';
}

abstract final class MetadataWire {
  static const channelId = 'channel_id';
  static const deviceName = 'device_name';
  static const senderDeviceId = 'sender_device_id';
  static const friendlyName = 'friendly_name';
  static const requestVoiceReply = 'request_voice_reply';
}
