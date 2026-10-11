import 'package:flutter/material.dart';

class AppLocalizations {
  const AppLocalizations(this.languageCode);

  final String languageCode;

  static const supportedLanguageCodes = ['en', 'es', 'fr', 'hi', 'zh'];

  static const _english = <String, String>{
    'language': 'Language',
    'appTagline': 'Ask about culture, climate & community',
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
    'autoReadOn': 'Auto read-aloud is on: tap to turn off',
    'autoReadOff': 'Auto read-aloud is off: tap to turn on',
    'trySuggested': 'Try one of these, or type your own question below.',
    'promptPlants':
        'What plants do the Garo people use for traditional medicine?',
    'promptClimate': 'How is climate change affecting indigenous communities?',
    'promptMatrilineal':
        "Tell me about the Garo people's matrilineal social system.",
    'stopReading': 'Stop reading aloud',
    'readAloud': 'Read aloud',
    'verifiedSources': 'View verified sources ({count})',
    'responseHelpful': 'Was this response helpful?',
    'helpful': 'Helpful',
    'notHelpful': 'Not helpful',
    'addComment': 'Add comment',
    'editComment': 'Edit comment',
    'feedbackThanks': 'Thank you for your feedback.',
    'commentLabel': 'Comment: {comment}',
    'chooseFeedback': 'Please select helpful or not helpful first.',
    'responseFeedback': 'Response feedback',
    'improveResponse': 'Tell us how this response could be improved.',
    'cancel': 'Cancel',
    'saveFeedback': 'Save feedback',
    'source': 'Source {number}',
    'section': 'Section: {section}',
    'knowledgeGraph': 'Knowledge graph: {triple}',
    'confidence': 'Confidence: {confidence}',
    'listening': 'Listening...',
    'stopListening': 'Stop listening',
    'askByVoice': 'Ask by voice',
    'cannotReachRag':
        'Cannot reach RAG.py at {endpoint}. Start the RAG API and try again.',
    'ragHttpError': 'RAG.py returned HTTP {status}: {error}',
    'checkBackend': 'Check the backend terminal.',
    'noAnswer': 'The graph returned no answer.',
  };

  static const _spanish = <String, String>{
    'language': 'Idioma',
    'appTagline': 'Pregunta sobre cultura, clima y comunidad',
    'welcomeBack': 'Te damos la bienvenida',
    'loginDescription':
        'Inicia sesión para seguir explorando el grafo de conocimiento.',
    'usernameEmail': 'Usuario / Correo electrónico',
    'enterUsername': 'Introduce un usuario o correo electrónico',
    'password': 'Contraseña',
    'enterPassword': 'Introduce una contraseña',
    'showPassword': 'Mostrar contraseña',
    'hidePassword': 'Ocultar contraseña',
    'keepSignedIn': 'Mantener la sesión iniciada',
    'signIn': 'Iniciar sesión',
    'loginFooter':
        'Usa las credenciales de tu espacio de trabajo para continuar.',
    'invalidCredentials': 'Credenciales no válidas. Inténtalo de nuevo.',
    'chatHistory': 'Historial de chat',
    'newChat': 'Nuevo chat',
    'signOut': 'Cerrar sesión',
    'savedConversations': 'Tus conversaciones guardadas aparecerán aquí.',
    'deleteConversation': 'Eliminar conversación',
    'askAnything': 'Pregúntame lo que quieras',
    'thinking': 'Pensando...',
    'sendQuestion': 'Enviar pregunta',
    'autoReadOn': 'Lectura automática activada: toca para desactivarla',
    'autoReadOff': 'Lectura automática desactivada: toca para activarla',
    'trySuggested': 'Prueba una de estas preguntas o escribe la tuya.',
    'promptPlants':
        '¿Qué plantas medicinales tradicionales usa el pueblo Garo?',
    'promptClimate':
        '¿Cómo afecta el cambio climático a las comunidades indígenas?',
    'promptMatrilineal':
        'Cuéntame sobre el sistema social matrilineal del pueblo Garo.',
    'stopReading': 'Detener lectura en voz alta',
    'readAloud': 'Leer en voz alta',
    'verifiedSources': 'Ver fuentes verificadas ({count})',
    'responseHelpful': '¿Te resultó útil esta respuesta?',
    'helpful': 'Útil',
    'notHelpful': 'No es útil',
    'addComment': 'Añadir comentario',
    'editComment': 'Editar comentario',
    'feedbackThanks': 'Gracias por tus comentarios.',
    'commentLabel': 'Comentario: {comment}',
    'chooseFeedback': 'Primero indica si la respuesta fue útil o no.',
    'responseFeedback': 'Comentarios sobre la respuesta',
    'improveResponse': 'Cuéntanos cómo podría mejorarse esta respuesta.',
    'cancel': 'Cancelar',
    'saveFeedback': 'Guardar comentarios',
    'source': 'Fuente {number}',
    'section': 'Sección: {section}',
    'knowledgeGraph': 'Grafo de conocimiento: {triple}',
    'confidence': 'Confianza: {confidence}',
    'listening': 'Escuchando...',
    'stopListening': 'Dejar de escuchar',
    'askByVoice': 'Preguntar por voz',
    'cannotReachRag': 'No se puede conectar con RAG.py en {endpoint}. Inicia la API e inténtalo de nuevo.',
    'ragHttpError': 'RAG.py devolvió HTTP {status}: {error}',
    'checkBackend': 'Revisa la terminal del backend.',
    'noAnswer': 'El grafo no devolvió ninguna respuesta.',
  };

  static const _french = <String, String>{
    'language': 'Langue',
    'appTagline':
        'Posez des questions sur la culture, le climat et la communauté',
    'welcomeBack': 'Bon retour',
    'loginDescription':
        'Connectez-vous pour continuer à explorer le graphe de connaissances.',
    'usernameEmail': 'Nom d’utilisateur / E-mail',
    'enterUsername': 'Saisissez un nom d’utilisateur ou un e-mail',
    'password': 'Mot de passe',
    'enterPassword': 'Saisissez un mot de passe',
    'showPassword': 'Afficher le mot de passe',
    'hidePassword': 'Masquer le mot de passe',
    'keepSignedIn': 'Rester connecté',
    'signIn': 'Se connecter',
    'loginFooter': 'Utilisez vos identifiants professionnels pour continuer.',
    'invalidCredentials': 'Identifiants incorrects. Veuillez réessayer.',
    'chatHistory': 'Historique des discussions',
    'newChat': 'Nouvelle discussion',
    'signOut': 'Se déconnecter',
    'savedConversations': 'Vos conversations enregistrées apparaîtront ici.',
    'deleteConversation': 'Supprimer la conversation',
    'askAnything': 'Posez-moi une question',
    'thinking': 'Réflexion...',
    'sendQuestion': 'Envoyer la question',
    'autoReadOn': 'Lecture automatique activée : appuyez pour désactiver',
    'autoReadOff': 'Lecture automatique désactivée : appuyez pour activer',
    'trySuggested': 'Essayez une question ci-dessous ou saisissez la vôtre.',
    'promptPlants':
        'Quelles plantes médicinales traditionnelles les Garo utilisent-ils ?',
    'promptClimate': 'Comment le changement climatique affecte-t-il les communautés autochtones ?',
    'promptMatrilineal': 'Parlez-moi du système social matrilinéaire des Garo.',
    'stopReading': 'Arrêter la lecture à voix haute',
    'readAloud': 'Lire à voix haute',
    'verifiedSources': 'Voir les sources vérifiées ({count})',
    'responseHelpful': 'Cette réponse vous a-t-elle été utile ?',
    'helpful': 'Utile',
    'notHelpful': 'Pas utile',
    'addComment': 'Ajouter un commentaire',
    'editComment': 'Modifier le commentaire',
    'feedbackThanks': 'Merci pour votre retour.',
    'commentLabel': 'Commentaire : {comment}',
    'chooseFeedback': 'Indiquez d’abord si cette réponse est utile ou non.',
    'responseFeedback': 'Avis sur la réponse',
    'improveResponse': 'Comment cette réponse pourrait-elle être améliorée ?',
    'cancel': 'Annuler',
    'saveFeedback': 'Enregistrer l’avis',
    'source': 'Source {number}',
    'section': 'Section : {section}',
    'knowledgeGraph': 'Graphe de connaissances : {triple}',
    'confidence': 'Confiance : {confidence}',
    'listening': 'Écoute en cours...',
    'stopListening': 'Arrêter l’écoute',
    'askByVoice': 'Poser une question à voix haute',
    'cannotReachRag': 'Impossible de joindre RAG.py à {endpoint}. Démarrez l’API et réessayez.',
    'ragHttpError': 'RAG.py a renvoyé HTTP {status} : {error}',
    'checkBackend': 'Vérifiez le terminal du backend.',
    'noAnswer': 'Le graphe n’a renvoyé aucune réponse.',
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
    'autoReadOn': 'स्वचालित रूप से पढ़ना चालू है: बंद करने के लिए टैप करें',
    'autoReadOff': 'स्वचालित रूप से पढ़ना बंद है: चालू करने के लिए टैप करें',
    'trySuggested': 'इनमें से कोई सवाल पूछें या अपना सवाल लिखें।',
    'promptPlants':
        'गारो लोग पारंपरिक चिकित्सा में किन पौधों का उपयोग करते हैं?',
    'promptClimate':
        'जलवायु परिवर्तन स्वदेशी समुदायों को कैसे प्रभावित कर रहा है?',
    'promptMatrilineal':
        'गारो लोगों की मातृवंशीय सामाजिक व्यवस्था के बारे में बताइए।',
    'stopReading': 'ज़ोर से पढ़ना बंद करें',
    'readAloud': 'ज़ोर से पढ़ें',
    'verifiedSources': 'सत्यापित स्रोत देखें ({count})',
    'responseHelpful': 'क्या यह जवाब उपयोगी था?',
    'helpful': 'उपयोगी',
    'notHelpful': 'उपयोगी नहीं',
    'addComment': 'टिप्पणी जोड़ें',
    'editComment': 'टिप्पणी संपादित करें',
    'feedbackThanks': 'आपकी प्रतिक्रिया के लिए धन्यवाद।',
    'commentLabel': 'टिप्पणी: {comment}',
    'chooseFeedback': 'पहले बताएं कि जवाब उपयोगी था या नहीं।',
    'responseFeedback': 'जवाब पर प्रतिक्रिया',
    'improveResponse': 'बताएं कि इस जवाब को कैसे बेहतर बनाया जा सकता है।',
    'cancel': 'रद्द करें',
    'saveFeedback': 'प्रतिक्रिया सहेजें',
    'source': 'स्रोत {number}',
    'section': 'अनुभाग: {section}',
    'knowledgeGraph': 'ज्ञान ग्राफ़: {triple}',
    'confidence': 'विश्वसनीयता: {confidence}',
    'listening': 'सुन रहा है...',
    'stopListening': 'सुनना बंद करें',
    'askByVoice': 'आवाज़ से पूछें',
    'cannotReachRag': '{endpoint} पर RAG.py से संपर्क नहीं हो पा रहा। API शुरू करके फिर प्रयास करें।',
    'ragHttpError': 'RAG.py ने HTTP {status} लौटाया: {error}',
    'checkBackend': 'बैकएंड टर्मिनल देखें।',
    'noAnswer': 'ग्राफ़ से कोई जवाब नहीं मिला।',
  };

  static const _chinese = <String, String>{
    'language': '语言',
    'appTagline': '询问文化、气候与社区',
    'welcomeBack': '欢迎回来',
    'loginDescription': '登录以继续探索知识图谱。',
    'usernameEmail': '用户名 / 电子邮箱',
    'enterUsername': '请输入用户名或电子邮箱',
    'password': '密码',
    'enterPassword': '请输入密码',
    'showPassword': '显示密码',
    'hidePassword': '隐藏密码',
    'keepSignedIn': '保持登录状态',
    'signIn': '登录',
    'loginFooter': '使用工作区凭据继续。',
    'invalidCredentials': '凭据无效，请重试。',
    'chatHistory': '聊天记录',
    'newChat': '新建聊天',
    'signOut': '退出登录',
    'savedConversations': '已保存的对话会显示在这里。',
    'deleteConversation': '删除对话',
    'askAnything': '有什么问题都可以问我',
    'thinking': '正在思考...',
    'sendQuestion': '发送问题',
    'autoReadOn': '自动朗读已开启：点击关闭',
    'autoReadOff': '自动朗读已关闭：点击开启',
    'trySuggested': '试试下面的问题，或输入你自己的问题。',
    'promptPlants': '加罗人使用哪些传统药用植物？',
    'promptClimate': '气候变化如何影响原住民社区？',
    'promptMatrilineal': '请介绍加罗人的母系社会制度。',
    'stopReading': '停止朗读',
    'readAloud': '朗读',
    'verifiedSources': '查看已验证来源（{count}）',
    'responseHelpful': '这个回答有帮助吗？',
    'helpful': '有帮助',
    'notHelpful': '没有帮助',
    'addComment': '添加评论',
    'editComment': '编辑评论',
    'feedbackThanks': '感谢你的反馈。',
    'commentLabel': '评论：{comment}',
    'chooseFeedback': '请先选择回答是否有帮助。',
    'responseFeedback': '回答反馈',
    'improveResponse': '请告诉我们如何改进这个回答。',
    'cancel': '取消',
    'saveFeedback': '保存反馈',
    'source': '来源 {number}',
    'section': '章节：{section}',
    'knowledgeGraph': '知识图谱：{triple}',
    'confidence': '置信度：{confidence}',
    'listening': '正在聆听...',
    'stopListening': '停止聆听',
    'askByVoice': '语音提问',
    'cannotReachRag': '无法连接 {endpoint} 上的 RAG.py。请启动 API 后重试。',
    'ragHttpError': 'RAG.py 返回 HTTP {status}：{error}',
    'checkBackend': '请检查后端终端。',
    'noAnswer': '知识图谱未返回答案。',
  };

  static const _translations = <String, Map<String, String>>{
    'en': _english,
    'es': _spanish,
    'fr': _french,
    'hi': _hindi,
    'zh': _chinese,
  };

  static const languageNames = <String, String>{
    'en': 'English',
    'es': 'Español (Spanish)',
    'fr': 'Français(French)',
    'hi': 'हिन्दी (Hindi)',
    'zh': '中文（Mandarin Chinese)',
  };

  String text(String key) {
    final translations = _translations[languageCode] ?? _english;
    return translations[key] ?? _english[key] ?? key;
  }

  String get languageName => languageNames[languageCode] ?? 'English';

  String get speechLocale => switch (languageCode) {
    'es' => 'es_ES',
    'fr' => 'fr_FR',
    'hi' => 'hi_IN',
    'zh' => 'zh_CN',
    _ => 'en_US',
  };

  String get ttsLocale => switch (languageCode) {
    'es' => 'es-ES',
    'fr' => 'fr-FR',
    'hi' => 'hi-IN',
    'zh' => 'zh-CN',
    _ => 'en-US',
  };

  List<String> get examplePrompts => [
    text('promptPlants'),
    text('promptClimate'),
    text('promptMatrilineal'),
  ];
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
