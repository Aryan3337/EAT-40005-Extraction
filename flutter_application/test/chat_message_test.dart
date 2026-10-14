import 'package:flutter_test/flutter_test.dart';

import 'package:flutter_application/models/chat_message.dart';

// SCRUM-366: a missing translation is detected instead of silently falling
// back to another language.
void main() {
  const answer = ChatMessage(
    text: 'The Garo live in Meghalaya.',
    author: MessageAuthor.assistant,
    translations: {
      'en': 'The Garo live in Meghalaya.',
      'hi': 'गारो लोग मेघालय में रहते हैं।',
    },
  );

  test('a saved translation is used and not flagged', () {
    expect(answer.hasTextFor('hi'), isTrue);
    expect(answer.textFor('hi'), 'गारो लोग मेघालय में रहते हैं।');
    expect(answer.displayLanguageFor('hi'), 'hi');
  });

  test('a missing translation is flagged with the language actually shown', () {
    expect(answer.hasTextFor('bn'), isFalse);
    expect(answer.textFor('bn'), 'The Garo live in Meghalaya.');
    expect(answer.displayLanguageFor('bn'), 'en');
  });

  test('messages without translations are never flagged', () {
    const question = ChatMessage(text: 'Hello', author: MessageAuthor.user);
    expect(question.hasTextFor('bn'), isTrue);
    expect(question.displayLanguageFor('bn'), 'bn');
  });
}
