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
- Confirm the permitted voice-input data flow with the team.
- If local-only recognition is required, enforce it with a supported
  recognizer or disable voice input where it cannot be guaranteed.
- Document the user-facing behaviour and test with nonconfidential phrases.

This is a code investigation, not a network-capture verification.

## Android finding
The app does not set onDevice. The plugin defaults it to false.

The inspected Android implementation selects an on-device recognizer
when requested, on a sufficiently recent Android version, and when
on-device recognition is available. It can otherwise create a standard
recognizer. The intentLookup path also uses a standard recognizer.

Therefore this app does not enforce local-only Android recognition.
External processing is possible, depending on the installed recognition
service and configuration. No network capture was performed; actual
endpoints and retention policies remain unverified.

## Scope and recommendation
The Jira investigation covers web/Chrome and Android. Native macOS and
Windows behaviour was not verified and is not claimed as local.

Treat microphone input as potentially externally processed. The team
should decide whether to retain it with appropriate disclosure or
require a recognizer that enforces local-only processing.
