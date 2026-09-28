import 'package:flutter/material.dart';

import '../../models/chat_message.dart';
import '../../services/chat_service.dart';
import '../../services/speech_service.dart';
import '../../services/tts_service.dart';

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
  final _tts = TtsService();
  final _speech = SpeechService();
  bool _isLoading = false;
  bool _autoSpeak = false;
  int? _speakingIndex;
  bool _speechAvailable = false;
  bool _isListening = false;

  // Wires up TTS/voice-input callbacks so the UI stays in sync with them.
  @override
  void initState() {
    super.initState();
    _tts.onDone(() {
      if (!mounted) return;
      setState(() => _speakingIndex = null);
    });
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

    if (_autoSpeak) {
      _speak(_messages.length - 1, answer.text);
    }
  }

  // Fills the composer with a suggested question and sends it right away.
  void _useSuggestedPrompt(String prompt) {
    _inputController.text = prompt;
    _sendMessage();
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

  // Speaks the message at [index] aloud, replacing any speech in progress.
  Future<void> _speak(int index, String text) async {
    setState(() => _speakingIndex = index);
    await _tts.speak(text);
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
      _speak(index, text);
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
    setState(() => _isListening = true);
    await _speech.listen((text) {
      setState(() {
        _inputController.text = text;
        _inputController.selection = TextSelection.collapsed(
          offset: text.length,
        );
      });
    });
  }

  // Clears the current conversation and starts a fresh session.
  void _startNewChat() {
    _stopSpeaking();
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
                _ChatHeader(
                  onNewChat: _startNewChat,
                  autoSpeak: _autoSpeak,
                  onToggleAutoSpeak: _toggleAutoSpeak,
                ),
                Expanded(
                  child: _ConversationView(
                    messages: _messages,
                    controller: _scrollController,
                    isLoading: _isLoading,
                    speakingIndex: _speakingIndex,
                    onToggleSpeak: _toggleSpeak,
                    onPromptTap: _useSuggestedPrompt,
                  ),
                ),
                _Composer(
                  controller: _inputController,
                  onSend: _sendMessage,
                  speechAvailable: _speechAvailable,
                  isListening: _isListening,
                  onToggleListening: _toggleListening,
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
    required this.autoSpeak,
    required this.onToggleAutoSpeak,
  });

  final VoidCallback onNewChat;
  final bool autoSpeak;
  final VoidCallback onToggleAutoSpeak;

  // Builds the product identity and session controls.
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.fromLTRB(24, 20, 24, 16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: const BorderRadius.vertical(
          bottom: Radius.circular(24),
        ),
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
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              gradient: LinearGradient(
                colors: [theme.colorScheme.primary, theme.colorScheme.secondary],
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
          const Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Mandi/Garo ChatBot',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
                ),
                Text(
                  'Ask about culture, climate & community',
                  style: TextStyle(fontSize: 12, color: Color(0xFF8A93A0)),
                ),
              ],
            ),
          ),
          _RoundIconButton(
            icon: autoSpeak ? Icons.volume_up_rounded : Icons.volume_off_rounded,
            active: autoSpeak,
            tooltip: autoSpeak
                ? 'Auto read-aloud is on: tap to turn off'
                : 'Auto read-aloud is off: tap to turn on',
            onPressed: onToggleAutoSpeak,
          ),
          const SizedBox(width: 8),
          _RoundIconButton(
            icon: Icons.add_comment_rounded,
            tooltip: 'New chat',
            onPressed: onNewChat,
          ),
        ],
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
    required this.speakingIndex,
    required this.onToggleSpeak,
    required this.onPromptTap,
  });

  final List<ChatMessage> messages;
  final ScrollController controller;
  final bool isLoading;
  final int? speakingIndex;
  final void Function(int index, String text) onToggleSpeak;
  final void Function(String prompt) onPromptTap;

  // Builds the empty state, messages, and loading indicator.
  @override
  Widget build(BuildContext context) {
    if (messages.isEmpty) return _EmptyState(onPromptTap: onPromptTap);

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
        final message = messages[index];
        return _MessageBubble(
          message: message,
          isSpeaking: speakingIndex == index,
          onToggleSpeak: message.author == MessageAuthor.assistant
              ? () => onToggleSpeak(index, message.text)
              : null,
        );
      },
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.onPromptTap});

  final void Function(String prompt) onPromptTap;

  static const _examplePrompts = [
    'What plants do the Garo people use for traditional medicine?',
    'How is climate change affecting indigenous communities?',
    "Tell me about the Garo people's matrilineal social system.",
  ];

  // Builds the first-use prompt and example questions.
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final accents = [theme.colorScheme.primary, theme.colorScheme.secondary];

    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(24, 48, 24, 24),
      child: Column(
        children: [
          const Text(
            'Ask me anything',
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
              for (var i = 0; i < _examplePrompts.length; i++)
                _PromptChip(
                  label: _examplePrompts[i],
                  color: accents[i % accents.length],
                  onTap: () => onPromptTap(_examplePrompts[i]),
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
    required this.isSpeaking,
    required this.onToggleSpeak,
  });

  final ChatMessage message;
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
                child: Text(
                  message.text,
                  style: TextStyle(
                    color: isUser ? Colors.white : const Color(0xFF26343D),
                    height: 1.45,
                    fontSize: 15,
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
                    tooltip: isSpeaking ? 'Stop reading aloud' : 'Read aloud',
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
          if (message.facts.isNotEmpty) ...[
            const SizedBox(height: 10),
            Theme(
              data: theme.copyWith(dividerColor: Colors.transparent),
              child: ExpansionTile(
                tilePadding: EdgeInsets.zero,
                childrenPadding: const EdgeInsets.only(bottom: 4),
                dense: true,
                leading: Icon(
                  Icons.hub_rounded,
                  size: 18,
                  color: theme.colorScheme.primary,
                ),
                title: Text(
                  'Facts from the knowledge graph (${message.facts.length})',
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: theme.colorScheme.primary,
                  ),
                ),
                children: message.facts
                    .map(
                      (fact) => Padding(
                        padding: const EdgeInsets.symmetric(vertical: 3),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text('\u2022  '),
                            Expanded(
                              child: Text(
                                fact,
                                style: const TextStyle(
                                  fontSize: 13,
                                  height: 1.35,
                                  color: Color(0xFF4A5A64),
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    )
                    .toList(),
              ),
            ),
          ],
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
                      backgroundColor: theme.colorScheme.primary.withValues(
                        alpha: 0.08,
                      ),
                      side: BorderSide.none,
                    ),
                  )
                  .toList(),
            ),
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
  const _Composer({
    required this.controller,
    required this.onSend,
    required this.speechAvailable,
    required this.isListening,
    required this.onToggleListening,
  });

  final TextEditingController controller;
  final VoidCallback onSend;
  final bool speechAvailable;
  final bool isListening;
  final VoidCallback onToggleListening;

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
                onSubmitted: (_) => onSend(),
                decoration: InputDecoration(
                  hintText: isListening ? 'Listening...' : 'Ask me anything',
                  prefixIcon: const Icon(Icons.search),
                  suffixIcon: speechAvailable
                      ? IconButton(
                          onPressed: onToggleListening,
                          tooltip: isListening
                              ? 'Stop listening'
                              : 'Ask by voice',
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
                colors: [theme.colorScheme.primary, theme.colorScheme.secondary],
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
              ),
              shape: BoxShape.circle,
              boxShadow: [
                BoxShadow(
                  color: theme.colorScheme.primary.withValues(alpha: 0.35),
                  blurRadius: 10,
                  offset: const Offset(0, 4),
                ),
              ],
            ),
            child: IconButton(
              onPressed: onSend,
              tooltip: 'Send question',
              icon: const Icon(Icons.arrow_upward_rounded, color: Colors.white),
            ),
          ),
        ],
      ),
    );
  }
}
