"""Tests for llm_endpoint.py -- the guard that keeps LLM inference local.

WHY THIS EXISTS: the team told the supervisor that paper content goes to a
local Ollama only, and she accepted the project on that basis. Two
commitments followed, the relevant one being that human-generated data
(workshop transcripts, focus-group data) goes through the local model and
never an external one.

Before this module, that promise was a property of one string in a .env
file. Every LLM call site read its endpoint from a bare environment variable
with no validation of any kind, so OLLAMA_URL=https://api.example.com/v1
would have shipped full paper chunks to a third party with no code change,
no warning and no log line. The promise now fails loudly instead.
"""

import pytest

from llm_endpoint import ExternalLLMRefused, is_private_host, resolve_llm_endpoint


# -- hosts that are ours ------------------------------------------------------


@pytest.mark.parametrize("url", [
    "http://localhost:11434/api/generate",
    "http://127.0.0.1:11434/api/generate",
    "http://127.1.2.3:11434/api/generate",      # all of 127/8 is loopback
    "http://[::1]:11434/api/generate",
    "http://ollama:11434/api/generate",          # docker-compose service name
    "http://mandi_kg_ollama:11434/api/chat",     # the container_name in compose
    "http://10.0.0.5:11434/api/generate",
    "http://172.16.0.9:11434/api/generate",
    "http://172.31.255.254:11434/api/generate",
    "http://192.168.1.50:11434/api/generate",
    "http://ollama.local:11434/api/generate",
])
def test_private_endpoints_are_allowed(url):
    assert resolve_llm_endpoint(url) == url


def test_a_bare_hostname_is_treated_as_a_container_on_our_own_network():
    # docker-compose.yml sets OLLAMA_URL=http://ollama:11434/..., because
    # inside the network "localhost" is the app container itself. A
    # single-label host cannot be a public DNS name.
    assert is_private_host("ollama")
    assert is_private_host("some-service")


# -- hosts that are not ours --------------------------------------------------


@pytest.mark.parametrize("url", [
    "https://api.openai.com/v1/chat/completions",
    "https://api.anthropic.com/v1/messages",
    "https://generativelanguage.googleapis.com/v1/models",
    "https://api.groq.com/openai/v1/chat/completions",
    "https://openrouter.ai/api/v1/chat/completions",
    "http://8.8.8.8:11434/api/generate",
    "https://ollama.example.com/api/generate",
])
def test_external_endpoints_are_refused(url):
    with pytest.raises(ExternalLLMRefused):
        resolve_llm_endpoint(url)


@pytest.mark.parametrize("host", [
    "localhost.example.com",      # merely STARTS with localhost
    "evil-localhost.com",
    "127.0.0.1.example.com",      # merely starts with a loopback literal
    "notlocal.local.example.com",
])
def test_a_host_that_only_looks_local_is_refused(host):
    # A substring test would pass every one of these. The check has to be on
    # the parsed host, not on whether the string contains "localhost".
    assert not is_private_host(host)
    with pytest.raises(ExternalLLMRefused):
        resolve_llm_endpoint(f"https://{host}/api/generate")


@pytest.mark.parametrize("ip", ["172.15.0.1", "172.32.0.1", "11.0.0.1", "192.167.1.1"])
def test_addresses_just_outside_the_private_ranges_are_refused(ip):
    # 172.16/12 is 172.16.0.0-172.31.255.255; one octet either side is public.
    assert not is_private_host(ip)


# -- the refusal itself -------------------------------------------------------


def test_the_refusal_explains_the_commitment_and_names_the_override():
    with pytest.raises(ExternalLLMRefused) as excinfo:
        resolve_llm_endpoint("https://api.openai.com/v1/chat/completions")

    message = str(excinfo.value)
    assert "api.openai.com" in message
    assert "ALLOW_EXTERNAL_LLM" in message


def test_an_unparseable_or_schemeless_endpoint_is_refused():
    # Fail closed: if we cannot tell where this points, it does not get paper
    # text.
    for bad in ["", "not a url", "localhost:11434", "ftp://localhost/x"]:
        with pytest.raises(ExternalLLMRefused):
            resolve_llm_endpoint(bad)


# -- the override -------------------------------------------------------------


def test_an_explicit_opt_in_permits_an_external_endpoint(monkeypatch):
    # There has to be a way out for the funded private-hosting discussion,
    # but it must be deliberate and visible rather than a silent default.
    monkeypatch.setenv("ALLOW_EXTERNAL_LLM", "1")
    url = "https://api.openai.com/v1/chat/completions"
    assert resolve_llm_endpoint(url) == url


@pytest.mark.parametrize("value", ["", "0", "false", "no"])
def test_a_falsey_opt_in_does_not_permit_an_external_endpoint(monkeypatch, value):
    monkeypatch.setenv("ALLOW_EXTERNAL_LLM", value)
    with pytest.raises(ExternalLLMRefused):
        resolve_llm_endpoint("https://api.openai.com/v1/chat/completions")


def test_the_opt_in_can_be_passed_directly_rather_than_through_the_environment():
    url = "https://api.openai.com/v1/chat/completions"
    assert resolve_llm_endpoint(url, allow_external=True) == url


def test_an_explicit_false_beats_the_environment(monkeypatch):
    monkeypatch.setenv("ALLOW_EXTERNAL_LLM", "1")
    with pytest.raises(ExternalLLMRefused):
        resolve_llm_endpoint("https://api.openai.com/v1/x", allow_external=False)


# -- SDK-based providers, which have no URL to inspect ------------------------


def test_require_external_opt_in_refuses_by_default():
    # pruner/llm_judge.py ships judge_with_openai and judge_with_anthropic.
    # Those build an SDK client rather than POSTing to a URL, so
    # resolve_llm_endpoint never sees them -- but they are shown source text,
    # so the same commitment applies. LLM_JUDGE_BACKEND defaults to "none",
    # which is the only reason this was not already a live exposure path.
    from llm_endpoint import require_external_llm_opt_in

    with pytest.raises(ExternalLLMRefused) as excinfo:
        require_external_llm_opt_in("OpenAI")

    assert "OpenAI" in str(excinfo.value)
    assert "ALLOW_EXTERNAL_LLM" in str(excinfo.value)


def test_require_external_opt_in_passes_when_explicitly_allowed(monkeypatch):
    from llm_endpoint import require_external_llm_opt_in

    monkeypatch.setenv("ALLOW_EXTERNAL_LLM", "1")
    require_external_llm_opt_in("OpenAI")  # must not raise


# -- the pinned trusted host (the no-funding hosted-demo tunnel) --------------


def test_a_pinned_trusted_host_is_allowed(monkeypatch):
    monkeypatch.setenv("TRUSTED_LLM_HOST", "laptop.tailxxxx.ts.net")
    url = "https://laptop.tailxxxx.ts.net/api/generate"
    assert resolve_llm_endpoint(url) == url


def test_the_pin_is_exact_not_a_substring_or_suffix_match(monkeypatch):
    # The same "parsed host, never a substring" discipline as the rest of
    # this module -- otherwise an attacker-chosen subdomain of the pinned
    # host, or a host that merely contains it, would also pass.
    monkeypatch.setenv("TRUSTED_LLM_HOST", "laptop.tailxxxx.ts.net")
    for host in [
        "evil.laptop.tailxxxx.ts.net",
        "laptop.tailxxxx.ts.net.evil.com",
        "notlaptop.tailxxxx.ts.net",
    ]:
        assert not is_private_host(host)


def test_an_unrelated_external_host_is_still_refused_when_a_pin_is_set(monkeypatch):
    # Pinning one host must not loosen the check for everything else.
    monkeypatch.setenv("TRUSTED_LLM_HOST", "laptop.tailxxxx.ts.net")
    with pytest.raises(ExternalLLMRefused):
        resolve_llm_endpoint("https://api.openai.com/v1/chat/completions")


def test_no_pin_set_means_no_host_is_trusted_by_this_mechanism():
    assert not is_private_host("laptop.tailxxxx.ts.net")
