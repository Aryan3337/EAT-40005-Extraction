import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'app_localizations.dart';
import '../features/admin/admin_page.dart';
import '../features/chat/chat_page.dart';
import '../features/auth/login_page.dart';
import '../services/admin_service.dart';
import '../services/auth_service.dart';
import '../services/chat_service.dart';
import 'pdf_picker.dart';

class KnowledgeGraphApp extends StatefulWidget {
  const KnowledgeGraphApp({super.key});

  @override
  State<KnowledgeGraphApp> createState() => _KnowledgeGraphAppState();
}

class _KnowledgeGraphAppState extends State<KnowledgeGraphApp> {
  final _authService = AuthService();
  AuthSession? _session;
  bool _isRestoringSession = true;
  String _languageCode = 'en';
  bool _showingAdmin = false;
  String _adminSecret = '';

  static const _adminSecretKey = 'admin.secret';

  @override
  void initState() {
    super.initState();
    _restoreSession();
    _restoreLanguage();
    _restoreAdminSecret();
  }

  // The admin secret is remembered rather than compiled in, so it can be
  // changed without a rebuild and never appears in the published JavaScript.
  Future<void> _restoreAdminSecret() async {
    final preferences = await SharedPreferences.getInstance();
    if (!mounted) return;
    setState(() => _adminSecret = preferences.getString(_adminSecretKey) ?? '');
  }

  Future<void> _setAdminSecret(String secret) async {
    setState(() => _adminSecret = secret);
    final preferences = await SharedPreferences.getInstance();
    await preferences.setString(_adminSecretKey, secret);
  }

  // Asks for the secret the first time, so the admin screen does not just
  // fail with a 401 nobody can act on.
  Future<void> _openAdmin() async {
    if (_adminSecret.isEmpty) {
      final entered = await showDialog<String>(
        context: context,
        builder: (context) => const _AdminSecretDialog(),
      );
      if (entered == null || entered.isEmpty) return;
      await _setAdminSecret(entered);
    }
    if (!mounted) return;
    setState(() => _showingAdmin = true);
  }

  Future<void> _restoreLanguage() async {
    final preferences = await SharedPreferences.getInstance();
    final languageCode = preferences.getString('app.language') ?? 'en';
    if (!mounted) return;
    setState(() {
      _languageCode =
          AppLocalizations.supportedLanguageCodes.contains(languageCode)
          ? languageCode
          : 'en';
    });
  }

  Future<void> _setLanguage(String languageCode) async {
    if (!AppLocalizations.supportedLanguageCodes.contains(languageCode)) {
      return;
    }
    setState(() => _languageCode = languageCode);
    final preferences = await SharedPreferences.getInstance();
    await preferences.setString('app.language', languageCode);
  }

  Future<void> _restoreSession() async {
    final session = await _authService.restoreSession();
    if (!mounted) return;
    setState(() {
      _session = session;
      _isRestoringSession = false;
    });
  }

  Future<void> _signIn(String email, String password, bool rememberMe) async {
    final session = await _authService.signIn(
      email: email,
      password: password,
      rememberMe: rememberMe,
    );
    if (!mounted) return;
    setState(() => _session = session);
  }

  Future<void> _signOut() async {
    await _authService.signOut();
    if (!mounted) return;
    setState(() {
      _session = null;
      _showingAdmin = false;
    });
  }

  // Builds the root Material application.
  @override
  Widget build(BuildContext context) {
    const ink = Color(0xFF17212B);
    const mint = Color(0xFF2CB67D);
    final strings = AppLocalizations(_languageCode);

    return MaterialApp(
      title: 'Mandi/Garo ChatBot',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        scaffoldBackgroundColor: const Color(0xFFF5F7F6),
        colorScheme: ColorScheme.fromSeed(
          seedColor: mint,
          brightness: Brightness.light,
          primary: mint,
          onSurface: ink,
        ),
        fontFamily: 'Arial',
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: Colors.white,
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(16),
            borderSide: BorderSide.none,
          ),
        ),
      ),
      home: _isRestoringSession
          ? const _SessionLoader()
          : _session == null
          ? LoginPage(
              onSignIn: _signIn,
              strings: strings,
              onLanguageChanged: _setLanguage,
            )
          : _showingAdmin && _session!.isAdmin
          ? AdminPage(
              service: AdminService(secret: _adminSecret),
              pickPdf: pickPdfFile,
              onClose: () => setState(() => _showingAdmin = false),
            )
          : ChatPage(
              service: ChatService(),
              onSignOut: _signOut,
              userEmail: _session!.email,
              strings: strings,
              onLanguageChanged: _setLanguage,
              // Only an admin session renders the entry point. The server's
              // shared secret is what actually authorises the requests -- a
              // role held in the browser is not access control.
              onOpenAdmin: _session!.isAdmin ? _openAdmin : null,
            ),
    );
  }
}

class _SessionLoader extends StatelessWidget {
  const _SessionLoader();

  @override
  Widget build(BuildContext context) {
    return const Scaffold(body: Center(child: CircularProgressIndicator()));
  }
}


// Collects the shared secret that authorises admin uploads. It must match
// ADMIN_UPLOAD_SECRET on the server, which refuses every request when it is
// unset rather than leaving the endpoint open.
class _AdminSecretDialog extends StatefulWidget {
  const _AdminSecretDialog();

  @override
  State<_AdminSecretDialog> createState() => _AdminSecretDialogState();
}

class _AdminSecretDialogState extends State<_AdminSecretDialog> {
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Admin secret'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            "Enter the value of ADMIN_UPLOAD_SECRET from the server's .env.",
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _controller,
            obscureText: true,
            autofocus: true,
            decoration: const InputDecoration(labelText: 'Secret'),
            onSubmitted: (value) => Navigator.of(context).pop(value.trim()),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(_controller.text.trim()),
          child: const Text('Continue'),
        ),
      ],
    );
  }
}
