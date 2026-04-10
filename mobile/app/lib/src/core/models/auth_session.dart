class AuthUser {
  const AuthUser({
    required this.id,
    required this.email,
    required this.fullName,
    required this.isAdmin,
    required this.isActive,
    required this.approvalStatus,
    required this.showInMemberLists,
  });

  factory AuthUser.fromJson(Map<String, dynamic> json) {
    return AuthUser(
      id: json['id'] as int,
      email: json['email'] as String,
      fullName: json['full_name'] as String,
      isAdmin: json['is_admin'] as bool? ?? false,
      isActive: json['is_active'] as bool? ?? true,
      approvalStatus: json['approval_status'] as String? ?? 'approved',
      showInMemberLists: json['show_in_member_lists'] as bool? ?? true,
    );
  }

  final int id;
  final String email;
  final String fullName;
  final bool isAdmin;
  final bool isActive;
  final String approvalStatus;
  final bool showInMemberLists;

  Map<String, dynamic> toJson() {
    return <String, dynamic>{
      'id': id,
      'email': email,
      'full_name': fullName,
      'is_admin': isAdmin,
      'is_active': isActive,
      'approval_status': approvalStatus,
      'show_in_member_lists': showInMemberLists,
    };
  }
}

class AuthSession {
  const AuthSession({
    required this.accessToken,
    required this.expiresAt,
    required this.user,
  });

  factory AuthSession.fromJson(Map<String, dynamic> json) {
    return AuthSession(
      accessToken: json['access_token'] as String,
      expiresAt: DateTime.parse(json['expires_at'] as String).toUtc(),
      user: AuthUser.fromJson(json['user'] as Map<String, dynamic>),
    );
  }

  final String accessToken;
  final DateTime expiresAt;
  final AuthUser user;

  bool get isExpired => DateTime.now().toUtc().isAfter(expiresAt);

  Map<String, dynamic> toJson() {
    return <String, dynamic>{
      'access_token': accessToken,
      'expires_at': expiresAt.toIso8601String(),
      'user': user.toJson(),
    };
  }
}
