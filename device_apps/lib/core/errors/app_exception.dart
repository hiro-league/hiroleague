/// Typed error hierarchy. No raw exceptions outside the data layer.
sealed class AppException implements Exception {
  const AppException(this.message);

  final String message;

  @override
  String toString() => '$runtimeType: $message';
}

final class NetworkException extends AppException {
  const NetworkException(super.message, {this.statusCode});

  final int? statusCode;
}

final class AuthException extends AppException {
  const AuthException(super.message);
}

final class PairingException extends AppException {
  const PairingException(super.message);
}

final class StorageException extends AppException {
  const StorageException(super.message);
}

final class GatewayException extends AppException {
  const GatewayException(super.message);
}

final class ValidationException extends AppException {
  const ValidationException(super.message);
}

final class UnknownException extends AppException {
  const UnknownException(super.message, {this.cause});

  final Object? cause;
}
