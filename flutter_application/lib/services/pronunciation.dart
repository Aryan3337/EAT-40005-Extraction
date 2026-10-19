/// Respellings that make speech engines pronounce hard words correctly.
///
/// Only the text sent to the voice is changed; what is shown on screen and
/// copied stays as written. Bangla voices often misread হ + য-ফলা (হ্য),
/// which is spoken as "জ্ঝ" (ঐতিহ্য is said "ওইতিজ্ঝো"), so those words are
/// respelled the way they sound. Add a word here when a voice gets it wrong:
/// longer forms (ঐতিহ্যগত) before shorter ones (ঐতিহ্য).
library;

const banglaPronunciations = <String, String>{
  'ঐতিহ্যগতভাবে': 'ওইতিজ্ঝোগতোভাবে',
  'ঐতিহ্যগত': 'ওইতিজ্ঝোগতো',
  'ঐতিহ্যবাহী': 'ওইতিজ্ঝোবাহী',
  'ঐতিহ্যের': 'ওইতিজ্ঝের',
  'ঐতিহ্য': 'ওইতিজ্ঝো',
  'সহ্য': 'শোজ্ঝো',
  'বাহ্যিক': 'বাজ্ঝিক',
  'গ্রাহ্য': 'গ্রাজ্ঝো',
};

/// Returns [text] respelled for a voice speaking [locale] (e.g. "bn-BD").
String forSpeech(String text, String locale) {
  if (!locale.toLowerCase().startsWith('bn')) return text;
  var spoken = text;
  for (final entry in banglaPronunciations.entries) {
    spoken = spoken.replaceAll(entry.key, entry.value);
  }
  return spoken;
}
