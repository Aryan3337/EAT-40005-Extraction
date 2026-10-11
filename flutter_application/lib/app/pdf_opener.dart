// Picks the right PDF opener for the platform being built.
//
// package:web and dart:js_interop exist only on the web, and `flutter test`
// runs on the Dart VM -- so importing the web version unconditionally makes
// every test that pumps KnowledgeGraphApp fail to compile, which is exactly
// what happened. The conditional export keeps app.dart's import simple while
// the VM gets a do-nothing stub.
//
// file_picker needed no equivalent because it ships its own VM-safe stub.
export 'pdf_opener_stub.dart'
    if (dart.library.js_interop) 'pdf_opener_web.dart';
