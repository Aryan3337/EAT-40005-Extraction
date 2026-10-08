import 'package:flutter/material.dart';

class AppLocalizations {
  const AppLocalizations(this.languageCode);

  final String languageCode;

  static const supportedLanguageCodes = ['en', 'hi', 'bn'];

  static const _english = <String, String>{
    'language': 'Language',
    'welcomeBack': 'Welcome back',
    'loginDescription': 'Sign in to continue exploring the knowledge graph.',
    'usernameEmail': 'Username / Email',
    'enterUsername': 'Enter a username or email',
    'password': 'Password',
    'enterPassword': 'Enter a password',
    'showPassword': 'Show password',
    'hidePassword': 'Hide password',
    'keepSignedIn': 'Keep me signed in',
    'signIn': 'Sign in',
    'loginFooter': 'Use your workspace credentials to continue.',
    'invalidCredentials': 'Invalid credentials. Please try again.',
    'chatHistory': 'Chat history',
    'newChat': 'New chat',
    'signOut': 'Sign out',
    'savedConversations': 'Your saved conversations will appear here.',
    'deleteConversation': 'Delete conversation',
    'askAnything': 'Ask me anything',
    'thinking': 'Thinking ...',
    'sendQuestion': 'Send question',
    'tryThese': 'Try one of these, or type your own question below.',
  };

  static const _hindi = <String, String>{
    'language': 'भाषा',
    'welcomeBack': 'वापसी पर स्वागत है',
    'loginDescription': 'ज्ञान ग्राफ़ को जानने के लिए साइन इन करें।',
    'usernameEmail': 'उपयोगकर्ता नाम / ईमेल',
    'enterUsername': 'उपयोगकर्ता नाम या ईमेल दर्ज करें',
    'password': 'पासवर्ड',
    'enterPassword': 'पासवर्ड दर्ज करें',
    'showPassword': 'पासवर्ड दिखाएँ',
    'hidePassword': 'पासवर्ड छिपाएँ',
    'keepSignedIn': 'मुझे साइन इन रखें',
    'signIn': 'साइन इन',
    'loginFooter':
        'जारी रखने के लिए अपने कार्यक्षेत्र के क्रेडेंशियल इस्तेमाल करें।',
    'invalidCredentials': 'लॉगिन विवरण गलत हैं। फिर से प्रयास करें।',
    'chatHistory': 'चैट इतिहास',
    'newChat': 'नई चैट',
    'signOut': 'साइन आउट',
    'savedConversations': 'आपकी सहेजी गई बातचीत यहाँ दिखाई देगी।',
    'deleteConversation': 'बातचीत हटाएँ',
    'askAnything': 'मुझसे कुछ भी पूछें',
    'thinking': 'सोच रहा है ...',
    'sendQuestion': 'सवाल भेजें',
    'tryThese': 'इनमें से कोई एक आज़माएँ, या नीचे अपना सवाल लिखें।',
  };

  static const _bangla = <String, String>{
    'language': 'ভাষা',
    'welcomeBack': 'আবার স্বাগতম',
    'loginDescription': 'জ্ঞান গ্রাফ ঘুরে দেখতে সাইন ইন করুন।',
    'usernameEmail': 'ব্যবহারকারীর নাম / ইমেইল',
    'enterUsername': 'ব্যবহারকারীর নাম বা ইমেইল লিখুন',
    'password': 'পাসওয়ার্ড',
    'enterPassword': 'পাসওয়ার্ড লিখুন',
    'showPassword': 'পাসওয়ার্ড দেখান',
    'hidePassword': 'পাসওয়ার্ড লুকান',
    'keepSignedIn': 'আমাকে সাইন ইন রাখুন',
    'signIn': 'সাইন ইন',
    'loginFooter': 'চালিয়ে যেতে আপনার ওয়ার্কস্পেসের তথ্য ব্যবহার করুন।',
    'invalidCredentials': 'লগইন তথ্য সঠিক নয়। আবার চেষ্টা করুন।',
    'chatHistory': 'চ্যাটের ইতিহাস',
    'newChat': 'নতুন চ্যাট',
    'signOut': 'সাইন আউট',
    'savedConversations': 'আপনার সংরক্ষিত কথোপকথন এখানে দেখা যাবে।',
    'deleteConversation': 'কথোপকথন মুছুন',
    'askAnything': 'আমাকে যেকোনো কিছু জিজ্ঞাসা করুন',
    'thinking': 'ভাবছি ...',
    'sendQuestion': 'প্রশ্ন পাঠান',
    'tryThese': 'এগুলোর একটি চেষ্টা করুন, অথবা নিচে আপনার প্রশ্ন লিখুন।',
  };

  // Display names, in each language's own script, for the picker.
  static const languageNames = <String, String>{
    'en': 'English',
    'hi': 'हिन्दी',
    'bn': 'বাংলা',
  };

  // Locale for voice input (speech_to_text uses underscores).
  String get speechLocaleId => const {
    'en': 'en_US',
    'hi': 'hi_IN',
    'bn': 'bn_BD',
  }[languageCode] ?? 'en_US';

  // Language for reading answers aloud (flutter_tts uses hyphens).
  String get ttsLanguage => const {
    'en': 'en-US',
    'hi': 'hi-IN',
    'bn': 'bn-BD',
  }[languageCode] ?? 'en-US';

  String text(String key) {
    final translations = switch (languageCode) {
      'hi' => _hindi,
      'bn' => _bangla,
      _ => _english,
    };
    return translations[key] ?? _english[key] ?? key;
  }

  String get languageName => languageNames[languageCode] ?? 'English';
}

class LanguagePicker extends StatelessWidget {
  const LanguagePicker({
    super.key,
    required this.strings,
    required this.onChanged,
  });

  final AppLocalizations strings;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    return PopupMenuButton<String>(
      tooltip: strings.text('language'),
      onSelected: onChanged,
      itemBuilder: (context) => [
        for (final code in AppLocalizations.supportedLanguageCodes)
          PopupMenuItem(
            value: code,
            child: Text(AppLocalizations.languageNames[code]!),
          ),
      ],
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 10),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.translate, size: 20),
            const SizedBox(width: 6),
            Text(strings.languageName),
          ],
        ),
      ),
    );
  }
}
