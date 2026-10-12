import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:flutter_application/app/app_localizations.dart';
import 'package:flutter_application/models/chat_message.dart';
import 'package:flutter_application/services/chat_service.dart';

void main() {
  group('ChatService source verification', () {
    test('parses knowledge-graph triples as source evidence', () async {
      final client = MockClient((request) async {
        expect(jsonDecode(request.body), {
          'query': 'Where do the Garo people live?',
          'language': 'en',
        });

        return http.Response(
          jsonEncode({
            'answer': 'The Garo people live in several districts.',
            'triples': [
              {
                'subject': 'GaroCommunity',
                'predicate': 'IS_RESIDENT_IN',
                'object': 'Tangail',
                'sentence_ref':
                    'They reside in several districts including Tangail.',
                'source_section': 'Page 1',
                'passage': '',
                'confidence': 'High',
              },
            ],
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final service = ChatService(
        client: client,
        endpoint: 'http://localhost/query',
      );

      final message = await service.ask('Where do the Garo people live?');

      expect(message.author, MessageAuthor.assistant);
      expect(message.text, 'The Garo people live in several districts.');
      expect(message.sources, hasLength(1));
      expect(message.sources.single.sourceSection, 'Page 1');
      expect(message.sources.single.confidence, 'High');
      expect(
        message.sources.single.supportingText,
        'They reside in several districts including Tangail.',
      );
      expect(
        message.sources.single.triple,
        'GaroCommunity — IS_RESIDENT_IN → Tangail',
      );
    });

    test('sends the selected answer language to the RAG API', () async {
      final client = MockClient((request) async {
        expect(jsonDecode(request.body), {
          'query': 'Where do the Garo people live?',
          'language': 'fr',
        });
        return http.Response(
          jsonEncode({'answer': 'Les Garo vivent dans plusieurs régions.'}),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final service = ChatService(
        client: client,
        endpoint: 'http://localhost/query',
      );
      final message = await service.ask(
        'Where do the Garo people live?',
        language: 'fr',
      );
      expect(message.text, 'Les Garo vivent dans plusieurs régions.');
    });

    test('localizes RAG API errors using the active app language', () async {
      final client = MockClient((request) async {
        return http.Response(
          jsonEncode({
            'error': 'Could not translate the answer into Bangla. Check the translation service connection and retry.',
            'language': 'bn',
          }),
          503,
          headers: {'content-type': 'application/json'},
        );
      });

      final service = ChatService(
        client: client,
        endpoint: 'http://localhost/query',
        strings: () => const AppLocalizations('bn'),
      );
      final message = await service.ask(
        'Where do the Garo people live?',
        language: 'bn',
      );

      expect(message.text, startsWith('RAG অনুরোধ ব্যর্থ হয়েছে (HTTP 503):'));
      expect(
        message.text,
        contains('Could not translate the answer into Bangla'),
      );
      expect(message.text, isNot('ragHttpError'));
    });

    test(
      'keeps all translated answers for instant language switching',
      () async {
        final client = MockClient((request) async {
          return http.Response(
            jsonEncode({
              'answer': 'गारो लोग बांग्लादेश में रहते हैं।',
              'translations': {
                'en': 'The Garo people live in Bangladesh.',
                'hi': 'गारो लोग बांग्लादेश में रहते हैं।',
                'bn': 'গারো জনগণ বাংলাদেশে বাস করে।',
              },
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        });

        final service = ChatService(
          client: client,
          endpoint: 'http://localhost/query',
        );
        final message = await service.ask(
          'गारो लोग कहाँ रहते हैं?',
          language: 'hi',
        );
        final restored = ChatMessage.fromJson(message.toJson());

        expect(restored.textFor('en'), 'The Garo people live in Bangladesh.');
        expect(restored.textFor('hi'), 'गारो लोग बांग्लादेश में रहते हैं।');
        expect(restored.textFor('bn'), 'গারো জনগণ বাংলাদেশে বাস করে।');
      },
    );

    test('preserves source evidence in chat-history JSON', () {
      const original = ChatMessage(
        text: 'Verified answer',
        author: MessageAuthor.assistant,
        sources: [
          SourceEvidence(
            subject: 'GaroCommunity',
            predicate: 'IS_RESIDENT_IN',
            object: 'Tangail',
            sentenceRef: 'Supporting sentence.',
            sourceSection: 'Page 1',
            passage: '',
            confidence: 'High',
          ),
        ],
      );

      final restored = ChatMessage.fromJson(original.toJson());

      expect(restored.text, original.text);
      expect(restored.author, original.author);
      expect(restored.sources, hasLength(1));
      expect(restored.sources.single.triple, original.sources.single.triple);
      expect(restored.sources.single.supportingText, 'Supporting sentence.');
    });
    test('preserves response feedback in chat-history JSON', () {
      const original = ChatMessage(
        text: 'A response with user feedback',
        author: MessageAuthor.assistant,
        feedback: MessageFeedback.notHelpful,
        feedbackComment: 'The answer needs more cultural context.',
      );

      final restored = ChatMessage.fromJson(original.toJson());

      expect(restored.feedback, MessageFeedback.notHelpful);
      expect(
        restored.feedbackComment,
        'The answer needs more cultural context.',
      );
    });
  });
}
