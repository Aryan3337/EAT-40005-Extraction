import 'dart:js_interop';
import 'dart:typed_data';

import 'package:web/web.dart' as web;

// Opens a PDF the app already holds in memory, in a new browser tab.
//
// The bytes are fetched with the admin secret in a header and turned into a
// blob URL here, rather than pointing the browser straight at
// /admin/paper?name=... A plain link cannot carry a header, so that approach
// would mean putting the secret in the URL, where it lands in browser history,
// server logs and the Referer header.
Future<void> openPdfInNewTab(String filename, Uint8List bytes) async {
  final blob = web.Blob(
    [bytes.toJS].toJS,
    web.BlobPropertyBag(type: 'application/pdf'),
  );
  final url = web.URL.createObjectURL(blob);
  web.window.open(url, '_blank');

  // The new tab needs the URL to still resolve when it loads, so this is
  // revoked on a delay rather than immediately. The browser reclaims it on
  // unload regardless.
  Future.delayed(const Duration(minutes: 2), () => web.URL.revokeObjectURL(url));
}
