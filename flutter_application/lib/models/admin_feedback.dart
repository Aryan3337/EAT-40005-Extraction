// One resolved knowledge-graph triple a piece of feedback was attached to.
class FeedbackTriple {
  const FeedbackTriple({
    required this.id,
    required this.subject,
    required this.predicate,
    required this.object,
    required this.archived,
  });

  final String id;
  final String subject;
  final String predicate;
  final String object;
  final bool archived;

  factory FeedbackTriple.fromJson(Map<String, dynamic> json) => FeedbackTriple(
    id: json['id']?.toString() ?? '',
    subject: json['subject']?.toString() ?? '',
    predicate: json['predicate']?.toString() ?? '',
    object: json['object']?.toString() ?? '',
    archived: json['archived'] == true,
  );

  String get label => '$subject — $predicate → $object';
}

// A feedback entry as the admin review queue sees it.
class AdminFeedback {
  const AdminFeedback({
    required this.id,
    required this.userEmail,
    required this.responseText,
    required this.rating,
    required this.comment,
    required this.status,
    required this.reviewAction,
    required this.reviewedBy,
    required this.reviewedAt,
    required this.reviewNote,
    required this.createdAt,
    required this.triples,
  });

  final String id;
  final String userEmail;
  final String responseText;
  final String rating;
  final String comment;
  final String status;
  final String reviewAction;
  final String reviewedBy;
  final String reviewedAt;
  final String reviewNote;
  final String createdAt;
  final List<FeedbackTriple> triples;

  bool get isReviewed => status == 'reviewed';
  bool get isNotHelpful => rating == 'notHelpful';

  factory AdminFeedback.fromJson(Map<String, dynamic> json) {
    String read(String key) => json[key]?.toString() ?? '';
    final rawTriples = json['triples'];
    return AdminFeedback(
      id: read('id'),
      userEmail: read('user_email'),
      responseText: read('response_text'),
      rating: read('rating'),
      comment: read('comment'),
      status: json['status']?.toString() ?? 'pending',
      reviewAction: read('review_action'),
      reviewedBy: read('reviewed_by'),
      reviewedAt: read('reviewed_at'),
      reviewNote: read('review_note'),
      createdAt: read('created_at'),
      triples: rawTriples is List
          ? rawTriples
                .whereType<Map>()
                .map((t) => FeedbackTriple.fromJson(Map<String, dynamic>.from(t)))
                .toList()
          : const [],
    );
  }
}

class FeedbackStats {
  const FeedbackStats({
    this.total = 0,
    this.helpful = 0,
    this.notHelpful = 0,
    this.pending = 0,
    this.approved = 0,
    this.dismissed = 0,
    this.archivedTriples = 0,
  });

  final int total;
  final int helpful;
  final int notHelpful;
  final int pending;
  final int approved;
  final int dismissed;
  final int archivedTriples;

  factory FeedbackStats.fromJson(Map<String, dynamic> json) {
    int n(String key) {
      final v = json[key];
      return v is num ? v.toInt() : int.tryParse('$v') ?? 0;
    }

    return FeedbackStats(
      total: n('total'),
      helpful: n('helpful'),
      notHelpful: n('not_helpful'),
      pending: n('pending'),
      approved: n('approved'),
      dismissed: n('dismissed'),
      archivedTriples: n('archived_triples'),
    );
  }
}

// An admin's replacement for one wrong triple. The old triple is archived.
class TripleCorrection {
  const TripleCorrection({
    required this.tripleId,
    required this.subject,
    required this.predicate,
    required this.object,
  });

  final String tripleId;
  final String subject;
  final String predicate;
  final String object;

  Map<String, dynamic> toJson() => {
    'triple_id': tripleId,
    'subject': subject,
    'predicate': predicate,
    'object': object,
  };
}
