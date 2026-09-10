import 'package:flutter/material.dart';

import '../features/chat/chat_page.dart';
import '../services/chat_service.dart';

// Configures the app theme and injects the chat service.
class KnowledgeGraphApp extends StatelessWidget {
  const KnowledgeGraphApp({super.key});

  // Builds the root Material application.
  @override
  Widget build(BuildContext context) {
    const ink = Color(0xFF1F2430);
    const violet = Color(0xFF6C5CE7);
    const coral = Color(0xFFFF6584);

    return MaterialApp(
      title: 'Mandi/Garo ChatBot',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        scaffoldBackgroundColor: const Color(0xFFF6F5FB),
        colorScheme: ColorScheme.fromSeed(
          seedColor: violet,
          brightness: Brightness.light,
          primary: violet,
          secondary: coral,
          onSurface: ink,
        ),
        fontFamily: 'Arial',
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: Colors.white,
          contentPadding: const EdgeInsets.symmetric(
            horizontal: 18,
            vertical: 14,
          ),
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(18),
            borderSide: BorderSide.none,
          ),
        ),
      ),
      home: ChatPage(service: ChatService()),
    );
  }
}
