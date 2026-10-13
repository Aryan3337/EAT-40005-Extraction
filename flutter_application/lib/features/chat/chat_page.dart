import 'dart:async';

import 'package:flutter/material.dart';

import '../../app/app_localizations.dart';
import '../../models/chat_conversation.dart';
import '../../models/chat_message.dart';
import '../../services/chat_history_service.dart';
import '../../services/chat_service.dart';
import '../../services/speech_service.dart';
import '../../services/tts_service.dart';

// Hosts the conversation layout and coordinates user input with RAG.py.
class ChatPage extends StatefulWidget {
  const ChatPage({
    super.key,
    required this.service,
    this.onSignOut,
    this.userEmail = 'local-user',
    this.historyService,
    this.strings = const AppLocalizations('en'),
    this.onLanguageChanged,
    this.onOpenAdmin,
    this.onOpenUserManagement,
  });

  final ChatService service;
  final VoidCallback? onSignOut;
  final String userEmail;
  final ChatHistoryService? historyService;
  final AppLocalizations strings;
  final ValueChanged<String>? onLanguageChanged;

  // Non-null only for an admin session, which is what renders the entry point
  // to the paper-admission screen. This is presentation, not access control:
  // the server's shared secret authorises the requests.
  final VoidCallback? onOpenAdmin;
  final VoidCallback? onOpenUserManagement;

  // Creates the mutable conversation state.
  @override
  State<ChatPage> createState() => _ChatPageState();
}

class _ChatPageState extends State<ChatPage> {
  final _inputController = TextEditingController();
  final _scrollController = ScrollController();
  final _messages = <ChatMessage>[];
  late final ChatHistoryService _historyService;
  List<ChatConversation> _history = [];
  String? _conversationId;
  bool _isHistoryLoading = true;
  final _tts = TtsService();
  final _speech = SpeechService();
  bool _isLoading = false;
  bool _autoSpeak = false;
  int? _speakingIndex;
  bool _speechAvailable = false;
  bool _isListening = false;
  int _languageChangeGeneration = 0;

  // Loads saved chats and wires up TTS/voice-input callbacks.
  @override
  void initState() {
    super.initState();
    _historyService = widget.historyService ?? ChatHistoryService();
    _loadHistory();
    _tts.onDone(
      () {
        if (!mounted) return;
        setState(() => _speakingIndex = null);
      },
      onError: (error) {
        if (!mounted) return;
        setState(() => _speakingIndex = null);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              widget.strings.text('speechError').replaceAll('{error}', error),
            ),
          ),
        );
      },
    );
    _speech
        .init(
          onListeningChanged: (listening) {
            if (!mounted) return;
            setState(() => _isListening = listening);
          },
        )
        .then((available) {
          if (!mounted) return;
          setState(() => _speechAvailable = available);
        });
  }

  @override
  void didUpdateWidget(covariant ChatPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.strings.languageCode != widget.strings.languageCode) {
      final generation = ++_languageChangeGeneration;
      final speakingIndex = _speakingIndex;
      if (speakingIndex != null) {
        unawaited(_restartSpeechForLanguage(speakingIndex, generation));
      }
    }
  }

  Future<void> _restartSpeechForLanguage(int index, int generation) async {
    await _stopSpeaking();
    if (!mounted ||
        generation != _languageChangeGeneration ||
        index >= _messages.length) {
      return;
    }
    final message = _messages[index];
    if (message.author != MessageAuthor.assistant) return;
    final languageCode = widget.strings.languageCode;
    await _speak(
      index,
      message.textFor(languageCode),
      languageCode: languageCode,
    );
  }

  Future<void> _loadHistory() async {
    List<ChatConversation> history = [];
    try {
      history = await _historyService.load(widget.userEmail);
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not load chat history: $error')),
        );
      }
    }
    if (!mounted) return;
    setState(() {
      _history = history;
      _isHistoryLoading = false;
    });
  }

  // Releases controllers and the speech engines owned by the screen.
  @override
  void dispose() {
    _inputController.dispose();
    _scrollController.dispose();
    _tts.dispose();
    _speech.dispose();
    super.dispose();
  }

  // Submits the current question and appends the RAG response.
  Future<void> _sendMessage() async {
    final question = _inputController.text.trim();
    if (question.isEmpty || _isLoading) return;

    setState(() {
      _conversationId ??= DateTime.now().microsecondsSinceEpoch.toString();
      _messages.add(ChatMessage(text: question, author: MessageAuthor.user));
      _inputController.clear();
      _isLoading = true;
    });

    final answer = await widget.service.ask(
      question,
      language: widget.strings.languageCode,
    );
    if (!mounted) return;
    setState(() {
      _messages.add(answer);
      _isLoading = false;
    });
    await _saveCurrentConversation();
    _scrollToBottom();

    if (_autoSpeak) {
      _speak(
        _messages.length - 1,
        answer.textFor(widget.strings.languageCode),
        languageCode: widget.strings.languageCode,
      );
    }
  }

  // Fills the composer with a suggested question and sends it right away.
  void _useSuggestedPrompt(String prompt) {
    _inputController.text = prompt;
    _sendMessage();
  }

  Future<void> _saveCurrentConversation() async {
    if (_messages.isEmpty || _conversationId == null) return;
    final firstUserMessage = _messages.firstWhere(
      (message) => message.author == MessageAuthor.user,
      orElse: () => _messages.first,
    );
    final conversation = ChatConversation(
      id: _conversationId!,
      title: firstUserMessage.text,
      messages: List.unmodifiable(_messages),
      updatedAt: DateTime.now(),
    );
    final updated = [
      conversation,
      ..._history.where((item) => item.id != conversation.id),
    ]..sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    try {
      await _historyService.save(widget.userEmail, updated);
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not save chat history: $error')),
        );
      }
      return;
    }
    if (!mounted) return;
    setState(() => _history = updated);
  }

  // Moves the conversation to the latest message.
  // Records feedback for an assistant response and persists it in chat history.
  Future<void> _updateMessageFeedback(
    int messageIndex,
    MessageFeedback feedback,
    String comment,
  ) async {
    if (messageIndex < 0 || messageIndex >= _messages.length) return;
    final message = _messages[messageIndex];
    if (_conversationId == null || message.author != MessageAuthor.assistant) {
      return;
    }

    try {
      await widget.service.saveFeedback(
        conversationId: _conversationId!,
        responseText: message.text,
        feedback: feedback,
        comment: comment,
      );
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not save feedback: $error')),
        );
      }
      return;
    }

    setState(() {
      _messages[messageIndex] = message.copyWith(
        feedback: feedback,
        feedbackComment: comment.trim(),
      );
    });

    await _saveCurrentConversation();
  }

  Future<void> _showFeedbackHistory() async {
    try {
      final feedback = await widget.service.feedbackHistory();
      if (!mounted) return;
      await showModalBottomSheet<void>(
        context: context,
        showDragHandle: true,
        isScrollControlled: true,
        builder: (context) => SafeArea(
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 8, 12, 0),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        widget.strings.text('feedbackHistory'),
                        style: const TextStyle(
                          fontSize: 20,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                    IconButton(
                      tooltip: widget.strings.text('clearFeedback'),
                      icon: const Icon(Icons.delete_sweep_outlined),
                      onPressed: () async {
                        final confirmed = await _confirmAction(
                          widget.strings.text('confirmClearFeedback'),
                        );
                        if (!confirmed) return;
                        await widget.service.clearFeedbackHistory();
                        if (context.mounted) Navigator.of(context).pop();
                      },
                    ),
                  ],
                ),
              ),
              Expanded(
                child: SizedBox(
                  height: MediaQuery.sizeOf(context).height * 0.72,
                  child: feedback.isEmpty
                      ? Center(
                          child: Padding(
                            padding: const EdgeInsets.all(24),
                            child: Text(
                              widget.strings.text('noFeedbackYet'),
                              textAlign: TextAlign.center,
                            ),
                          ),
                        )
                      : ListView.separated(
                          padding: const EdgeInsets.all(20),
                          itemCount: feedback.length,
                          separatorBuilder: (_, _) => const Divider(height: 28),
                          itemBuilder: (context, index) {
                            final item = feedback[index];
                            return Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  children: [
                                    Icon(
                                      item.rating == MessageFeedback.helpful
                                          ? Icons.thumb_up_outlined
                                          : Icons.thumb_down_outlined,
                                    ),
                                    const SizedBox(width: 8),
                                    Text(
                                      item.rating == MessageFeedback.helpful
                                          ? widget.strings.text('helpful')
                                          : widget.strings.text('notHelpful'),
                                      style: const TextStyle(
                                        fontWeight: FontWeight.w700,
                                      ),
                                    ),
                                  ],
                                ),
                                const SizedBox(height: 8),
                                Text(
                                  item.responseText,
                                  maxLines: 3,
                                  overflow: TextOverflow.ellipsis,
                                ),
                                if (item.comment.isNotEmpty) ...[
                                  const SizedBox(height: 8),
                                  Text(item.comment),
                                ],
                                if (item.createdAt.isNotEmpty) ...[
                                  const SizedBox(height: 8),
                                  Text(
                                    item.createdAt,
                                    style: Theme.of(context)
                                        .textTheme
                                        .bodySmall,
                                  ),
                                ],
                              ],
                            );
                          },
                        ),
                ),
              ),
            ],
          ),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not load feedback: $error')),
      );
    }
  }

  Future<bool> _confirmAction(String message) async {
    return await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            content: Text(message),
            actions: [
              TextButton(
                onPressed: () => Navigator.of(context).pop(false),
                child: Text(widget.strings.text('cancel')),
              ),
              FilledButton(
                onPressed: () => Navigator.of(context).pop(true),
                child: Text(widget.strings.text('clearHistory')),
              ),
            ],
          ),
        ) ??
        false;
  }

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

  // Speaks the message at [index] aloud, replacing any speech in progress.
  Future<void> _speak(
    int index,
    String text, {
    required String languageCode,
  }) async {
    setState(() => _speakingIndex = index);
    try {
      final voiceAvailable = await _tts.speak(text, languageCode: languageCode);
      if (!mounted) return;
      if (!voiceAvailable) {
        final language =
            AppLocalizations.languageNames[languageCode] ?? languageCode;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              widget.strings
                  .text('speechVoiceUnavailable')
                  .replaceAll('{language}', language),
            ),
          ),
        );
        setState(() => _speakingIndex = null);
      }
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            widget.strings
                .text('speechError')
                .replaceAll('{error}', error.toString()),
          ),
        ),
      );
      setState(() => _speakingIndex = null);
    }
  }

  // Stops whatever the assistant is currently reading aloud.
  Future<void> _stopSpeaking() async {
    await _tts.stop();
    if (!mounted) return;
    setState(() => _speakingIndex = null);
  }

  // Reads message [index] aloud, or stops it if it's already speaking.
  void _toggleSpeak(int index, String text) {
    if (_speakingIndex == index) {
      _stopSpeaking();
    } else {
      _speak(index, text, languageCode: widget.strings.languageCode);
    }
  }

  // Toggles whether new assistant answers are read aloud automatically.
  void _toggleAutoSpeak() {
    setState(() => _autoSpeak = !_autoSpeak);
    if (!_autoSpeak) {
      _stopSpeaking();
    }
  }

  // Starts or stops dictating the question by voice.
  Future<void> _toggleListening() async {
    if (!_speechAvailable) return;
    if (_isListening) {
      await _speech.stop();
      return;
    }
    if (_isLoading) return; // wait for the current answer first

    final localeId = switch (widget.strings.languageCode) {
      'hi' => 'hi-IN',
      'bn' => 'bn-BD',
      _ => 'en-US',
    };
    setState(() => _isListening = true);
    await _speech.listen((text) {
      setState(() {
        _inputController.text = text;
        _inputController.selection = TextSelection.collapsed(
          offset: text.length,
        );
      });
    }, localeId: localeId);
  }

  // Clears the current conversation and starts a fresh session.
  Future<void> _startNewChat() async {
    _stopSpeaking();
    await _saveCurrentConversation();
    if (!mounted) return;
    setState(() {
      _messages.clear();
      _conversationId = null;
      _isLoading = false;
    });
  }

  Future<void> _openConversation(ChatConversation conversation) async {
    await _saveCurrentConversation();
    if (!mounted) return;
    setState(() {
      _conversationId = conversation.id;
      _messages
        ..clear()
        ..addAll(conversation.messages);
      _isLoading = false;
    });
    Navigator.of(context).pop();
    _scrollToBottom();
  }

  Future<void> _deleteConversation(ChatConversation conversation) async {
    try {
      await _historyService.delete(widget.userEmail, conversation.id);
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not delete chat history: $error')),
        );
      }
      return;
    }
    if (!mounted) return;
    setState(() {
      _history.removeWhere((item) => item.id == conversation.id);
      if (_conversationId == conversation.id) {
        _messages.clear();
        _conversationId = null;
      }
    });
  }

  Future<void> _clearHistory() async {
    final confirmed = await _confirmAction(
      widget.strings.text('confirmClearHistory'),
    );
    if (!confirmed) return;
    try {
      await _historyService.clear(widget.userEmail);
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not clear chat history: $error')),
        );
      }
      return;
    }
    if (!mounted) return;
    setState(() {
      _history.clear();
      _messages.clear();
      _conversationId = null;
    });
    Navigator.of(context).pop();
  }

  // Builds the complete assistant workspace.
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      drawer: _HistoryDrawer(
        strings: widget.strings,
        history: _history,
        isLoading: _isHistoryLoading,
        onOpen: _openConversation,
        onDelete: _deleteConversation,
        onClear: _clearHistory,
        onNewChat: _startNewChat,
      ),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1120),
            child: Column(
              children: [
                _ChatHeader(
                  strings: widget.strings,
                  onNewChat: _startNewChat,
                  onSignOut: widget.onSignOut,
                  onLanguageChanged: widget.onLanguageChanged,
                  onOpenAdmin: widget.onOpenAdmin,
                  onOpenUserManagement: widget.onOpenUserManagement,
                  onShowFeedbackHistory: _showFeedbackHistory,
                  autoSpeak: _autoSpeak,
                  onToggleAutoSpeak: _toggleAutoSpeak,
                ),
                Expanded(
                  child: _ConversationView(
                    messages: _messages,
                    controller: _scrollController,
                    isLoading: _isLoading,
                    onFeedback: _updateMessageFeedback,
                    strings: widget.strings,
                    speakingIndex: _speakingIndex,
                    onToggleSpeak: _toggleSpeak,
                    onPromptTap: _useSuggestedPrompt,
                  ),
                ),
                _Composer(
                  controller: _inputController,
                  onSend: _sendMessage,
                  strings: widget.strings,
                  speechAvailable: _speechAvailable,
                  isListening: _isListening,
                  onToggleListening: _toggleListening,
                  isBusy: _isLoading,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ChatHeader extends StatelessWidget {
  const _ChatHeader({
    required this.onNewChat,
    required this.strings,
    required this.autoSpeak,
    required this.onToggleAutoSpeak,
    this.onSignOut,
    this.onLanguageChanged,
    this.onOpenAdmin,
    this.onOpenUserManagement,
    required this.onShowFeedbackHistory,
  });

  final Future<void> Function() onNewChat;
  final AppLocalizations strings;
  final bool autoSpeak;
  final VoidCallback onToggleAutoSpeak;
  final VoidCallback? onSignOut;
  final ValueChanged<String>? onLanguageChanged;
  final VoidCallback? onOpenAdmin;
  final VoidCallback? onOpenUserManagement;
  final Future<void> Function() onShowFeedbackHistory;

  // Builds the product identity and session controls.
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.fromLTRB(24, 20, 24, 16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: const BorderRadius.vertical(bottom: Radius.circular(24)),
        boxShadow: [
          BoxShadow(
            color: theme.colorScheme.primary.withValues(alpha: 0.08),
            blurRadius: 16,
            offset: const Offset(0, 6),
          ),
        ],
      ),
      child: Row(
        children: [
          Builder(
            builder: (context) => IconButton(
              onPressed: () => Scaffold.of(context).openDrawer(),
              tooltip: strings.text('chatHistory'),
              icon: const Icon(Icons.menu_rounded),
            ),
          ),
          const SizedBox(width: 4),
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              gradient: LinearGradient(
                colors: [
                  theme.colorScheme.primary,
                  theme.colorScheme.secondary,
                ],
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
              ),
              borderRadius: BorderRadius.circular(12),
            ),
            child: const Icon(
              Icons.forum_rounded,
              color: Colors.white,
              size: 22,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Mandi/Garo ChatBot',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
                ),
                Text(
                  strings.text('appTagline'),
                  style: const TextStyle(
                    fontSize: 12,
                    color: Color(0xFF8A93A0),
                  ),
                ),
              ],
            ),
          ),
          if (onLanguageChanged != null)
            LanguagePicker(strings: strings, onChanged: onLanguageChanged!),
          if (onOpenAdmin != null)
            IconButton(
              onPressed: onOpenAdmin,
              tooltip: 'Paper admission',
              icon: const Icon(Icons.admin_panel_settings_outlined),
            ),
          IconButton(
            onPressed: onShowFeedbackHistory,
            tooltip: strings.text('feedbackHistory'),
            icon: const Icon(Icons.rate_review_outlined),
          ),
          if (onOpenUserManagement != null)
            IconButton(
              onPressed: onOpenUserManagement,
              tooltip: 'Manage users',
              icon: const Icon(Icons.people_outline),
            ),
          const SizedBox(width: 8),
          _RoundIconButton(
            icon: autoSpeak
                ? Icons.volume_up_rounded
                : Icons.volume_off_rounded,
            active: autoSpeak,
            tooltip: strings.text(autoSpeak ? 'autoReadOn' : 'autoReadOff'),
            onPressed: onToggleAutoSpeak,
          ),
          const SizedBox(width: 8),
          _RoundIconButton(
            icon: Icons.add_comment_rounded,
            tooltip: strings.text('newChat'),
            onPressed: onNewChat,
          ),
          if (onSignOut != null)
            IconButton(
              onPressed: onSignOut,
              tooltip: strings.text('signOut'),
              icon: const Icon(Icons.logout_outlined),
            ),
        ],
      ),
    );
  }
}

class _HistoryDrawer extends StatelessWidget {
  const _HistoryDrawer({
    required this.strings,
    required this.history,
    required this.isLoading,
    required this.onOpen,
    required this.onDelete,
    required this.onClear,
    required this.onNewChat,
  });

  final AppLocalizations strings;
  final List<ChatConversation> history;
  final bool isLoading;
  final Future<void> Function(ChatConversation conversation) onOpen;
  final Future<void> Function(ChatConversation conversation) onDelete;
  final Future<void> Function() onClear;
  final Future<void> Function() onNewChat;

  @override
  Widget build(BuildContext context) {
    return Drawer(
      child: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 22, 12, 14),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      strings.text('chatHistory'),
                      style: TextStyle(
                        fontSize: 21,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  IconButton(
                    onPressed: onNewChat,
                    tooltip: strings.text('newChat'),
                    icon: const Icon(Icons.add_comment_outlined),
                  ),
                  IconButton(
                    onPressed: onClear,
                    tooltip: strings.text('clearHistory'),
                    icon: const Icon(Icons.delete_sweep_outlined),
                  ),
                ],
              ),
            ),
            const Divider(height: 1),
            Expanded(
              child: isLoading
                  ? const Center(child: CircularProgressIndicator())
                  : history.isEmpty
                  ? Center(
                      child: Padding(
                        padding: const EdgeInsets.all(24),
                        child: Text(
                          strings.text('savedConversations'),
                          textAlign: TextAlign.center,
                        ),
                      ),
                    )
                  : ListView.builder(
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      itemCount: history.length,
                      itemBuilder: (context, index) {
                        final conversation = history[index];
                        return ListTile(
                          leading: const Icon(Icons.chat_bubble_outline),
                          title: Text(
                            conversation.title,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                          ),
                          trailing: IconButton(
                            onPressed: () => onDelete(conversation),
                            tooltip: strings.text('deleteConversation'),
                            icon: const Icon(Icons.delete_outline),
                          ),
                          onTap: () => onOpen(conversation),
                        );
                      },
                    ),
            ),
          ],
        ),
      ),
    );
  }
}

// A small circular icon button with a tinted background, used for header
// and composer actions to give the UI a friendlier, "buttony" feel.
class _RoundIconButton extends StatelessWidget {
  const _RoundIconButton({
    required this.icon,
    required this.onPressed,
    required this.tooltip,
    this.active = false,
  });

  final IconData icon;
  final VoidCallback onPressed;
  final String tooltip;
  final bool active;

  @override
  Widget build(BuildContext context) {
    final color = Theme.of(context).colorScheme.primary;
    return Tooltip(
      message: tooltip,
      child: Material(
        color: active ? color.withValues(alpha: 0.15) : const Color(0xFFF1F1F6),
        shape: const CircleBorder(),
        child: InkWell(
          onTap: onPressed,
          customBorder: const CircleBorder(),
          child: SizedBox(
            width: 40,
            height: 40,
            child: Icon(
              icon,
              color: active ? color : const Color(0xFF5B6472),
              size: 20,
            ),
          ),
        ),
      ),
    );
  }
}

class _ConversationView extends StatelessWidget {
  const _ConversationView({
    required this.messages,
    required this.controller,
    required this.isLoading,
    required this.onFeedback,
    required this.strings,
    required this.speakingIndex,
    required this.onToggleSpeak,
    required this.onPromptTap,
  });

  final List<ChatMessage> messages;
  final ScrollController controller;
  final bool isLoading;
  final Future<void> Function(
    int messageIndex,
    MessageFeedback feedback,
    String comment,
  )
  onFeedback;

  final AppLocalizations strings;
  final int? speakingIndex;
  final void Function(int index, String text) onToggleSpeak;
  final void Function(String prompt) onPromptTap;

  // Builds the empty state, messages, and loading indicator.
  @override
  Widget build(BuildContext context) {
    if (messages.isEmpty) {
      return _EmptyState(strings: strings, onPromptTap: onPromptTap);
    }

    return ListView.builder(
      controller: controller,
      padding: const EdgeInsets.fromLTRB(24, 16, 24, 18),
      itemCount: messages.length + (isLoading ? 1 : 0),
      itemBuilder: (context, index) {
        if (index == messages.length) {
          return Padding(
            padding: const EdgeInsets.only(top: 12),
            child: _TypingIndicator(strings: strings),
          );
        }
        final message = messages[index];
        final displayText = message.author == MessageAuthor.assistant
            ? message.textFor(strings.languageCode)
            : message.text;
        return _MessageBubble(
          message: message,
          messageIndex: index,
          strings: strings,
          onFeedback: onFeedback,
          isSpeaking: speakingIndex == index,
          onToggleSpeak: message.author == MessageAuthor.assistant
              ? () => onToggleSpeak(index, displayText)
              : null,
        );
      },
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.strings, required this.onPromptTap});

  final AppLocalizations strings;

  final void Function(String prompt) onPromptTap;

  static const _examplePrompts = [
    'What plants do the Garo people use for traditional medicine?',
    'How is climate change affecting indigenous communities?',
    "Tell me about the Garo people's matrilineal social system.",
  ];

  static const _banglaExamplePrompts = [
    'গারো জনগণ ঐতিহ্যবাহী ওষুধে কোন গাছ ব্যবহার করে?',
    'জলবায়ু পরিবর্তন আদিবাসী সম্প্রদায়কে কীভাবে প্রভাবিত করছে?',
    'গারো জনগণের মাতৃসূত্র সামাজিক ব্যবস্থা সম্পর্কে বলুন।',
  ];

  static const _hindiExamplePrompts = [
    'गारो लोग पारंपरिक चिकित्सा में कौन-कौन से पौधों का उपयोग करते हैं?',
    'जलवायु परिवर्तन आदिवासी समुदायों को कैसे प्रभावित कर रहा है?',
    'गारो लोगों की मातृसत्तात्मक सामाजिक व्यवस्था के बारे में बताइए।',
  ];

  // Builds the first-use prompt and example questions.
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final accents = [theme.colorScheme.primary, theme.colorScheme.secondary];
    final prompts = switch (strings.languageCode) {
      'bn' => _banglaExamplePrompts,
      'hi' => _hindiExamplePrompts,
      _ => _examplePrompts,
    };

    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(24, 48, 24, 24),
      child: Column(
        children: [
          Text(
            strings.text('askAnything'),
            style: TextStyle(
              fontSize: 28,
              fontWeight: FontWeight.w700,
              color: Color(0xFF17212B),
            ),
          ),
          const SizedBox(height: 6),
          const Text(
            'Try one of these, or type your own question below.',
            style: TextStyle(color: Color(0xFF8A93A0)),
          ),
          const SizedBox(height: 22),
          Wrap(
            alignment: WrapAlignment.center,
            spacing: 10,
            runSpacing: 10,
            children: [
              for (var i = 0; i < prompts.length; i++)
                _PromptChip(
                  label: prompts[i],
                  color: accents[i % accents.length],
                  onTap: () => onPromptTap(prompts[i]),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _PromptChip extends StatelessWidget {
  const _PromptChip({
    required this.label,
    required this.onTap,
    required this.color,
  });

  final String label;
  final VoidCallback onTap;
  final Color color;

  // Builds a visually compact, tappable example question.
  @override
  Widget build(BuildContext context) {
    return ActionChip(
      avatar: Icon(Icons.auto_awesome, size: 16, color: color),
      label: Text(label),
      onPressed: onTap,
      backgroundColor: color.withValues(alpha: 0.08),
      side: BorderSide(color: color.withValues(alpha: 0.25)),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
    );
  }
}

class _MessageBubble extends StatelessWidget {
  const _MessageBubble({
    required this.message,
    required this.messageIndex,
    required this.strings,
    required this.onFeedback,
    required this.isSpeaking,
    required this.onToggleSpeak,
  });

  final ChatMessage message;
  final int messageIndex;
  final AppLocalizations strings;
  final Future<void> Function(
    int messageIndex,
    MessageFeedback feedback,
    String comment,
  )
  onFeedback;
  final bool isSpeaking;
  final VoidCallback? onToggleSpeak;

  // Builds a user or assistant message with optional sources and, for
  // assistant replies, a button to read the message aloud.
  @override
  Widget build(BuildContext context) {
    final isUser = message.author == MessageAuthor.user;
    final theme = Theme.of(context);

    final bubble = Container(
      constraints: const BoxConstraints(maxWidth: 680),
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
        boxShadow: isUser
            ? null
            : [
                BoxShadow(
                  color: Colors.black.withValues(alpha: 0.03),
                  blurRadius: 10,
                  offset: const Offset(0, 4),
                ),
              ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: AnimatedSwitcher(
                  duration: const Duration(milliseconds: 180),
                  child: Text(
                    message.author == MessageAuthor.assistant
                        ? message.textFor(strings.languageCode)
                        : message.text,
                    key: ValueKey(strings.languageCode),
                    style: TextStyle(
                      color: isUser ? Colors.white : const Color(0xFF26343D),
                      height: 1.45,
                      fontSize: 15,
                    ),
                  ),
                ),
              ),
              if (onToggleSpeak != null) ...[
                const SizedBox(width: 4),
                SizedBox(
                  width: 32,
                  height: 32,
                  child: IconButton(
                    padding: EdgeInsets.zero,
                    visualDensity: VisualDensity.compact,
                    onPressed: onToggleSpeak,
                    tooltip: strings.text(
                      isSpeaking ? 'stopReading' : 'readAloud',
                    ),
                    icon: Icon(
                      isSpeaking
                          ? Icons.stop_circle_rounded
                          : Icons.volume_up_rounded,
                      size: 20,
                      color: isSpeaking
                          ? theme.colorScheme.secondary
                          : theme.colorScheme.primary,
                    ),
                  ),
                ),
              ],
            ],
          ),
          if (!isUser && message.sources.isNotEmpty) ...[
            const SizedBox(height: 12),
            const Divider(color: Color(0xFFE0E7E3)),
            Theme(
              data: Theme.of(context)
                  .copyWith(dividerColor: Colors.transparent),
              child: ExpansionTile(
                tilePadding: EdgeInsets.zero,
                childrenPadding: EdgeInsets.zero,
                leading: const Icon(
                  Icons.verified_outlined,
                  color: Color(0xFF2E7D5B),
                ),
                title: Text(
                  strings
                      .text('verifiedSources')
                      .replaceAll('{count}', '${message.sources.length}'),
                  style: const TextStyle(
                    color: Color(0xFF2E7D5B),
                    fontWeight: FontWeight.w600,
                    fontSize: 14,
                  ),
                ),
                children: [
                  for (var index = 0; index < message.sources.length; index++)
                    _buildSourceCard(message.sources[index], index + 1),
                ],
              ),
            ),
          ],
          if (!isUser) ...[
            const SizedBox(height: 12),
            const Divider(color: Color(0xFFE0E7E3)),
            Text(
              strings.text('responseHelpful'),
              style: const TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w600,
                color: Color(0xFF52616A),
              ),
            ),
            const SizedBox(height: 4),
            Row(
              children: [
                IconButton(
                  onPressed: () => onFeedback(
                    messageIndex,
                    MessageFeedback.helpful,
                    message.feedbackComment,
                  ),
                  tooltip: strings.text('helpful'),
                  color: const Color(0xFF2E7D5B),
                  icon: Icon(
                    message.feedback == MessageFeedback.helpful
                        ? Icons.thumb_up
                        : Icons.thumb_up_outlined,
                  ),
                ),
                IconButton(
                  onPressed: () => onFeedback(
                    messageIndex,
                    MessageFeedback.notHelpful,
                    message.feedbackComment,
                  ),
                  tooltip: strings.text('notHelpful'),
                  color: const Color(0xFFC05A47),
                  icon: Icon(
                    message.feedback == MessageFeedback.notHelpful
                        ? Icons.thumb_down
                        : Icons.thumb_down_outlined,
                  ),
                ),
                TextButton.icon(
                  onPressed: () => _showCommentDialog(context),
                  icon: const Icon(Icons.comment_outlined, size: 18),
                  label: Text(
                    message.feedbackComment.isEmpty
                        ? strings.text('addComment')
                        : strings.text('editComment'),
                  ),
                ),
              ],
            ),
            if (message.feedback != null)
              Text(
                strings.text('feedbackThanks'),
                style: const TextStyle(fontSize: 12, color: Color(0xFF2E7D5B)),
              ),
            if (message.feedbackComment.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(
                strings
                    .text('commentLabel')
                    .replaceAll('{comment}', message.feedbackComment),
                style: const TextStyle(
                  fontSize: 12,
                  fontStyle: FontStyle.italic,
                  color: Color(0xFF52616A),
                ),
              ),
            ],
          ],
        ],
      ),
    );

    final content = isUser
        ? bubble
        : Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 30,
                height: 30,
                margin: const EdgeInsets.only(right: 8, top: 2),
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    colors: [
                      theme.colorScheme.primary,
                      theme.colorScheme.secondary,
                    ],
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                  ),
                  shape: BoxShape.circle,
                ),
                child: const Icon(
                  Icons.auto_awesome,
                  color: Colors.white,
                  size: 15,
                ),
              ),
              Flexible(child: bubble),
            ],
          );

    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Padding(
        padding: const EdgeInsets.only(bottom: 14),
        child: content,
      ),
    );
  }

  Future<void> _showCommentDialog(BuildContext context) async {
    if (message.feedback == null) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(strings.text('chooseFeedback'))));
      return;
    }

    final controller = TextEditingController(text: message.feedbackComment);

    final comment = await showDialog<String>(
      context: context,
      builder: (dialogContext) {
        return AlertDialog(
          title: Text(strings.text('responseFeedback')),
          content: TextField(
            controller: controller,
            autofocus: true,
            maxLines: 4,
            maxLength: 300,
            decoration: InputDecoration(
              hintText: strings.text('improveResponse'),
              border: OutlineInputBorder(),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(),
              child: Text(strings.text('cancel')),
            ),
            FilledButton(
              onPressed: () => Navigator.of(dialogContext).pop(controller.text),
              child: Text(strings.text('saveFeedback')),
            ),
          ],
        );
      },
    );

    controller.dispose();

    if (comment != null) {
      await onFeedback(messageIndex, message.feedback!, comment);
    }
  }

  Widget _buildSourceCard(SourceEvidence source, int number) {
    final supportingText = source.supportingText;

    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFFF4F8F6),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFD6E5DE)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            strings.text('source').replaceAll('{number}', '$number'),
            style: const TextStyle(
              fontWeight: FontWeight.w700,
              color: Color(0xFF2E7D5B),
            ),
          ),
          if (source.sourceSection.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              strings
                  .text('section')
                  .replaceAll('{section}', source.sourceSection),
            ),
          ],
          if (supportingText.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              supportingText,
              style: const TextStyle(fontStyle: FontStyle.italic, height: 1.35),
            ),
          ],
          if (source.subject.isNotEmpty &&
              source.predicate.isNotEmpty &&
              source.object.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              strings
                  .text('knowledgeGraph')
                  .replaceAll('{triple}', source.triple),
              style: const TextStyle(fontSize: 13, color: Color(0xFF52616A)),
            ),
          ],
          if (source.confidence.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              strings
                  .text('confidence')
                  .replaceAll('{confidence}', source.confidence),
              style: const TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w600,
                color: Color(0xFF52616A),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _TypingIndicator extends StatelessWidget {
  const _TypingIndicator({required this.strings});

  final AppLocalizations strings;

  // Builds the response-in-progress state.
  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: Text(
        strings.text('thinking'),
        style: TextStyle(color: Color(0xFF637078), fontStyle: FontStyle.italic),
      ),
    );
  }
}

class _Composer extends StatelessWidget {
  const _Composer({
    required this.controller,
    required this.onSend,
    required this.strings,
    required this.speechAvailable,
    required this.isListening,
    required this.onToggleListening,
    this.isBusy = false,
  });

  final TextEditingController controller;
  final VoidCallback onSend;
  final AppLocalizations strings;
  final bool speechAvailable;
  final bool isListening;
  final VoidCallback onToggleListening;

  // True while the bot is answering: sending and starting voice input are
  // disabled (and shown as disabled) until the answer arrives.
  final bool isBusy;

  // Builds the query input, optional voice-input control, and send action.
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(24, 8, 24, 24),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Expanded(
            child: Container(
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(18),
                boxShadow: [
                  BoxShadow(
                    color: theme.colorScheme.primary.withValues(alpha: 0.08),
                    blurRadius: 14,
                    offset: const Offset(0, 4),
                  ),
                ],
              ),
              child: TextField(
                controller: controller,
                minLines: 1,
                maxLines: 4,
                textInputAction: TextInputAction.send,
                onSubmitted: (_) {
                  if (!isBusy) onSend();
                },
                decoration: InputDecoration(
                  hintText: isListening
                      ? strings.text('listening')
                      : strings.text('askAnything'),
                  prefixIcon: const Icon(Icons.search),
                  suffixIcon: speechAvailable
                      ? IconButton(
                          // Stopping is always allowed; starting waits for
                          // the current answer.
                          onPressed: isBusy && !isListening
                              ? null
                              : onToggleListening,
                          tooltip: isListening
                              ? strings.text('stopListening')
                              : strings.text('askByVoice'),
                          color: isListening
                              ? theme.colorScheme.secondary
                              : const Color(0xFF8A93A0),
                          icon: Icon(
                            isListening
                                ? Icons.mic_rounded
                                : Icons.mic_none_rounded,
                          ),
                        )
                      : null,
                ),
              ),
            ),
          ),
          const SizedBox(width: 10),
          Container(
            width: 48,
            height: 48,
            decoration: BoxDecoration(
              gradient: LinearGradient(
                colors: isBusy
                    ? const [Color(0xFFB8BEC6), Color(0xFFB8BEC6)]
                    : [theme.colorScheme.primary, theme.colorScheme.secondary],
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
              ),
              shape: BoxShape.circle,
              boxShadow: isBusy
                  ? const []
                  : [
                      BoxShadow(
                        color: theme.colorScheme.primary.withValues(
                          alpha: 0.35,
                        ),
                        blurRadius: 10,
                        offset: const Offset(0, 4),
                      ),
                    ],
            ),
            child: IconButton(
              onPressed: isBusy ? null : onSend,
              tooltip: isBusy
                  ? strings.text('waitingForAnswer')
                  : strings.text('sendQuestion'),
              icon: isBusy
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Colors.white,
                      ),
                    )
                  : const Icon(Icons.arrow_upward_rounded, color: Colors.white),
            ),
          ),
        ],
      ),
    );
  }
}
