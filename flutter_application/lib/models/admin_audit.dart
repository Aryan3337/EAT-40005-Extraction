// One line of the server's audit log.
class AuditEvent {
  const AuditEvent({
    required this.at,
    required this.type,
    required this.actor,
    required this.outcome,
    required this.details,
  });

  final String at;
  final String type;
  final String actor;
  final String outcome;
  final Map<String, String> details;

  bool get failed => outcome == 'failure' || outcome == 'error';

  factory AuditEvent.fromJson(Map<String, dynamic> json) {
    const known = {'at', 'type', 'actor', 'outcome'};
    final details = <String, String>{};
    for (final entry in json.entries) {
      if (known.contains(entry.key) || entry.value == null) continue;
      details[entry.key] = entry.value.toString();
    }
    return AuditEvent(
      at: json['at']?.toString() ?? '',
      type: json['type']?.toString() ?? '',
      actor: json['actor']?.toString() ?? '',
      outcome: json['outcome']?.toString() ?? 'success',
      details: details,
    );
  }
}

class SourceCount {
  const SourceCount({required this.source, required this.triples});

  final String source;
  final int triples;
}

// The numbers behind the admin dashboard. [graph] fields are null when the
// graph could not be reached, so the rest of the dashboard still renders.
class AdminOverview {
  const AdminOverview({
    this.nodes,
    this.relationships,
    this.archived,
    this.sources = const [],
    this.papers = const {},
    this.recentErrors = const [],
  });

  final int? nodes;
  final int? relationships;
  final int? archived;
  final List<SourceCount> sources;
  final Map<String, int> papers;
  final List<AuditEvent> recentErrors;

  factory AdminOverview.fromJson(Map<String, dynamic> json) {
    int? number(dynamic value) =>
        value is num ? value.toInt() : int.tryParse('$value');

    final graph = json['graph'];
    final graphMap = graph is Map ? Map<String, dynamic>.from(graph) : null;
    final rawSources = graphMap?['sources'];
    final rawPapers = json['papers'];
    final rawErrors = json['recent_errors'];

    return AdminOverview(
      nodes: number(graphMap?['nodes']),
      relationships: number(graphMap?['relationships']),
      archived: number(graphMap?['archived']),
      sources: rawSources is List
          ? rawSources.whereType<Map>().map((row) {
              return SourceCount(
                source: row['source']?.toString() ?? 'unknown',
                triples: number(row['triples']) ?? 0,
              );
            }).toList()
          : const [],
      papers: rawPapers is Map
          ? {
              for (final entry in rawPapers.entries)
                entry.key.toString(): number(entry.value) ?? 0,
            }
          : const {},
      recentErrors: rawErrors is List
          ? rawErrors
                .whereType<Map>()
                .map((e) => AuditEvent.fromJson(Map<String, dynamic>.from(e)))
                .toList()
          : const [],
    );
  }
}
