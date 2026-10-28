// One decision from the admin upload queue, as rag.py's /admin/queue returns
// it. Mirrors admin_ingest.IngestOutcome.to_json plus the server's timestamp.

enum IngestDecision {
  readyToExtract,
  heldForReview,
  rejected,
  scoringFailed,
  // What happened AFTER approval. The server appends these to the same
  // append-only queue as the verdicts above and later entries win, so an
  // approved paper that is now extracting shows one row, not two.
  extracting,
  extracted,
  extractionFailed,
  unknown,
}

class IngestEntry {
  const IngestEntry({
    required this.paper,
    required this.decision,
    this.score,
    this.maxScore,
    this.outcome,
    this.reasons = const [],
    this.storedPath,
    this.at,
    this.triplesLoaded,
    this.error,
  });

  final String paper;
  final IngestDecision decision;
  final int? score;
  final int? maxScore;
  final String? outcome;
  final List<String> reasons;
  final String? storedPath;
  final String? at;

  // Set once an extraction finishes. 0 is a real answer -- it means nothing
  // survived the three verification gates -- so this is nullable to keep
  // "no extraction yet" distinct from "extracted nothing".
  final int? triplesLoaded;
  final String? error;

  // A rejected paper is discarded; everything else is kept on the server.
  bool get isStored => storedPath != null && storedPath!.isNotEmpty;

  // Scoring failures are NOT verdicts on the paper -- the confidence model was
  // unreachable. The UI has to say so, or an admin reads it as a rejection.
  bool get isVerdict => decision != IngestDecision.scoringFailed;

  String get scoreLabel {
    if (score == null) return '—';
    return maxScore == null ? '$score' : '$score / $maxScore';
  }

  static IngestDecision decisionFrom(String? raw) {
    switch (raw) {
      case 'ready_to_extract':
        return IngestDecision.readyToExtract;
      case 'held_for_review':
        return IngestDecision.heldForReview;
      case 'rejected':
        return IngestDecision.rejected;
      case 'scoring_failed':
        return IngestDecision.scoringFailed;
      case 'extracting':
        return IngestDecision.extracting;
      case 'extracted':
        return IngestDecision.extracted;
      case 'extraction_failed':
        return IngestDecision.extractionFailed;
      default:
        return IngestDecision.unknown;
    }
  }

  factory IngestEntry.fromJson(Map<String, dynamic> json) {
    final rawReasons = json['reasons'];
    return IngestEntry(
      paper: json['paper']?.toString() ?? 'unknown',
      decision: decisionFrom(json['decision']?.toString()),
      score: json['score'] is num ? (json['score'] as num).toInt() : null,
      maxScore: json['max_score'] is num
          ? (json['max_score'] as num).toInt()
          : null,
      outcome: json['outcome']?.toString(),
      reasons: rawReasons is List
          ? rawReasons.map((r) => r.toString()).toList()
          : const [],
      storedPath: json['stored_path']?.toString(),
      at: json['at']?.toString(),
      triplesLoaded: json['triples_loaded'] is num
          ? (json['triples_loaded'] as num).toInt()
          : null,
      error: json['error']?.toString(),
    );
  }
}

// What the server says when it accepts an upload. The verdict is not known
// yet: scoring is an LLM job of minutes, so it runs in the background and the
// admin polls the queue.
class UploadAck {
  const UploadAck({required this.paper, required this.message});

  final String paper;
  final String message;
}

class AdminException implements Exception {
  const AdminException(this.message);

  final String message;

  @override
  String toString() => message;
}
