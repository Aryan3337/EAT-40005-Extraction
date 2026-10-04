import 'package:flutter/material.dart';

class AppLocalizations {
  const AppLocalizations(this.languageCode);

  final String languageCode;

  static const supportedLanguageCodes = ['en', 'hi'];

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
  };

  String text(String key) {
    final translations = languageCode == 'hi' ? _hindi : _english;
    return translations[key] ?? _english[key] ?? key;
  }

  String get languageName => languageCode == 'hi' ? 'हिन्दी' : 'English';
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
      itemBuilder: (context) => const [
        PopupMenuItem(value: 'en', child: Text('English')),
        PopupMenuItem(value: 'hi', child: Text('हिन्दी')),
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
