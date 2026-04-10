class SavedLogin {
  const SavedLogin({
    required this.email,
    required this.password,
  });

  factory SavedLogin.fromJson(Map<String, dynamic> json) {
    return SavedLogin(
      email: json['email'] as String,
      password: json['password'] as String,
    );
  }

  final String email;
  final String password;

  Map<String, dynamic> toJson() {
    return <String, dynamic>{
      'email': email,
      'password': password,
    };
  }
}
