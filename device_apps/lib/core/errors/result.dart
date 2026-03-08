import 'app_exception.dart';

/// Result typed success/failure. Replaces thrown exceptions at layer boundaries.
sealed class Result<T> {
  const Result();

  static Result<T> success<T>(T value) => Success(value);
  static Result<T> failure<T>(AppException error) => Failure(error);

  bool get isSuccess => this is Success<T>;
  bool get isFailure => this is Failure<T>;

  T? get valueOrNull => switch (this) {
        Success(:final value) => value,
        Failure() => null,
      };

  AppException? get errorOrNull => switch (this) {
        Success() => null,
        Failure(:final error) => error,
      };

  R when<R>({
    required R Function(T value) success,
    required R Function(AppException error) failure,
  }) =>
      switch (this) {
        Success(:final value) => success(value),
        Failure(:final error) => failure(error),
      };
}

final class Success<T> extends Result<T> {
  const Success(this.value);

  final T value;
}

final class Failure<T> extends Result<T> {
  const Failure(this.error);

  final AppException error;
}
