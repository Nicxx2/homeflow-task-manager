import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import '../../core/models/auth_session.dart';
import '../../core/models/mobile_task.dart';
import '../../core/models/remote_task_window.dart';
import '../../core/models/task_next_available_result.dart';
import '../../core/models/task_schedule_feedback.dart';
import '../../core/models/task_schedule_update_result.dart';
import '../../core/models/task_status_update_result.dart';
import 'api_exception.dart';

class HomeflowApiClient {
  static const Duration _requestTimeout = Duration(seconds: 15);

  HomeflowApiClient({required String baseUrl, required http.Client httpClient})
      : _baseUri = Uri.parse(baseUrl),
        _httpClient = httpClient;

  final Uri _baseUri;
  final http.Client _httpClient;

  Future<void> testConnection() async {
    await _getJson('/health');
  }

  Future<AuthSession> login({
    required String email,
    required String password,
  }) async {
    final payload = await _postJson(
      '/api/v1/auth/login',
      body: <String, dynamic>{'email': email, 'password': password},
    );
    return AuthSession.fromJson(payload);
  }

  Future<RemoteTaskWindow> fetchTaskWindow({
    required String accessToken,
    required DateTime startDate,
    required DateTime endDate,
  }) async {
    final payload = await _getJson(
      '/api/v1/mobile/tasks/window',
      queryParameters: <String, String>{
        'start': _formatDate(startDate),
        'end': _formatDate(endDate),
      },
      accessToken: accessToken,
    );
    return RemoteTaskWindow.fromJson(payload);
  }

  Future<TaskStatusUpdateResult> updateTaskStatus({
    required String accessToken,
    required int taskId,
    required MobileTaskStatus status,
  }) async {
    final payload = await _patchJson(
      '/api/v1/mobile/tasks/$taskId/status',
      accessToken: accessToken,
      body: <String, dynamic>{'status': status.value},
    );
    final task = payload['task'];
    final refreshRequired = payload['refresh_required'] as bool? ?? false;
    if (task is! Map<String, dynamic>) {
      return TaskStatusUpdateResult(
        refreshRequired: refreshRequired,
        task: null,
      );
    }
    return TaskStatusUpdateResult(
      refreshRequired: refreshRequired,
      task: MobileTask.fromJson(task),
    );
  }

  Future<TaskScheduleFeedback> checkTaskSchedule({
    required String accessToken,
    required int taskId,
    required DateTime assignmentDate,
  }) async {
    final payload = await _getJson(
      '/api/v1/mobile/tasks/$taskId/schedule/check',
      queryParameters: <String, String>{
        'assignment_date': _formatDate(assignmentDate),
      },
      accessToken: accessToken,
    );
    return TaskScheduleFeedback.fromJson(payload);
  }

  Future<TaskNextAvailableResult> fetchTaskNextAvailableDate({
    required String accessToken,
    required int taskId,
    DateTime? startDate,
  }) async {
    final payload = await _getJson(
      '/api/v1/mobile/tasks/$taskId/schedule/next-available',
      queryParameters: <String, String>{
        if (startDate != null) 'start_date': _formatDate(startDate),
      },
      accessToken: accessToken,
    );
    return TaskNextAvailableResult.fromJson(payload);
  }

  Future<TaskScheduleUpdateResult> updateTaskSchedule({
    required String accessToken,
    required int taskId,
    required DateTime dueDate,
    required DateTime assignmentDate,
    bool extendCapacity = false,
  }) async {
    final payload = await _patchJson(
      '/api/v1/mobile/tasks/$taskId/schedule',
      accessToken: accessToken,
      body: <String, dynamic>{
        'due_date': _formatDate(dueDate),
        'assignment_date': _formatDate(assignmentDate),
        'extend_capacity': extendCapacity,
      },
    );
    return TaskScheduleUpdateResult.fromJson(payload);
  }

  Future<Map<String, dynamic>> _getJson(
    String path, {
    Map<String, String>? queryParameters,
    String? accessToken,
  }) async {
    final uri = _baseUri.replace(path: path, queryParameters: queryParameters);
    try {
      final response = await _httpClient
          .get(uri, headers: _headers(accessToken: accessToken))
          .timeout(_requestTimeout);
      return _decodeJson(response);
    } on SocketException {
      throw const ApiException(
        type: ApiErrorType.serverUnreachable,
        message: 'Unable to reach the Homeflow server.',
      );
    } on TimeoutException {
      throw const ApiException(
        type: ApiErrorType.networkUnavailable,
        message: 'Network request timed out.',
      );
    }
  }

  Future<Map<String, dynamic>> _postJson(
    String path, {
    required Map<String, dynamic> body,
    String? accessToken,
  }) async {
    final uri = _baseUri.replace(path: path);
    try {
      final response = await _httpClient
          .post(
            uri,
            headers: _headers(accessToken: accessToken),
            body: jsonEncode(body),
          )
          .timeout(_requestTimeout);
      return _decodeJson(response);
    } on SocketException {
      throw const ApiException(
        type: ApiErrorType.serverUnreachable,
        message: 'Unable to reach the Homeflow server.',
      );
    } on TimeoutException {
      throw const ApiException(
        type: ApiErrorType.networkUnavailable,
        message: 'Network request timed out.',
      );
    }
  }

  Future<Map<String, dynamic>> _patchJson(
    String path, {
    required Map<String, dynamic> body,
    String? accessToken,
  }) async {
    final uri = _baseUri.replace(path: path);
    try {
      final response = await _httpClient
          .patch(
            uri,
            headers: _headers(accessToken: accessToken),
            body: jsonEncode(body),
          )
          .timeout(_requestTimeout);
      return _decodeJson(response);
    } on SocketException {
      throw const ApiException(
        type: ApiErrorType.serverUnreachable,
        message: 'Unable to reach the Homeflow server.',
      );
    } on TimeoutException {
      throw const ApiException(
        type: ApiErrorType.networkUnavailable,
        message: 'Network request timed out.',
      );
    }
  }

  Map<String, String> _headers({String? accessToken}) {
    return <String, String>{
      'Content-Type': 'application/json',
      if (accessToken != null) 'Authorization': 'Bearer $accessToken',
    };
  }

  Map<String, dynamic> _decodeJson(http.Response response) {
    final dynamic decoded;
    try {
      decoded = response.body.isEmpty
          ? <String, dynamic>{}
          : jsonDecode(response.body);
    } on FormatException {
      throw ApiException(
        type: response.statusCode >= 500
            ? ApiErrorType.serverError
            : ApiErrorType.unknown,
        message: response.statusCode >= 500
            ? 'Server returned an invalid error response.'
            : 'Unexpected response from the server.',
        statusCode: response.statusCode,
        retryable: response.statusCode >= 500,
      );
    }

    if (response.statusCode >= 200 && response.statusCode < 300) {
      if (decoded is Map<String, dynamic>) {
        return decoded;
      }
      throw const ApiException(
        type: ApiErrorType.unknown,
        message: 'Unexpected response shape from the server.',
      );
    }

    final payload =
        decoded is Map<String, dynamic> ? decoded : <String, dynamic>{};
    final code = payload['code'] as String?;
    final detail = payload['detail'] as String? ?? 'Server request failed.';
    throw ApiException(
      type: _mapApiErrorType(response.statusCode, code),
      message: detail,
      statusCode: response.statusCode,
      code: code,
      retryable: payload['retryable'] as bool? ?? response.statusCode >= 500,
    );
  }

  ApiErrorType _mapApiErrorType(int statusCode, String? code) {
    switch (code) {
      case 'invalid_credentials':
        return ApiErrorType.invalidCredentials;
      case 'not_authenticated':
        return ApiErrorType.notAuthenticated;
      case 'invalid_token':
        return ApiErrorType.invalidToken;
      case 'session_expired':
        return ApiErrorType.sessionExpired;
      case 'approval_pending':
        return ApiErrorType.approvalPending;
      case 'registration_rejected':
        return ApiErrorType.registrationRejected;
      case 'forbidden':
        return ApiErrorType.forbidden;
      case 'invalid_request':
        return ApiErrorType.invalidRequest;
      case 'validation_error':
        return ApiErrorType.validationError;
      case 'not_found':
        return ApiErrorType.notFound;
      case 'server_error':
        return ApiErrorType.serverError;
    }

    if (statusCode >= 500) {
      return ApiErrorType.serverError;
    }
    return ApiErrorType.unknown;
  }

  String _formatDate(DateTime value) {
    final month = value.month.toString().padLeft(2, '0');
    final day = value.day.toString().padLeft(2, '0');
    return '${value.year}-$month-$day';
  }
}
