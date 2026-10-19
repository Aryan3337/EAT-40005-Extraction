import 'dart:convert';

import 'package:flutter_application/models/admin_audit.dart';
import 'package:flutter_application/services/admin_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  test('parses the overview and tolerates a missing graph', () {
    final full = AdminOverview.fromJson({
      'graph': {
        'nodes': 5,
        'relationships': 7,
        'archived': 1,
        'sources': [
          {'source': 'p.pdf', 'triples': 7},
        ],
      },
      'papers': {'MANUAL_APPROVED': 2},
      'recent_errors': [
        {'at': 't', 'type': 'auth.login', 'actor': 'a', 'outcome': 'failure'},
      ],
    });
    expect(full.relationships, 7);
    expect(full.sources.single.source, 'p.pdf');
    expect(full.papers['MANUAL_APPROVED'], 2);
    expect(full.recentErrors.single.failed, isTrue);

    final partial = AdminOverview.fromJson({'graph': null});
    expect(partial.nodes, isNull);
    expect(partial.recentErrors, isEmpty);
  });

  test('audit events keep extra fields as details', () {
    final event = AuditEvent.fromJson({
      'at': 't',
      'type': 'admin.paper_review',
      'actor': 'admin@x.com',
      'outcome': 'success',
      'paper': 'a.pdf',
    });
    expect(event.details, {'paper': 'a.pdf'});
    expect(event.failed, isFalse);
  });

  test('fetchAudit sends filters and the bearer token only', () async {
    final client = MockClient((request) async {
      expect(request.url.path, '/admin/audit');
      expect(request.url.queryParameters['type'], 'auth');
      expect(request.url.queryParameters['outcome'], 'failure');
      expect(request.headers['authorization'], 'Bearer tok');
      return http.Response(
        jsonEncode({
          'events': [
            {'at': 't', 'type': 'auth.login', 'actor': 'a', 'outcome': 'failure'},
          ],
        }),
        200,
      );
    });
    final service = AdminService(
      client: client,
      endpoint: 'http://localhost',
      secret: 's',
      authToken: 'tok',
    );
    final events = await service.fetchAudit(type: 'auth', outcome: 'failure');
    expect(events.single.type, 'auth.login');
  });
}
