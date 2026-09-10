import 'package:flutter/material.dart';

import '../features/chat/chat_page.dart';
import '../services/chat_service.dart';

// Configures the app theme and injects the chat service.
class KnowledgeGraphApp extends StatelessWidget {
  const KnowledgeGraphApp({super.key});

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
      home: ChatPage(service: ChatService()),
    );
  }
}
