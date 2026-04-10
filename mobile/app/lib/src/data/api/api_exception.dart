enum ApiErrorType {
  invalidCredentials,
  notAuthenticated,
  invalidToken,
  sessionExpired,
  approvalPending,
  registrationRejected,
  forbidden,
  invalidRequest,
  validationError,
  notFound,
  networkUnavailable,
  serverUnreachable,
  serverError,
  unknown,
}

class ApiException implements Exception {
  const ApiException({
    required this.type,
    required this.message,
    this.statusCode,
    this.code,
    this.retryable = false,
  });

  final ApiErrorType type;
  final String message;
  final int? statusCode;
  final String? code;
  final bool retryable;

  @override
  String toString() {
    return 'ApiException(type: $type, statusCode: $statusCode, code: $code, message: $message)';
  }
}
