import 'package:flutter/material.dart';

class AppLocalizations {
  const AppLocalizations(this.languageCode);

  final String languageCode;

  static const supportedLanguageCodes = ['en', 'hi', 'bn'];

  static const languageNames = <String, String>{
    'en': 'English',
    'hi': 'हिन्दी',
    'bn': 'বাংলা',
  };

  static const _english = <String, String>{
    'language': 'Language',
    'appTagline': 'Ask about culture, climate & community',
    'welcomeBack': 'Welcome back',
    'createAccount': 'Create your account',
    'loginDescription': 'Sign in to continue exploring the knowledge graph.',
    'registerDescription': 'Create an account to continue.',
    'needAccount': 'Need an account? Create one',
    'alreadyHaveAccount': 'Already have an account? Sign in',
    'usernameEmail': 'Username / Email',
    'enterUsername': 'Enter a username or email',
    'enterEmail': 'Enter a valid email address',
    'password': 'Password',
    'enterPassword': 'Enter a password',
    'passwordTooShort': 'Password must be at least 8 characters',
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
    'tryThese': 'Try these questions',
    'verifiedSources': 'Verified sources',
    'responseHelpful': 'Was this response helpful?',
    'helpful': 'Helpful',
    'notHelpful': 'Not helpful',
    'addComment': 'Add a comment',
    'editComment': 'Edit comment',
    'feedbackThanks': 'Thanks for your feedback',
    'commentLabel': 'Comment',
    'chooseFeedback': 'Choose whether this response was helpful.',
    'responseFeedback': 'Response feedback',
    'improveResponse': 'How could this response be improved?',
    'cancel': 'Cancel',
    'saveFeedback': 'Save feedback',
    'feedbackHistory': 'My feedback',
    'feedbackApproved': 'Reviewed: accepted',
    'feedbackDismissed': 'Reviewed: dismissed',
    'deleteFeedbackItem': 'Delete this feedback',
    'noFeedbackYet': 'Your response ratings and comments will appear here.',
    'clearHistory': 'Clear history',
    'clearFeedback': 'Clear feedback',
    'confirmClearHistory': 'Delete all of your chat history?',
    'confirmClearFeedback': 'Delete all of your feedback?',
    'source': 'Source {number}',
    'section': 'Section',
    'knowledgeGraph': 'Knowledge graph',
    'confidence': 'Confidence',
    'listening': 'Listening...',
    'stopListening': 'Stop listening',
    'askByVoice': 'Ask by voice',
    'readAloud': 'Read aloud',
    'stopReading': 'Stop reading',
    'noAnswer': 'No answer was returned.',
    'ragHttpError': 'RAG request failed (HTTP {status}): {error}',
    'cannotReachRag': 'Cannot reach the RAG service at {endpoint}.',
    'checkBackend': 'Check the backend',
    'speechVoiceUnavailable': 'No {language} voice was found on this device. Install or enable one in speech settings.',
    'speechError': 'Could not read this answer aloud: {error}',
  };

  static const _hindi = <String, String>{
    'language': 'भाषा',
    'appTagline': 'संस्कृति, जलवायु और समुदाय के बारे में पूछें',
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
    'thinking': 'सोच रहा है...',
    'sendQuestion': 'सवाल भेजें',
    'tryThese': 'इन सवालों को पूछें',
    'verifiedSources': 'सत्यापित स्रोत',
    'responseHelpful': 'क्या यह जवाब उपयोगी था?',
    'helpful': 'उपयोगी',
    'notHelpful': 'उपयोगी नहीं',
    'addComment': 'टिप्पणी जोड़ें',
    'editComment': 'टिप्पणी बदलें',
    'feedbackThanks': 'आपकी प्रतिक्रिया के लिए धन्यवाद',
    'commentLabel': 'टिप्पणी',
    'chooseFeedback': 'बताएँ कि यह जवाब उपयोगी था या नहीं।',
    'responseFeedback': 'जवाब पर प्रतिक्रिया',
    'improveResponse': 'इस जवाब को कैसे बेहतर बनाया जा सकता है?',
    'cancel': 'रद्द करें',
    'saveFeedback': 'प्रतिक्रिया सहेजें',
    'source': 'स्रोत {number}',
    'section': 'अनुभाग',
    'knowledgeGraph': 'ज्ञान ग्राफ़',
    'confidence': 'विश्वसनीयता',
    'listening': 'सुन रहा है...',
    'stopListening': 'सुनना बंद करें',
    'askByVoice': 'आवाज़ से पूछें',
    'readAloud': 'ज़ोर से पढ़ें',
    'stopReading': 'पढ़ना बंद करें',
    'noAnswer': 'कोई जवाब नहीं मिला।',
    'ragHttpError': 'RAG अनुरोध विफल (HTTP {status}): {error}',
    'cannotReachRag': 'RAG सेवा तक पहुँचा नहीं जा सका: {endpoint}।',
    'checkBackend': 'बैकएंड जाँचें',
    'speechVoiceUnavailable': 'इस डिवाइस पर {language} आवाज़ नहीं मिली। वाक् सेटिंग में इसे इंस्टॉल या चालू करें।',
    'speechError': 'इस जवाब को ज़ोर से नहीं पढ़ा जा सका: {error}',
  };

  static const _bangla = <String, String>{
    'language': 'ভাষা',
    'appTagline': 'সংস্কৃতি, জলবায়ু ও সম্প্রদায় সম্পর্কে জিজ্ঞাসা করুন',
    'welcomeBack': 'আবারও স্বাগতম',
    'loginDescription': 'জ্ঞান গ্রাফ দেখতে সাইন ইন করুন।',
    'usernameEmail': 'ব্যবহারকারীর নাম / ইমেইল',
    'enterUsername': 'ব্যবহারকারীর নাম বা ইমেইল লিখুন',
    'password': 'পাসওয়ার্ড',
    'enterPassword': 'পাসওয়ার্ড লিখুন',
    'showPassword': 'পাসওয়ার্ড দেখান',
    'hidePassword': 'পাসওয়ার্ড লুকান',
    'keepSignedIn': 'সাইন ইন অবস্থায় রাখুন',
    'signIn': 'সাইন ইন',
    'loginFooter': 'চালিয়ে যেতে আপনার কর্মক্ষেত্রের পরিচয়পত্র ব্যবহার করুন।',
    'invalidCredentials': 'লগইনের তথ্য সঠিক নয়। আবার চেষ্টা করুন।',
    'chatHistory': 'চ্যাটের ইতিহাস',
    'newChat': 'নতুন চ্যাট',
    'signOut': 'সাইন আউট',
    'savedConversations': 'আপনার সংরক্ষিত কথোপকথন এখানে দেখা যাবে।',
    'deleteConversation': 'কথোপকথন মুছুন',
    'askAnything': 'যেকোনো প্রশ্ন করুন',
    'thinking': 'ভাবছে...',
    'sendQuestion': 'প্রশ্ন পাঠান',
    'tryThese': 'এই প্রশ্নগুলো করতে পারেন',
    'verifiedSources': 'যাচাইকৃত সূত্র',
    'responseHelpful': 'এই উত্তরটি কি সহায়ক ছিল?',
    'helpful': 'সহায়ক',
    'notHelpful': 'সহায়ক নয়',
    'addComment': 'মন্তব্য যোগ করুন',
    'editComment': 'মন্তব্য সম্পাদনা করুন',
    'feedbackThanks': 'আপনার মতামতের জন্য ধন্যবাদ',
    'commentLabel': 'মন্তব্য',
    'chooseFeedback': 'উত্তরটি সহায়ক ছিল কি না জানান।',
    'responseFeedback': 'উত্তর সম্পর্কে মতামত',
    'improveResponse': 'এই উত্তরটি কীভাবে আরও ভালো করা যায়?',
    'cancel': 'বাতিল',
    'saveFeedback': 'মতামত সংরক্ষণ করুন',
    'source': 'সূত্র {number}',
    'section': 'বিভাগ',
    'knowledgeGraph': 'জ্ঞান গ্রাফ',
    'confidence': 'নির্ভরযোগ্যতা',
    'listening': 'শুনছে...',
    'stopListening': 'শোনা বন্ধ করুন',
    'askByVoice': 'কথা বলে প্রশ্ন করুন',
    'readAloud': 'জোরে পড়ুন',
    'stopReading': 'পড়া বন্ধ করুন',
    'noAnswer': 'কোনো উত্তর পাওয়া যায়নি।',
    'ragHttpError': 'RAG অনুরোধ ব্যর্থ হয়েছে (HTTP {status}): {error}',
    'cannotReachRag': 'RAG পরিষেবায় পৌঁছানো যাচ্ছে না: {endpoint}।',
    'checkBackend': 'ব্যাকএন্ড পরীক্ষা করুন',
    'speechVoiceUnavailable': 'এই ডিভাইসে {language} কণ্ঠস্বর পাওয়া যায়নি। স্পিচ সেটিংসে এটি ইনস্টল বা চালু করুন।',
    'speechError': 'উত্তরটি জোরে পড়া যায়নি: {error}',
  };

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
