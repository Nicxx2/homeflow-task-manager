class ConnectionSettings {
  const ConnectionSettings({
    required this.scheme,
    required this.host,
    required this.port,
  });

  factory ConnectionSettings.fromJson(Map<String, dynamic> json) {
    return ConnectionSettings(
      scheme: json['scheme'] as String? ?? 'http',
      host: json['host'] as String? ?? '',
      port: json['port'] as int? ?? 8000,
    );
  }

  final String scheme;
  final String host;
  final int port;

  String get baseUrl => '$scheme://$host:$port';

  bool get isValid => validationError == null;

  String? get validationError {
    if (host.trim().isEmpty) {
      return 'Host is required.';
    }
    if (port < 1 || port > 65535) {
      return 'Port must be between 1 and 65535.';
    }
    if (scheme != 'http' && scheme != 'https') {
      return 'Scheme must be http or https.';
    }
    return null;
  }

  Map<String, dynamic> toJson() {
    return <String, dynamic>{'scheme': scheme, 'host': host, 'port': port};
  }
}
