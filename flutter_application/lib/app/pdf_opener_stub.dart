import 'dart:typed_data';

// The non-web build. Opening a PDF in a new tab is a browser idea, and
// package:web cannot compile off the web -- which includes `flutter test`,
// since that runs on the Dart VM.
//
// This does nothing rather than throwing: AdminPage only calls its viewer
// after the admin presses "View paper", and failing loudly there would be
// worse than the button simply being unavailable. The real fix for a desktop
// or mobile build is to write the bytes to a temporary file and hand them to
// the platform's own PDF handler.
Future<void> openPdfInNewTab(String filename, Uint8List bytes) async {}
