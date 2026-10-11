import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import '../models/ingest_entry.dart';
import 'api_config.dart';

// Talks to rag.py's admin endpoints.
//
// The admin role in AuthService only decides which buttons render. This secret
// is what actually authorises the request: the server checks it with a
// constant-time compare and refuses when it is unset, so a deployment that
// forgot to configure one has the endpoints disabled rather than open.
class AdminService {
  AdminService({http.Client? client, String? endpoint, required this.secret})
    : endpoint = endpoint ?? apiBaseUrl,
      _client = client ?? http.Client();

  final http.Client _client;
  final String endpoint;
  final String secret;

  Map<String, String> get _authHeaders => {'X-Admin-Secret': secret};

  // Sends the PDF as the raw request body with its name in a header. Raw bytes
  // rather than multipart because the stdlib module that parsed multipart was
  // removed in Python 3.13, and this is just as easy from here.
  //
  // Returns as soon as the server accepts it. The verdict is NOT known yet --
  // scoring takes minutes, so it runs server-side in the background and the
  // caller polls fetchQueue().
  Future<UploadAck> uploadPdf({
    required Uint8List bytes,
    required String filename,
  }) async {
    http.Response response;
    try {
      response = await _client.post(
        Uri.parse('${endpoint.replaceAll(RegExp(r'/$'), '')}/admin/upload'),
        headers: {..._authHeaders, 'X-Filename': filename},
        body: bytes,
      );
    } catch (_) {
      throw AdminException(
        'Cannot reach the API at $endpoint. Start it with '
        '"python rag.py --serve" and try again.',
      );
    }

    if (response.statusCode == 202) {
      final payload = _decode(response.body);
      return UploadAck(
        paper: payload['paper']?.toString() ?? filename,
        message: payload['message']?.toString() ?? 'Upload accepted.',
      );
    }
    throw AdminException(_errorFor(response));
  }

  Future<List<IngestEntry>> fetchQueue() async {
    http.Response response;
    try {
      response = await _client.get(
        Uri.parse('${endpoint.replaceAll(RegExp(r'/$'), '')}/admin/queue'),
        headers: _authHeaders,
      );
    } catch (_) {
      throw AdminException(
        'Cannot reach the API at $endpoint. Start it with '
        '"python rag.py --serve" and try again.',
      );
    }

    if (response.statusCode != 200) {
      throw AdminException(_errorFor(response));
    }

    final payload = _decode(response.body);
    final rows = payload['queue'];
    if (rows is! List) return const [];

    // Newest first: an admin who just uploaded wants to see that row.
    return rows
        .whereType<Map>()
        .map((row) => IngestEntry.fromJson(Map<String, dynamic>.from(row)))
        .toList()
        .reversed
        .toList();
  }

  // The stored PDF, so a reviewer can read what they are judging. The paper
  // name travels in the query string -- it is not sensitive -- while the
  // secret stays in a header.
  Future<Uint8List> fetchPaper(String paper) async {
    final uri = Uri.parse('${endpoint.replaceAll(RegExp(r'/$'), '')}/admin/paper')
        .replace(queryParameters: {'name': paper});

    http.Response response;
    try {
      response = await _client.get(uri, headers: _authHeaders);
    } catch (_) {
      throw AdminException(
        'Cannot reach the API at $endpoint. Start it with '
        '"python rag.py --serve" and try again.',
      );
    }

    if (response.statusCode == 404) {
      throw const AdminException(
        'That paper is not stored on the server, so there is nothing to show. '
        'An automatically rejected paper is never kept.',
      );
    }
    if (response.statusCode != 200) {
      throw AdminException(_errorFor(response));
    }
    return response.bodyBytes;
  }

  // Records a person's approve/reject on a paper held for review. The server
  // appends it rather than replacing the machine verdict, so the audit trail
  // keeps both.
  Future<void> submitReview(String paper, {required bool approve, String? note}) async {
    http.Response response;
    try {
      response = await _client.post(
        Uri.parse('${endpoint.replaceAll(RegExp(r'/$'), '')}/admin/review'),
        headers: {..._authHeaders, 'Content-Type': 'application/json'},
        body: jsonEncode({
          'paper': paper,
          'approve': approve,
          if (note != null && note.trim().isNotEmpty) 'note': note.trim(),
        }),
      );
    } catch (_) {
      throw AdminException(
        'Cannot reach the API at $endpoint. Start it with '
        '"python rag.py --serve" and try again.',
      );
    }

    if (response.statusCode != 200) {
      throw AdminException(_errorFor(response));
    }
  }

  Map<String, dynamic> _decode(String body) {
    try {
      final decoded = jsonDecode(body);
      return decoded is Map ? Map<String, dynamic>.from(decoded) : {};
    } catch (_) {
      return {};
    }
  }

  // Turns a status code into something an admin can act on, preferring the
  // server's own message when it sent one.
  String _errorFor(http.Response response) {
    final serverMessage = _decode(response.body)['error']?.toString();

    switch (response.statusCode) {
      case 401:
        return serverMessage ??
            'The admin secret was missing or incorrect. It must match '
                'ADMIN_UPLOAD_SECRET on the server.';
      case 503:
        return serverMessage ??
            'Admin uploads are disabled: ADMIN_UPLOAD_SECRET is not set on '
                'the server. Set it in .env and restart the API.';
      case 413:
        return serverMessage ?? 'That file is too large to upload.';
      case 400:
        return serverMessage ?? 'The server rejected that file.';
      default:
        return serverMessage ??
            'The server returned HTTP ${response.statusCode}.';
    }
  }
}
