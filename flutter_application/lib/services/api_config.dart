import 'package:flutter/foundation.dart';

// The RAG.py API's base URL, no trailing slash and no path.
//
// --dart-define=API_BASE_URL=https://... at build time points a hosted
// build at the hosted API. Omitted (every build before this one, and every
// local `flutter run`), it falls back to whichever loopback address
// reaches a rag.py --serve running on the same machine.
const String _configuredApiBaseUrl = String.fromEnvironment('API_BASE_URL');

String get apiBaseUrl {
  if (_configuredApiBaseUrl.isNotEmpty) {
    return _configuredApiBaseUrl;
  }
  // The Android emulator's loopback is its own, not the host machine's.
  if (defaultTargetPlatform == TargetPlatform.android) {
    return 'http://10.0.2.2:8000';
  }
  return 'http://127.0.0.1:8000';
}
