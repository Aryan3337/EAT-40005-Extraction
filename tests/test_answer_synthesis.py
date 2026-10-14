"""Tests for rag.py's AnswerSynthesizer.answer() -- its timeout and default model.

WHY THIS EXISTS: benchmarked on this machine's CPU Ollama, deepseek-r1:7b
(the model in use at the time) took 40.8s and mistral:7b took 40.3s to
synthesize a real answer. The timeout passed to requests.post was 30s --
below both -- so every real call timed out and silently fell back to the
templated response. Good prose was being generated and thrown away on every
single query.

Raising the timeout to 90s was not the full fix: measured 2026-10-05, 2 of 3
real deepseek-r1:7b calls still exceeded it and fell back to the template,
including one live chat request the user watched happen. deepseek-r1 is a
"thinking" model whose internal reasoning length varies the actual
wall-clock time unpredictably; mistral:7b has no such overhead and was
consistent across every benchmark run, so it is now the default model.
"""

import requests

from rag import (
    ANSWER_SYNTHESIS_CONNECT_TIMEOUT_SECONDS,
    ANSWER_SYNTHESIS_CONNECTION_RETRIES,
    ANSWER_SYNTHESIS_TIMEOUT_SECONDS,
    NO_GROUNDED_ANSWER_MESSAGE,
    SYNTHESIS_EVIDENCE_LIMIT,
    AnswerSynthesizer,
    load_demo_answer_cache,
    relevance_gate_enabled,
)


def _triple(**overrides):
    triple = {
        "subject": "GaroPeople",
        "predicate": "BILINGUAL",
        "object": "Bengali",
        "sentence_ref": "The majority of Garo people are bilingual.",
    }
    triple.update(overrides)
    return triple


def test_the_timeout_clears_the_slowest_benchmarked_default_model():
    # deepseek-r1:7b measured at 40.8s; mistral:7b (the default model) at
    # 40.3s. The timeout must clear both with real headroom, not just barely.
    assert ANSWER_SYNTHESIS_TIMEOUT_SECONDS >= 60


def test_the_default_model_has_no_reasoning_token_overhead():
    # deepseek-r1:7b is a "thinking" model whose internal reasoning length
    # varies unpredictably -- 2 of 3 real calls exceeded even the 90s
    # timeout on 2026-10-05, including one live chat request. mistral:7b has
    # no such overhead and was the consistent one across every benchmark.
    synthesizer = AnswerSynthesizer(ollama_url="http://localhost:11434/api/generate")
    assert synthesizer.model == "mistral:7b"


def test_the_configured_timeout_is_the_one_actually_sent(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout, headers=None):
        captured["timeout"] = timeout
        raise requests.Timeout("simulated")

    monkeypatch.setattr("rag.requests.post", fake_post)
    # answer_cache={} isolates this from data/demo_answer_cache.json -- this
    # question is one of the real cached prompts, and this test is about the
    # live-call path, not the cache short-circuit covered below.
    synthesizer = AnswerSynthesizer(ollama_url="http://localhost:11434/api/generate", answer_cache={})
    synthesizer.answer("What language do the Garo speak?", [_triple()])

    assert captured["timeout"] == (ANSWER_SYNTHESIS_CONNECT_TIMEOUT_SECONDS, ANSWER_SYNTHESIS_TIMEOUT_SECONDS)


def test_the_connect_timeout_is_short_so_a_dark_tunnel_fails_fast():
    # The hosted demo's OLLAMA_URL points at a Tailscale Funnel tunnel to a
    # laptop that is only turned on during the live demo. The rest of the
    # time nothing is listening there, so this has to be short -- not the
    # full 90s -- or every uncached question makes a real visitor wait a
    # minute and a half before seeing the templated fallback.
    assert ANSWER_SYNTHESIS_CONNECT_TIMEOUT_SECONDS <= 15
    assert ANSWER_SYNTHESIS_CONNECT_TIMEOUT_SECONDS < ANSWER_SYNTHESIS_TIMEOUT_SECONDS


def test_a_timeout_still_falls_back_to_the_templated_answer(monkeypatch):
    # The fallback path itself is a pre-existing feature; this just locks in
    # that raising the timeout did not remove the safety net for the case
    # where Ollama is genuinely slower than even the new ceiling.
    def fake_post(url, json, timeout, headers=None):
        raise requests.Timeout("simulated")

    monkeypatch.setattr("rag.requests.post", fake_post)
    synthesizer = AnswerSynthesizer(ollama_url="http://localhost:11434/api/generate", answer_cache={})
    answer = synthesizer.answer("What language do the Garo speak?", [_triple()])

    assert "bilingual" in answer.lower()


def test_the_synthesis_prompt_is_capped_to_the_top_n_triples(monkeypatch):
    # Measured 2026-10-07 on the real hosted-demo tunnel path: a cold,
    # 25-triple evidence prompt (~2460 tokens) takes ~62s just to prefill on
    # this CPU's ~40 tokens/sec prefill speed, before decoding even starts --
    # enough on its own to blow a 90s timeout. Triples arrive score-sorted,
    # so capping to the top N keeps the most relevant evidence while cutting
    # prefill roughly proportionally. This must not affect the separate
    # citations list the query handler builds from the full, uncapped triple
    # list -- only what gets sent to the model.
    captured = {}

    def fake_build_prompt(self, question, triples):
        captured["triples"] = triples
        return "prompt"

    monkeypatch.setattr(AnswerSynthesizer, "_build_prompt", fake_build_prompt)

    def fake_post(url, json, timeout, headers=None):
        raise requests.Timeout("simulated")

    monkeypatch.setattr("rag.requests.post", fake_post)
    many_triples = [_triple(subject=f"Subject{i}") for i in range(25)]
    synthesizer = AnswerSynthesizer(ollama_url="http://localhost:11434/api/generate", answer_cache={})
    synthesizer.answer("What language do the Garo speak?", many_triples)

    assert len(captured["triples"]) == SYNTHESIS_EVIDENCE_LIMIT
    assert captured["triples"] == many_triples[:SYNTHESIS_EVIDENCE_LIMIT]


def test_the_prompt_tells_the_model_to_ignore_off_topic_evidence():
    # Live-tested 2026-10-07: asked "What is the health status of the Garo
    # community?" with 10 retrieved triples, only 1 of which was about
    # health -- the rest were language/location/unrelated-challenges facts.
    # The model narrated almost all of them (85 words, 4 sentences) for a
    # question whose real answer is one word ("good"). Lowering the evidence
    # count alone did NOT fix it (word count went UP with only 4 triples);
    # the fix that worked was telling the model explicitly to ignore
    # off-topic evidence and stop padding -- verified live: the same
    # question with the same 10 triples dropped to a 9-word answer.
    synthesizer = AnswerSynthesizer(ollama_url="http://localhost:11434/api/generate", answer_cache={})
    prompt = synthesizer._build_prompt("What is the health status of the Garo community?", [_triple()])

    assert "ignore" in prompt.lower()
    assert "short sentence" in prompt.lower()


def test_the_prompt_does_not_demand_a_disclaimer_for_a_fully_answered_question():
    # The other half of the same live finding: the model was adding a
    # boilerplate "further research might be necessary" hedge to EVERY
    # answer, even a single high-confidence fact that fully answers the
    # question. Traced to the old prompt's unconditional "if the evidence is
    # incomplete, acknowledge the limitation" line being applied out of
    # habit rather than when actually needed.
    synthesizer = AnswerSynthesizer(ollama_url="http://localhost:11434/api/generate", answer_cache={})
    prompt = synthesizer._build_prompt("What is the health status of the Garo community?", [_triple()])

    assert "out of habit" in prompt.lower()


def test_a_bare_connection_failure_is_retried(monkeypatch):
    # Live-tested 2026-10-07 against the real hosted tunnel: with the laptop
    # and Funnel genuinely up and every layer individually confirmed healthy,
    # 1 of 3 identical requests still failed to connect at all in well under
    # a second, while the other 2 succeeded with real generation moments
    # apart. The proxy's own log showed no trace of the failed attempt ever
    # arriving -- the drop is in the network path, not this code -- so one
    # retry is enough to mask a single transient blip.
    # This test is about the HTTP-layer retry, not gate parsing (covered by
    # its own tests below) -- disable the gate rather than coupling this
    # fixture to _parse_gated_response's marker-stripping behaviour.
    monkeypatch.setenv("SYNTHESIS_RELEVANCE_GATE", "0")
    calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"response": "Second attempt succeeded."}

    def fake_post(url, json, timeout, headers=None):
        calls.append(1)
        if len(calls) == 1:
            raise requests.ConnectionError("simulated transient drop")
        return FakeResponse()

    monkeypatch.setattr("rag.requests.post", fake_post)
    synthesizer = AnswerSynthesizer(ollama_url="http://localhost:11434/api/generate", answer_cache={})
    answer = synthesizer.answer("What language do the Garo speak?", [_triple()])

    assert answer == "Second attempt succeeded."
    assert len(calls) == 2


def test_a_persistent_connection_failure_still_falls_back(monkeypatch):
    calls = []

    def fake_post(url, json, timeout, headers=None):
        calls.append(1)
        raise requests.ConnectionError("simulated persistent drop")

    monkeypatch.setattr("rag.requests.post", fake_post)
    synthesizer = AnswerSynthesizer(ollama_url="http://localhost:11434/api/generate", answer_cache={})
    answer = synthesizer.answer("What language do the Garo speak?", [_triple()])

    assert "bilingual" in answer.lower()
    # Exactly the original attempt plus the configured number of retries --
    # not an unbounded loop.
    assert len(calls) == ANSWER_SYNTHESIS_CONNECTION_RETRIES + 1


def test_a_slow_but_connected_timeout_is_not_retried(monkeypatch):
    # Retrying a bare connection failure is cheap (fails in well under a
    # second). Retrying a full generation timeout would double a 130s wait
    # for a visitor who is already watching a long spinner -- this locks in
    # that only ConnectionError triggers a retry, not the broader Timeout a
    # slow-but-connected generation raises.
    calls = []

    def fake_post(url, json, timeout, headers=None):
        calls.append(1)
        raise requests.Timeout("simulated slow generation")

    monkeypatch.setattr("rag.requests.post", fake_post)
    synthesizer = AnswerSynthesizer(ollama_url="http://localhost:11434/api/generate", answer_cache={})
    answer = synthesizer.answer("What language do the Garo speak?", [_triple()])

    assert "bilingual" in answer.lower()
    assert len(calls) == 1


def test_a_response_within_the_timeout_is_used_as_is(monkeypatch):
    # This test is about the immediate-success pass-through, not gate
    # parsing (covered by its own tests below) -- disable the gate rather
    # than coupling this fixture to _parse_gated_response's behaviour.
    monkeypatch.setenv("SYNTHESIS_RELEVANCE_GATE", "0")

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"response": "The Garo are bilingual in Bengali."}

    def fake_post(url, json, timeout, headers=None):
        return FakeResponse()

    monkeypatch.setattr("rag.requests.post", fake_post)
    synthesizer = AnswerSynthesizer(ollama_url="http://localhost:11434/api/generate", answer_cache={})
    answer = synthesizer.answer("What language do the Garo speak?", [_triple()])

    assert answer == "The Garo are bilingual in Bengali."


# -- the demo answer cache -----------------------------------------------------


def test_a_cached_question_short_circuits_the_live_call(monkeypatch):
    def fake_post(url, json, timeout, headers=None):
        raise AssertionError("Ollama should not be called for a cached question")

    monkeypatch.setattr("rag.requests.post", fake_post)
    synthesizer = AnswerSynthesizer(
        ollama_url="http://localhost:11434/api/generate",
        answer_cache={"where do the garo live?": "They live in the Garo Hills."},
    )
    answer = synthesizer.answer("Where do the Garo live?", [_triple()])

    assert answer == "They live in the Garo Hills."


def test_cache_lookup_ignores_case_and_surrounding_whitespace():
    synthesizer = AnswerSynthesizer(
        ollama_url="http://localhost:11434/api/generate",
        answer_cache={"where do the garo live?": "They live in the Garo Hills."},
    )
    answer = synthesizer.answer("  WHERE DO THE GARO LIVE?  ", [_triple()])

    assert answer == "They live in the Garo Hills."


def test_an_uncached_question_is_not_affected_by_a_nonempty_cache(monkeypatch):
    def fake_post(url, json, timeout, headers=None):
        raise requests.Timeout("simulated")

    monkeypatch.setattr("rag.requests.post", fake_post)
    synthesizer = AnswerSynthesizer(
        ollama_url="http://localhost:11434/api/generate",
        answer_cache={"where do the garo live?": "They live in the Garo Hills."},
    )
    answer = synthesizer.answer("What language do the Garo speak?", [_triple()])

    assert "bilingual" in answer.lower()


def test_loading_a_missing_cache_file_returns_empty(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    assert load_demo_answer_cache(missing) == {}


def test_loading_the_cache_file_normalizes_its_keys(tmp_path):
    cache_file = tmp_path / "cache.json"
    cache_file.write_text(
        '{"  Where Do The Garo Live?  ": "They live in the Garo Hills."}',
        encoding="utf-8",
    )
    cache = load_demo_answer_cache(cache_file)

    assert cache == {"where do the garo live?": "They live in the Garo Hills."}


# -- the relevance gate's parser ---------------------------------------------
#
# WHY THIS EXISTS: measured live 2026-10-08, synthesis fabricated a citation
# ("as stated in Putz (1991) who identified family as one of the domains of
# study") linking two facts that share only the keyword "family". The model's
# own answer OPENED with "The evidence provided does not directly answer..."
# and then kept writing anyway -- its judgement was never the broken part, the
# unconstrained continuation was. So the parser's job is to discard everything
# after a "no" in code. Two prior prompt-only fixes that asked the model to
# restrain itself were both reverted after failing live retests.


def _synthesizer():
    return AnswerSynthesizer(
        ollama_url="http://localhost:11434/api/generate", answer_cache={}
    )


def test_a_yes_marker_returns_the_prose_below_it():
    result = _synthesizer()._parse_gated_response(
        "RELEVANT: yes\nThe Garo community speaks Garo and Mandi."
    )
    assert result == "The Garo community speaks Garo and Mandi."


def test_a_no_marker_discards_everything_the_model_wrote_after_it():
    # The exact 2026-10-08 failure shape: an honest opener followed by
    # fabricated bridging prose. The prose must not survive.
    result = _synthesizer()._parse_gated_response(
        "RELEVANT: no\nHowever, it is mentioned that traditional practices "
        "are being modified in response to modernization, as stated in "
        "Putz (1991)."
    )
    assert result is None


def test_a_missing_marker_fails_closed():
    result = _synthesizer()._parse_gated_response(
        "The Garo community resides primarily in the Garo Hills."
    )
    assert result is None


def test_an_unrecognised_marker_value_fails_closed():
    # "nope" must not be read as a prefix of "no" -- nor as a yes.
    assert _synthesizer()._parse_gated_response("RELEVANT: nope\nSomething.") is None
    assert _synthesizer()._parse_gated_response("RELEVANT: maybe\nSomething.") is None


def test_a_thinking_model_preamble_is_stripped_before_the_marker_is_read():
    # deepseek-r1:7b emits <think>...</think> before anything else. Without
    # _clean_response running first, the marker is never on the first line
    # and every answer would fail closed.
    result = _synthesizer()._parse_gated_response(
        "<think>The user asks about language. The evidence covers it.</think>\n"
        "RELEVANT: yes\nThe Garo community speaks Garo."
    )
    assert result == "The Garo community speaks Garo."


def test_the_marker_is_case_and_whitespace_insensitive():
    result = _synthesizer()._parse_gated_response(
        "  relevant:YES  \n\nThe Garo community speaks Garo."
    )
    assert result == "The Garo community speaks Garo."


def test_a_yes_marker_with_no_answer_body_fails_closed():
    assert _synthesizer()._parse_gated_response("RELEVANT: yes\n   \n") is None


def test_a_yes_marker_sharing_its_line_with_the_answer_still_returns_it():
    # Robustness against format drift: if the model puts the marker and the
    # answer on one line, dropping the answer would cause a false refusal --
    # the over-refusal risk called out in the spec's risks section.
    result = _synthesizer()._parse_gated_response(
        "RELEVANT: yes The Garo community speaks Garo."
    )
    assert result == "The Garo community speaks Garo."


def test_the_gate_is_on_by_default(monkeypatch):
    # Default ON is the whole point -- an unset variable must not silently
    # disable the fix. Note the default passed to os.getenv is "on", NOT ""
    # ("" is in _FALSEY and would invert this).
    monkeypatch.delenv("SYNTHESIS_RELEVANCE_GATE", raising=False)
    assert relevance_gate_enabled() is True


def test_the_gate_can_be_switched_off_for_demo_rollback(monkeypatch):
    for value in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("SYNTHESIS_RELEVANCE_GATE", value)
        assert relevance_gate_enabled() is False, value


def test_the_prompt_carries_the_gate_instruction_when_enabled(monkeypatch):
    monkeypatch.delenv("SYNTHESIS_RELEVANCE_GATE", raising=False)
    prompt = _synthesizer()._build_prompt("What language do they speak?", [_triple()])
    assert "RELEVANT: yes" in prompt
    assert "RELEVANT: no" in prompt


def test_the_prompt_omits_the_gate_instruction_when_switched_off(monkeypatch):
    monkeypatch.setenv("SYNTHESIS_RELEVANCE_GATE", "0")
    prompt = _synthesizer()._build_prompt("What language do they speak?", [_triple()])
    assert "RELEVANT:" not in prompt


def _fake_ollama(text):
    """Stubs a successful Ollama call returning `text` as the model output."""

    class _Response:
        status_code = 200

        @staticmethod
        def json():
            return {"response": text}

    def fake_post(url, json, timeout, headers=None):
        return _Response()

    return fake_post


def test_a_gated_refusal_returns_the_honest_message(monkeypatch):
    monkeypatch.delenv("SYNTHESIS_RELEVANCE_GATE", raising=False)
    monkeypatch.setattr(
        "rag.requests.post",
        _fake_ollama("RELEVANT: no\nHowever, traditional practices are being modified."),
    )
    result = _synthesizer().answer("How do the Garo trace inheritance?", [_triple()])
    assert result == NO_GROUNDED_ANSWER_MESSAGE


def test_a_gated_refusal_does_not_fall_back_to_the_triple_templates(monkeypatch):
    # _fallback_answer renders "Based on the available knowledge, ..." from
    # the triples -- the exact off-topic padding this gate exists to remove.
    # A refusal must not route into it.
    monkeypatch.delenv("SYNTHESIS_RELEVANCE_GATE", raising=False)
    monkeypatch.setattr("rag.requests.post", _fake_ollama("RELEVANT: no\nSomething."))
    result = _synthesizer().answer("How do the Garo trace inheritance?", [_triple()])
    assert "Based on the available knowledge" not in result
    assert "bilingual" not in result.lower()


def test_a_gated_pass_returns_the_models_prose(monkeypatch):
    monkeypatch.delenv("SYNTHESIS_RELEVANCE_GATE", raising=False)
    monkeypatch.setattr(
        "rag.requests.post",
        _fake_ollama("RELEVANT: yes\nThe Garo people are bilingual in Bengali."),
    )
    result = _synthesizer().answer("What languages do they speak?", [_triple()])
    assert result == "The Garo people are bilingual in Bengali."


def test_an_unmarked_response_fails_closed_rather_than_passing_prose_through(monkeypatch):
    monkeypatch.delenv("SYNTHESIS_RELEVANCE_GATE", raising=False)
    monkeypatch.setattr("rag.requests.post", _fake_ollama("The Garo people are bilingual."))
    result = _synthesizer().answer("What languages do they speak?", [_triple()])
    assert result == NO_GROUNDED_ANSWER_MESSAGE


def test_with_the_gate_off_prose_is_returned_unmodified(monkeypatch):
    # The rollback path must behave exactly as before: no marker expected,
    # no parsing, model output returned as-is.
    monkeypatch.setenv("SYNTHESIS_RELEVANCE_GATE", "0")
    monkeypatch.setattr("rag.requests.post", _fake_ollama("The Garo people are bilingual."))
    result = _synthesizer().answer("What languages do they speak?", [_triple()])
    assert result == "The Garo people are bilingual."


def test_an_explicit_no_is_logged_distinctly_from_an_unparseable_response(monkeypatch, capsys):
    # OLLAMA_MODEL is env-overridable; if the swapped-in model does not honour
    # the RELEVANT: format, every answer silently becomes a refusal with no
    # way to tell format collapse from a genuine "no" mid-demo. answer() must
    # print a line naming which branch fired, and the two branches must read
    # differently from each other.
    monkeypatch.delenv("SYNTHESIS_RELEVANCE_GATE", raising=False)

    monkeypatch.setattr(
        "rag.requests.post", _fake_ollama("RELEVANT: no\nSomething.")
    )
    _synthesizer().answer("How do the Garo trace inheritance?", [_triple()])
    no_output = capsys.readouterr().out

    monkeypatch.setattr(
        "rag.requests.post", _fake_ollama("The Garo people are bilingual.")
    )
    _synthesizer().answer("What languages do they speak?", [_triple()])
    unreadable_output = capsys.readouterr().out

    assert no_output.strip()
    assert unreadable_output.strip()
    assert no_output != unreadable_output
    assert "no" in no_output.lower()
    assert "unreadable" in unreadable_output.lower() or "missing" in unreadable_output.lower()


def test_a_comma_after_the_marker_is_consumed_not_leaked_into_the_answer():
    # Verified live 2026-10-08: "RELEVANT: yes, the evidence covers it. The
    # Garo speak Garo." left a stray leading comma AND leaked the gate's own
    # meta-commentary onto the demo screen, because the marker regex's
    # [.:]? only consumed a period or colon, not a comma.
    result = _synthesizer()._parse_gated_response(
        "RELEVANT: yes, the evidence covers it. The Garo speak Garo."
    )
    assert result is not None
    assert not result.startswith(",")
    assert ", the evidence covers it." not in result


def test_a_cached_answer_is_never_run_through_the_gate(monkeypatch):
    # Cached demo answers contain no RELEVANT marker, so if the gate were
    # ever applied before the cache short-circuit, all three scripted demo
    # questions would fail closed and refuse on stage. Locks the ordering.
    monkeypatch.delenv("SYNTHESIS_RELEVANCE_GATE", raising=False)

    def explode(*args, **kwargs):
        raise AssertionError("a cached answer must not reach Ollama")

    monkeypatch.setattr("rag.requests.post", explode)
    synthesizer = AnswerSynthesizer(
        ollama_url="http://localhost:11434/api/generate",
        answer_cache={"where do the garo live?": "The Garo live in Mymensingh."},
    )
    assert synthesizer.answer("Where do the Garo live?", [_triple()]) == (
        "The Garo live in Mymensingh."
    )
