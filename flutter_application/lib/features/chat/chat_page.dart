import 'package:flutter/material.dart';

import '../../models/chat_conversation.dart';
import '../../models/chat_message.dart';
import '../../services/chat_history_service.dart';
import '../../services/chat_service.dart';

// Hosts the conversation layout and coordinates user input with RAG.py.
class ChatPage extends StatefulWidget {
  const ChatPage({
    super.key,
    required this.service,
    this.onSignOut,
    this.userEmail = 'local-user',
    this.historyService,
  });

  final ChatService service;
  final VoidCallback? onSignOut;
  final String userEmail;
  final ChatHistoryService? historyService;

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
  bool _isLoading = false;

  @override
  void initState() {
    super.initState();
    _historyService = widget.historyService ?? ChatHistoryService();
    _loadHistory();
  }

  Future<void> _loadHistory() async {
    final history = await _historyService.load(widget.userEmail);
    if (!mounted) return;
    setState(() {
      _history = history;
      _isHistoryLoading = false;
    });
  }

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
      _conversationId ??= DateTime.now().microsecondsSinceEpoch.toString();
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
    await _saveCurrentConversation();
    _scrollToBottom();
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
    await _historyService.save(widget.userEmail, updated);
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

    setState(() {
      _messages[messageIndex] = _messages[messageIndex].copyWith(
        feedback: feedback,
        feedbackComment: comment.trim(),
      );
    });

    await _saveCurrentConversation();
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

  // Clears the current conversation and starts a fresh session.
  Future<void> _startNewChat() async {
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
    await _historyService.delete(widget.userEmail, conversation.id);
    if (!mounted) return;
    setState(() {
      _history.removeWhere((item) => item.id == conversation.id);
      if (_conversationId == conversation.id) {
        _messages.clear();
        _conversationId = null;
      }
    });
  }

  // Builds the complete assistant workspace.
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      drawer: _HistoryDrawer(
        history: _history,
        isLoading: _isHistoryLoading,
        onOpen: _openConversation,
        onDelete: _deleteConversation,
        onNewChat: _startNewChat,
      ),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1120),
            child: Column(
              children: [
                _ChatHeader(
                  onNewChat: _startNewChat,
                  onSignOut: widget.onSignOut,
                ),
                Expanded(
                  child: _ConversationView(
                    messages: _messages,
                    controller: _scrollController,
                    isLoading: _isLoading,
                    onFeedback: _updateMessageFeedback,
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
  const _ChatHeader({required this.onNewChat, this.onSignOut});

  final Future<void> Function() onNewChat;
  final VoidCallback? onSignOut;

  // Builds the product identity and session controls.
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(24, 22, 24, 12),
      child: Row(
        children: [
          Builder(
            builder: (context) => IconButton(
              onPressed: () => Scaffold.of(context).openDrawer(),
              tooltip: 'Chat history',
              icon: const Icon(Icons.menu_rounded),
            ),
          ),
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
          if (onSignOut != null)
            IconButton(
              onPressed: onSignOut,
              tooltip: 'Sign out',
              icon: const Icon(Icons.logout_outlined),
            ),
        ],
      ),
    );
  }
}

class _HistoryDrawer extends StatelessWidget {
  const _HistoryDrawer({
    required this.history,
    required this.isLoading,
    required this.onOpen,
    required this.onDelete,
    required this.onNewChat,
  });

  final List<ChatConversation> history;
  final bool isLoading;
  final Future<void> Function(ChatConversation conversation) onOpen;
  final Future<void> Function(ChatConversation conversation) onDelete;
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
                  const Expanded(
                    child: Text(
                      'Chat history',
                      style: TextStyle(
                        fontSize: 21,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  IconButton(
                    onPressed: onNewChat,
                    tooltip: 'New chat',
                    icon: const Icon(Icons.add_comment_outlined),
                  ),
                ],
              ),
            ),
            const Divider(height: 1),
            Expanded(
              child: isLoading
                  ? const Center(child: CircularProgressIndicator())
                  : history.isEmpty
                  ? const Center(
                      child: Padding(
                        padding: EdgeInsets.all(24),
                        child: Text(
                          'Your saved conversations will appear here.',
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
                            tooltip: 'Delete conversation',
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

class _ConversationView extends StatelessWidget {
  const _ConversationView({
    required this.messages,
    required this.controller,
    required this.isLoading,
    required this.onFeedback,
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
        return _MessageBubble(
          message: messages[index],
          messageIndex: index,
          onFeedback: onFeedback,
        );
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

class _MessageBubble extends StatelessWidget {
  const _MessageBubble({
    required this.message,
    required this.messageIndex,
    required this.onFeedback,
  });

  final ChatMessage message;
  final int messageIndex;
  final Future<void> Function(
    int messageIndex,
    MessageFeedback feedback,
    String comment,
  )
  onFeedback;

  // Builds a user or assistant message with verifiable source evidence.
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
                    'View verified sources (${message.sources.length})',
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
              const Text(
                'Was this response helpful?',
                style: TextStyle(
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
                    tooltip: 'Helpful',
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
                    tooltip: 'Not helpful',
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
                          ? 'Add comment'
                          : 'Edit comment',
                    ),
                  ),
                ],
              ),
              if (message.feedback != null)
                const Text(
                  'Thank you for your feedback.',
                  style: TextStyle(fontSize: 12, color: Color(0xFF2E7D5B)),
                ),
              if (message.feedbackComment.isNotEmpty) ...[
                const SizedBox(height: 6),
                Text(
                  'Comment: ${message.feedbackComment}',
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
      ),
    );
  }

  Future<void> _showCommentDialog(BuildContext context) async {
    if (message.feedback == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Please select helpful or not helpful first.'),
        ),
      );
      return;
    }

    final controller = TextEditingController(text: message.feedbackComment);

    final comment = await showDialog<String>(
      context: context,
      builder: (dialogContext) {
        return AlertDialog(
          title: const Text('Response feedback'),
          content: TextField(
            controller: controller,
            autofocus: true,
            maxLines: 4,
            maxLength: 300,
            decoration: const InputDecoration(
              hintText: 'Tell us how this response could be improved.',
              border: OutlineInputBorder(),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.of(dialogContext).pop(controller.text),
              child: const Text('Save feedback'),
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
            'Source $number',
            style: const TextStyle(
              fontWeight: FontWeight.w700,
              color: Color(0xFF2E7D5B),
            ),
          ),
          if (source.sourceSection.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text('Section: ${source.sourceSection}'),
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
              'Knowledge graph: ${source.triple}',
              style: const TextStyle(fontSize: 13, color: Color(0xFF52616A)),
            ),
          ],
          if (source.confidence.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              'Confidence: ${source.confidence}',
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
