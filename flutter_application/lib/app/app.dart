import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'app_localizations.dart';
import '../features/admin/admin_dashboard_page.dart';
import '../features/admin/admin_feedback_page.dart';
import '../features/admin/admin_page.dart';
import '../features/admin/admin_users_page.dart';
import '../features/chat/chat_page.dart';
import '../features/auth/login_page.dart';
import '../services/admin_service.dart';
import '../services/auth_service.dart';
import '../services/chat_service.dart';
import '../services/chat_history_service.dart';
import 'pdf_opener.dart';
import 'pdf_picker.dart';

class KnowledgeGraphApp extends StatefulWidget {
  const KnowledgeGraphApp({super.key, this.authService});

  final AuthService? authService;

  @override
  State<KnowledgeGraphApp> createState() => _KnowledgeGraphAppState();
}

class _KnowledgeGraphAppState extends State<KnowledgeGraphApp> {
  late final AuthService _authService;
  AuthSession? _session;
  bool _isRestoringSession = true;
  String _languageCode = 'en';
  // Admins land on the dashboard; the chat is one of its tiles.
  bool _showingChat = false;
  bool _showingAdmin = false;
  bool _showingUsers = false;
  bool _showingFeedback = false;
  String _adminSecret = '';

  // showDialog needs a context BELOW MaterialApp -- one that can see the
  // Navigator and MaterialLocalizations it provides. This State builds
  // MaterialApp, so its own context sits above both and throws. The key gives
  // us a context from inside.
  final _navigatorKey = GlobalKey<NavigatorState>();

  static const _adminSecretKey = 'admin.secret';

  @override
  void initState() {
    super.initState();
    _authService = widget.authService ?? AuthService();
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

  void _openChat() {
    if (!mounted) return;
    setState(() => _showingChat = true);
  }

  void _openDashboard() {
    if (!mounted) return;
    setState(() => _showingChat = false);
  }

  // Asks for the secret the first time, so the admin screen does not just
  // fail with a 401 nobody can act on.
  Future<void> _openAdmin() async {
    if (_adminSecret.isEmpty) {
      final dialogContext = _navigatorKey.currentContext;
      if (dialogContext == null) return;
      final entered = await showDialog<String>(
        context: dialogContext,
        builder: (context) => const _AdminSecretDialog(),
      );
      if (entered == null || entered.isEmpty) return;
      await _setAdminSecret(entered);
    }
    if (!mounted) return;
    setState(() => _showingAdmin = true);
  }

  // Only admins are ever offered this screen, and the server independently
  // refuses the review requests of anyone who is not an admin, so it does not
  // need the shared upload secret the way paper upload and review do.
  void _openFeedbackReview() {
    if (!mounted) return;
    setState(() => _showingFeedback = true);
  }

  void _openUsers() {
    if (!mounted) return;
    setState(() => _showingUsers = true);
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

  Future<void> _register(RegistrationDetails details, bool rememberMe) async {
    final session = await _authService.register(
      details: details,
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
      _showingChat = false;
      _showingAdmin = false;
      _showingUsers = false;
      _showingFeedback = false;
    });
  }

  // Builds the root Material application.
  @override
  Widget build(BuildContext context) {
    const ink = Color(0xFF17212B);
    const blue = Color(0xFF0D6EFD);
    const teal = Color(0xFF0F766E);
    const border = Color(0xFFE2E8F0);
    final strings = AppLocalizations(_languageCode);

    return MaterialApp(
      navigatorKey: _navigatorKey,
      title: 'Mandi/Garo ChatBot',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        scaffoldBackgroundColor: const Color(0xFFF4F7FB),
        colorScheme: ColorScheme.fromSeed(
          seedColor: blue,
          brightness: Brightness.light,
          primary: blue,
          onPrimary: Colors.white,
          secondary: teal,
          onSecondary: Colors.white,
          surface: Colors.white,
          onSurface: ink,
          error: const Color(0xFFB42318),
        ),
        fontFamily: 'Arial',
        appBarTheme: const AppBarTheme(
          backgroundColor: Colors.white,
          foregroundColor: ink,
          surfaceTintColor: Colors.transparent,
          elevation: 0,
          scrolledUnderElevation: 0,
          titleTextStyle: TextStyle(
            color: ink,
            fontFamily: 'Arial',
            fontSize: 20,
            fontWeight: FontWeight.w700,
          ),
        ),
        cardTheme: CardThemeData(
          color: Colors.white,
          surfaceTintColor: Colors.transparent,
          elevation: 0,
          margin: const EdgeInsets.symmetric(vertical: 6),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(14),
            side: const BorderSide(color: border),
          ),
        ),
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: Colors.white,
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(10),
            borderSide: const BorderSide(color: border),
          ),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(10),
            borderSide: const BorderSide(color: border),
          ),
          focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(10),
            borderSide: const BorderSide(color: blue, width: 1.5),
          ),
          errorBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(10),
            borderSide: const BorderSide(color: Color(0xFFB42318)),
          ),
          focusedErrorBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(10),
            borderSide: const BorderSide(color: Color(0xFFB42318), width: 1.5),
          ),
          contentPadding: const EdgeInsets.symmetric(
            horizontal: 16,
            vertical: 14,
          ),
        ),
        filledButtonTheme: FilledButtonThemeData(
          style: FilledButton.styleFrom(
            backgroundColor: blue,
            foregroundColor: Colors.white,
            padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(10),
            ),
          ),
        ),
        outlinedButtonTheme: OutlinedButtonThemeData(
          style: OutlinedButton.styleFrom(
            foregroundColor: const Color(0xFF344054),
            side: const BorderSide(color: border),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(10),
            ),
          ),
        ),
        dividerTheme: const DividerThemeData(
          color: border,
          thickness: 1,
          space: 1,
        ),
        snackBarTheme: SnackBarThemeData(
          behavior: SnackBarBehavior.floating,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(10),
          ),
        ),
      ),
      home: _isRestoringSession
          ? const _SessionLoader()
          : _session == null
          ? LoginPage(
              onSignIn: _signIn,
              onRegister: _register,
              strings: strings,
              onLanguageChanged: _setLanguage,
            )
          : _showingUsers && _session!.isAdmin
          ? AdminUsersPage(
              service: AdminService(
                secret: _adminSecret,
                authToken: _session!.token,
              ),
              onClose: () => setState(() => _showingUsers = false),
            )
          : _showingFeedback && _session!.isAdmin
          ? AdminFeedbackPage(
              service: AdminService(
                secret: _adminSecret,
                authToken: _session!.token,
              ),
              onClose: () => setState(() => _showingFeedback = false),
            )
          : _showingAdmin && _session!.isAdmin
          ? AdminPage(
              service: AdminService(
                secret: _adminSecret,
                authToken: _session!.token,
              ),
              pickPdf: pickPdfFile,
              viewPdf: openPdfInNewTab,
              onClose: () => setState(() => _showingAdmin = false),
            )
          : _session!.isAdmin && !_showingChat
          ? AdminDashboardPage(
              service: AdminService(
                secret: _adminSecret,
                authToken: _session!.token,
              ),
              adminEmail: _session!.email,
              onOpenPapers: _openAdmin,
              onOpenFeedback: _openFeedbackReview,
              onOpenUsers: _openUsers,
              onOpenChat: _openChat,
              onSignOut: _signOut,
            )
          : ChatPage(
              service: ChatService(
                strings: () => strings,
                authToken: _session!.token,
              ),
              historyService: ChatHistoryService(authToken: _session!.token),
              onSignOut: _signOut,
              userEmail: _session!.email,
              strings: strings,
              onLanguageChanged: _setLanguage,
              // Only an admin session renders the entry point. The server's
              // shared secret is what actually authorises the requests -- a
              // role held in the browser is not access control.
              onOpenAdmin: _session!.isAdmin ? _openDashboard : null,
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
