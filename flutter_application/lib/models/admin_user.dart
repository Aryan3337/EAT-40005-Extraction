class AdminUser {
  const AdminUser({
    required this.email,
    required this.role,
    required this.createdAt,
    required this.feedbackCount,
    required this.conversationCount,
    required this.messageCount,
  });

  final String email;
  final String role;
  final String createdAt;
  final int feedbackCount;
  final int conversationCount;
  final int messageCount;

  factory AdminUser.fromJson(Map<String, dynamic> json) => AdminUser(
    email: json['email']?.toString() ?? '',
    role: json['role']?.toString() ?? 'user',
    createdAt: json['created_at']?.toString() ?? '',
    feedbackCount: _number(json['feedback_count']),
    conversationCount: _number(json['conversation_count']),
    messageCount: _number(json['message_count']),
  );

  static int _number(dynamic value) =>
      value is num ? value.toInt() : int.tryParse('$value') ?? 0;
}
