import 'package:flutter/material.dart';

import '../features/chat/chat_page.dart';
import '../features/auth/login_page.dart';
import '../services/auth_service.dart';
import '../services/chat_service.dart';

class KnowledgeGraphApp extends StatefulWidget {
  const KnowledgeGraphApp({super.key});

  @override
  State<KnowledgeGraphApp> createState() => _KnowledgeGraphAppState();
}

class _KnowledgeGraphAppState extends State<KnowledgeGraphApp> {
  final _authService = AuthService();
  AuthSession? _session;
  bool _isRestoringSession = true;

  @override
  void initState() {
    super.initState();
    _restoreSession();
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
    setState(() => _session = null);
  }

  // Builds the root Material application.
  @override
  Widget build(BuildContext context) {
    const ink = Color(0xFF17212B);
    const mint = Color(0xFF2CB67D);

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
          ? LoginPage(onSignIn: _signIn)
          : ChatPage(
              service: ChatService(),
              onSignOut: _signOut,
              userEmail: _session!.email,
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
