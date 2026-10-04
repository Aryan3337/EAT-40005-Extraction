import 'package:file_picker/file_picker.dart';

import '../features/admin/admin_page.dart';

// The ONLY file in the app that imports file_picker.
//
// Kept isolated on purpose: AdminPage takes its picker as an injected
// callback, so the screen and all of its tests work without this package. If
// `flutter pub get` cannot resolve file_picker, comment out this file's import
// and the `pickPdf: pickPdfFile` line in app.dart, and everything except
// choosing a file still builds and runs.
Future<PickedPdf?> pickPdfFile() async {
  final result = await FilePicker.platform.pickFiles(
    type: FileType.custom,
    allowedExtensions: const ['pdf'],
    // The bytes are what gets POSTed, and on web there is no path to read
    // from, so ask for the data itself.
    withData: true,
  );

  final files = result?.files ?? const [];
  if (files.isEmpty) return null;

  final file = files.first;
  final bytes = file.bytes;
  if (bytes == null) return null;

  return PickedPdf(filename: file.name, bytes: bytes);
}
