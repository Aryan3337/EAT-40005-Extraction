import 'package:flutter/material.dart';

import '../../models/chat_message.dart';
import '../../services/chat_service.dart';

// Hosts the conversation layout and coordinates user input with RAG.py.
class ChatPage extends StatefulWidget {
  const ChatPage({super.key, required this.service});

  final ChatService service;

  // Creates the mutable conversation state.
  @override
  State<ChatPage> createState() => _ChatPageState();
}

class _ChatPageState extends State<ChatPage> {
  final _inputController = TextEditingController();
  final _scrollController = ScrollController();
  final _messages = <ChatMessage>[];
  bool _isLoading = false;

  // Releases controllers owned by the chat screen.
  @override
  void dispose() {
    _inputController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  // Submits the current question and appends the RAG response.
  Future<void> _sendMessage() async {
    final question = _inputController.text.trim();
    if (question.isEmpty || _isLoading) return;

    setState(() {
      _messages.add(ChatMessage(text: question, author: MessageAuthor.user));
      _inputController.clear();
      _isLoading = true;
    });

    final answer = await widget.service.ask(question);
    if (!mounted) return;
    setState(() {
      _messages.add(answer);
      _isLoading = false;
    });
    _scrollToBottom();
  }

  // Moves the conversation to the latest message.
  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  // Clears the current conversation and starts a fresh session.
  void _startNewChat() {
    setState(() {
      _messages.clear();
      _isLoading = false;
    });
  }

  // Builds the complete assistant workspace.
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1120),
            child: Column(
              children: [
                _ChatHeader(onNewChat: _startNewChat),
                Expanded(
                  child: _ConversationView(
                    messages: _messages,
                    controller: _scrollController,
                    isLoading: _isLoading,
                  ),
                ),
                _Composer(controller: _inputController, onSend: _sendMessage),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ChatHeader extends StatelessWidget {
  const _ChatHeader({required this.onNewChat});

  final VoidCallback onNewChat;

  // Builds the product identity and session controls.
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(24, 22, 24, 12),
      child: Row(
        children: [
          const Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Mandi/Garo ChatBot',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
                ),
              ],
            ),
          ),
          IconButton(
            onPressed: onNewChat,
            tooltip: 'New chat',
            icon: const Icon(Icons.add_comment_outlined),
          ),
        ],
      ),
    );
  }
}

class _ConversationView extends StatelessWidget {
  const _ConversationView({
    required this.messages,
    required this.controller,
    required this.isLoading,
  });

  final List<ChatMessage> messages;
  final ScrollController controller;
  final bool isLoading;

  // Builds the empty state, messages, and loading indicator.
  @override
  Widget build(BuildContext context) {
    if (messages.isEmpty) return const _EmptyState();

    return ListView.builder(
      controller: controller,
      padding: const EdgeInsets.fromLTRB(24, 16, 24, 18),
      itemCount: messages.length + (isLoading ? 1 : 0),
      itemBuilder: (context, index) {
        if (index == messages.length) {
          return const Padding(
            padding: EdgeInsets.only(top: 12),
            child: _TypingIndicator(),
          );
        }
        return _MessageBubble(message: messages[index]);
      },
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState();

  // Builds the first-use prompt and example questions.
  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(24, 48, 24, 24),
      child: Column(
        children: [
          const Text(
            'Ask me anything',
            style: TextStyle(
              fontSize: 28,
              fontWeight: FontWeight.w600,
              color: Color(0xFF17212B),
            ),
          ),
        ],
      ),
    );
  }
}

class _PromptChip extends StatelessWidget {
  const _PromptChip({required this.label});

  final String label;

  // Builds a visually compact example question.
  @override
  Widget build(BuildContext context) {
    return Chip(
      avatar: const Icon(Icons.auto_awesome, size: 16),
      label: Text(label),
    );
  }
}

class _MessageBubble extends StatelessWidget {
  const _MessageBubble({required this.message});

  final ChatMessage message;

  // Builds a user or assistant message with optional sources.
  @override
  Widget build(BuildContext context) {
    final isUser = message.author == MessageAuthor.user;
    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 720),
        margin: const EdgeInsets.only(bottom: 14),
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: isUser ? const Color(0xFF17212B) : Colors.white,
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(18),
            topRight: const Radius.circular(18),
            bottomLeft: Radius.circular(isUser ? 18 : 4),
            bottomRight: Radius.circular(isUser ? 4 : 18),
          ),
          border: isUser ? null : Border.all(color: const Color(0xFFE0E7E3)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              message.text,
              style: TextStyle(
                color: isUser ? Colors.white : const Color(0xFF26343D),
                height: 1.45,
                fontSize: 15,
              ),
            ),
            if (message.sources.isNotEmpty) ...[
              const SizedBox(height: 14),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: message.sources
                    .map(
                      (source) => Chip(
                        label: Text(source),
                        visualDensity: VisualDensity.compact,
                      ),
                    )
                    .toList(),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _TypingIndicator extends StatelessWidget {
  const _TypingIndicator();

  // Builds the response-in-progress state.
  @override
  Widget build(BuildContext context) {
    return const Align(
      alignment: Alignment.centerLeft,
      child: Text(
        'Thinking ...',
        style: TextStyle(color: Color(0xFF637078), fontStyle: FontStyle.italic),
      ),
    );
  }
}

class _Composer extends StatelessWidget {
  const _Composer({required this.controller, required this.onSend});

  final TextEditingController controller;
  final VoidCallback onSend;

  // Builds the query input and send action.
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(24, 8, 24, 24),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Expanded(
            child: TextField(
              controller: controller,
              minLines: 1,
              maxLines: 4,
              textInputAction: TextInputAction.send,
              onSubmitted: (_) => onSend(),
              decoration: const InputDecoration(
                hintText: 'Ask me anything',
                prefixIcon: Icon(Icons.search),
              ),
            ),
          ),
          const SizedBox(width: 10),
          IconButton.filled(
            onPressed: onSend,
            tooltip: 'Send question',
            icon: const Icon(Icons.arrow_upward),
          ),
        ],
      ),
    );
  }
}
