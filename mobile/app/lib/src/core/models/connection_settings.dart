class ConnectionSettings {
  const ConnectionSettings({
    required this.scheme,
    required this.host,
    required this.port,
  });

  factory ConnectionSettings.fromJson(Map<String, dynamic> json) {
    final normalized = _normalizeConnectionEndpoint(
      rawHost: json['host'] as String? ?? '',
      fallbackPort: json['port'] as int? ?? 8000,
    );
    return ConnectionSettings(
      scheme: json['scheme'] as String? ?? 'http',
      host: normalized.host,
      port: normalized.port,
    );
  }

  factory ConnectionSettings.sanitized({
    required String scheme,
    required String host,
    required int port,
  }) {
    final normalized = _normalizeConnectionEndpoint(
      rawHost: host,
      fallbackPort: port,
    );
    return ConnectionSettings(
      scheme: scheme,
      host: normalized.host,
      port: normalized.port,
    );
  }

  final String scheme;
  final String host;
  final int port;

  String get baseUrl {
    final normalized = _normalizeConnectionEndpoint(
      rawHost: host,
      fallbackPort: port,
    );
    return '$scheme://${normalized.host}:${normalized.port}';
  }

  bool get isValid => validationError == null;

  String? get validationError {
    final normalized = _normalizeConnectionEndpoint(
      rawHost: host,
      fallbackPort: port,
    );
    if (normalized.host.trim().isEmpty) {
      return 'Host is required.';
    }
    if (normalized.port < 1 || normalized.port > 65535) {
      return 'Port must be between 1 and 65535.';
    }
    if (scheme != 'http' && scheme != 'https') {
      return 'Scheme must be http or https.';
    }
    return null;
  }

  Map<String, dynamic> toJson() {
    final normalized = _normalizeConnectionEndpoint(
      rawHost: host,
      fallbackPort: port,
    );
    return <String, dynamic>{
      'scheme': scheme,
      'host': normalized.host,
      'port': normalized.port,
    };
  }
}

_NormalizedConnectionEndpoint _normalizeConnectionEndpoint({
  required String rawHost,
  required int fallbackPort,
}) {
  final trimmed = rawHost.trim();
  if (trimmed.isEmpty) {
    return _NormalizedConnectionEndpoint(host: '', port: fallbackPort);
  }

  Uri? parsed;
  if (trimmed.contains('://')) {
    parsed = Uri.tryParse(trimmed);
  } else {
    parsed = Uri.tryParse('http://$trimmed');
  }
  if (parsed != null && parsed.host.isNotEmpty) {
    return _NormalizedConnectionEndpoint(
      host: parsed.host,
      port: parsed.hasPort ? parsed.port : fallbackPort,
    );
  }

  var fallbackHost = trimmed
      .replaceFirst(RegExp(r'^[a-zA-Z][a-zA-Z0-9+.-]*://'), '')
      .replaceFirst(RegExp(r'^//+'), '');
  for (final separator in const ['/', '?', '#']) {
    final index = fallbackHost.indexOf(separator);
    if (index >= 0) {
      fallbackHost = fallbackHost.substring(0, index);
    }
  }

  if (fallbackHost.startsWith('[')) {
    final closingBracket = fallbackHost.indexOf(']');
    if (closingBracket > 0) {
      final host = fallbackHost.substring(1, closingBracket);
      final remainder = fallbackHost.substring(closingBracket + 1);
      final parsedPort = remainder.startsWith(':')
          ? int.tryParse(remainder.substring(1))
          : null;
      return _NormalizedConnectionEndpoint(
        host: host,
        port: parsedPort ?? fallbackPort,
      );
    }
  }

  final firstColon = fallbackHost.indexOf(':');
  final lastColon = fallbackHost.lastIndexOf(':');
  if (firstColon > 0 && firstColon == lastColon) {
    final parsedPort = int.tryParse(fallbackHost.substring(lastColon + 1));
    return _NormalizedConnectionEndpoint(
      host: fallbackHost.substring(0, lastColon),
      port: parsedPort ?? fallbackPort,
    );
  }

  return _NormalizedConnectionEndpoint(host: fallbackHost, port: fallbackPort);
}

class _NormalizedConnectionEndpoint {
  const _NormalizedConnectionEndpoint({
    required this.host,
    required this.port,
  });

  final String host;
  final int port;
}
