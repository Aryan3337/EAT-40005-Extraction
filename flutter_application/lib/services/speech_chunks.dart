/// Splits an answer into short pieces that speech engines read reliably.
///
/// flutter_tts and the browser's Web Speech API truncate or garble a long
/// answer passed as one utterance (Chrome stops after about 15 seconds), so
/// answers are read one sentence at a time. Pieces end after a sentence
/// mark (Bangla/Hindi দাঁড়ি "।", ".", "!", "?") or a line break. A sentence
/// longer than [maxLength] is split at a comma or space. No characters are
/// dropped: joining the pieces gives back all of the original text apart
/// from whitespace at the cut points.
library;

const _sentenceEnds = '।॥.!?';

List<String> speechChunks(String text, {int maxLength = 200}) {
  if (maxLength < 2) throw ArgumentError.value(maxLength, 'maxLength');
  final sentences = <String>[];
  final current = StringBuffer();

  void flush() {
    final sentence = current.toString().trim();
    if (sentence.isNotEmpty) sentences.add(sentence);
    current.clear();
  }

  for (var i = 0; i < text.length; i++) {
    final char = text[i];
    if (char == '\n') {
      flush();
      continue;
    }
    current.write(char);
    final next = i + 1 < text.length ? text[i + 1] : '';
    // "0.5" or "e.g." mid-word is not the end of a sentence.
    if (_sentenceEnds.contains(char) && (next.isEmpty || next.trim().isEmpty)) {
      flush();
    }
  }
  flush();

  final chunks = <String>[];
  for (var sentence in sentences) {
    while (sentence.length > maxLength) {
      final window = sentence.substring(0, maxLength);
      var cut = window.lastIndexOf(RegExp(r'[,،;:]\s'));
      cut = cut > 0 ? cut + 1 : window.lastIndexOf(' ');
      if (cut <= 0) cut = maxLength;
      // Do not split a UTF-16 surrogate pair (e.g. an emoji).
      final unit = sentence.codeUnitAt(cut - 1);
      if (unit >= 0xD800 && unit <= 0xDBFF && cut > 1) cut--;
      chunks.add(sentence.substring(0, cut).trim());
      sentence = sentence.substring(cut).trim();
    }
    if (sentence.isNotEmpty) chunks.add(sentence);
  }
  return chunks;
}
