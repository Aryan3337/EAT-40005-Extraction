# SCRUM-368: Voice-input data flow

## Inspected implementation
The app uses speech_to_text 7.4.0.
SpeechService selects a locale and receives recognizedWords.
ChatPage places the transcript into the question input field.

## Browser finding
The installed speech_to_text_web.dart accepts onDevice, but its
listen implementation does not apply it or set processLocally.
Adding onDevice: true in the app therefore does not establish
local-only browser recognition.

Microphone audio is handled by the browser recognition service
and may be processed externally. The inspected code does not
identify the actual processing endpoint or retention policy.

## Separate paths
Voice input is separate from backend read-aloud and translation.
Local TTS or translation does not establish local voice recognition.

## Remaining follow-up
- Verify native macOS and Windows recognition behaviour.
- Confirm the permitted voice-input data flow with the team.
- If local-only recognition is required, enforce it with a supported
  recognizer or disable voice input where it cannot be guaranteed.
- Document the user-facing behaviour and test with nonconfidential phrases.

This is a code investigation, not a network-capture verification.
