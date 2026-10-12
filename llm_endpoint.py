"""Keeps LLM inference on infrastructure we control.

The team told the project supervisor that paper content goes to a local
Ollama model inside Docker and does not leave our infrastructure, and she
accepted the project on that basis. Two commitments followed; the one this
module enforces is that human-generated data -- workshop transcripts,
focus-group material -- goes through the local model and never an external
one.

Before this module, that was a property of one string in a .env file. Every
LLM call site read its endpoint from a bare environment variable with no
validation anywhere in the codebase, so

    OLLAMA_URL=https://api.some-provider.com/v1/chat/completions

would have sent full 1500-word paper chunks to a third party with no code
change, no warning and no log line. One mistyped or copy-pasted .env was the
whole distance between the commitment and breaking it.

Every call site now resolves its endpoint through resolve_llm_endpoint(),
which refuses a host that is not on our own network. The refusal is loud and
immediate rather than a fallback, because the failure it prevents is silent
by nature: an external endpoint that works looks exactly like a local one
that works.

ALLOW_EXTERNAL_LLM=1 overrides it. That exists for the funded private-hosting
discussion, where a model may legitimately run on a paid instance -- it has
to be deliberate and visible, never a default.

TRUSTED_LLM_HOST pins exactly one external hostname as trusted -- narrower
than ALLOW_EXTERNAL_LLM=1, which accepts any external host. This is for the
no-funding hosted demo: the API runs in the cloud, but inference stays on
the team's own laptop, reached back over a tunnel (e.g. a Tailscale Funnel
hostname) rather than a paid instance. The hostname is still infrastructure
the team controls, not a third-party model provider; pinning it exactly
means a copy-pasted unrelated external URL is still refused.

That tunnel hostname is PUBLIC once Funnel is on, though, and Ollama itself
has no password -- see ollama_tunnel_proxy.py, which sits in front of it and
only forwards a request carrying OLLAMA_TUNNEL_SECRET (header
OLLAMA_TUNNEL_SECRET_HEADER below). ollama_tunnel_headers() is the sending
side of that: every call site that might be talking to the tunnel (rag.py's
AnswerSynthesizer, confidence_framework.py's call_ollama) attaches it. It is
a plain dict, empty when OLLAMA_TUNNEL_SECRET is not set, which is the
normal case for a local, non-tunnelled Ollama that was never asked for it.

NOT COVERED: kg_filter.py and script.py also build Ollama URLs and are not
routed through here. kg_filter.py is unwired (imported by nothing) and both
are teammates' files on the main branch; they are listed as a known gap
rather than edited here.
"""

import ipaddress
import os
from typing import Dict
from urllib.parse import urlparse

ALLOW_EXTERNAL_ENV = "ALLOW_EXTERNAL_LLM"
_PERMITTED_SCHEMES = {"http", "https"}
_FALSEY = {"", "0", "false", "no", "off"}

OLLAMA_TUNNEL_SECRET_HEADER = "X-Tunnel-Secret"


def ollama_tunnel_headers() -> Dict[str, str]:
    """The shared-secret header ollama_tunnel_proxy.py requires once Funnel
    is on. Empty when OLLAMA_TUNNEL_SECRET isn't set -- the normal case for
    a local, non-tunnelled Ollama, which was never asked for this header."""
    secret = os.environ.get("OLLAMA_TUNNEL_SECRET", "")
    return {OLLAMA_TUNNEL_SECRET_HEADER: secret} if secret else {}


class ExternalLLMRefused(RuntimeError):
    """An LLM endpoint outside our own network was configured."""


def _looks_like_an_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def is_private_host(host: str) -> bool:
    """True when `host` is on infrastructure we control.

    Matching is on the PARSED host, never on a substring: "localhost" is
    local but "localhost.example.com" and "127.0.0.1.example.com" are
    someone else's machines, and a `"localhost" in url` test would wave both
    through.
    """
    if not host:
        return False

    host = host.strip().strip("[]").rstrip(".").lower()
    if not host:
        return False

    if _looks_like_an_ip(host):
        address = ipaddress.ip_address(host)
        # is_private covers 10/8, 172.16/12, 192.168/16 and fc00::/7;
        # loopback covers 127/8 and ::1. One octet outside those ranges
        # (172.15.x, 172.32.x) is a public address and is refused.
        return address.is_private or address.is_loopback

    if host == "localhost":
        return True

    # A single-label hostname cannot be a public DNS name, so it is a
    # container or a machine on the local network -- docker-compose.yml
    # relies on exactly this, setting OLLAMA_URL=http://ollama:11434/...
    # because inside the network "localhost" is the app container itself.
    if "." not in host:
        return True

    # mDNS / local-network suffixes.
    if host.endswith(".local") or host.endswith(".internal"):
        return True

    pinned = os.getenv("TRUSTED_LLM_HOST", "").strip().strip("[]").rstrip(".").lower()
    return bool(pinned) and host == pinned


def _external_allowed(allow_external: bool | None) -> bool:
    if allow_external is not None:
        return allow_external
    return os.getenv(ALLOW_EXTERNAL_ENV, "").strip().lower() not in _FALSEY


def require_external_llm_opt_in(provider: str, *, allow_external: bool | None = None) -> None:
    """Gate a provider reached through its own SDK rather than a URL.

    pruner/llm_judge.py ships judge_with_openai and judge_with_anthropic.
    Those construct an SDK client, so there is no endpoint string for
    resolve_llm_endpoint to inspect -- but the judge is shown source text, so
    the commitment applies to them just the same. LLM_JUDGE_BACKEND defaults
    to "none", which is the only reason selecting one was not already a live
    exposure path.
    """
    if _external_allowed(allow_external):
        return

    raise ExternalLLMRefused(
        f"Refusing to send content to {provider}, a third-party model "
        f"provider.\n\n"
        f"This project committed to the supervisor that paper content and "
        f"human-generated data (workshop transcripts, focus-group material) "
        f"go to a LOCAL model only. Use the 'ollama' judge backend instead.\n\n"
        f"If {provider} is genuinely intended -- a decision for the funded "
        f"hosting discussion, not a configuration detail -- set "
        f"{ALLOW_EXTERNAL_ENV}=1 to override this check."
    )


def resolve_llm_endpoint(url: str, *, allow_external: bool | None = None) -> str:
    """Return `url` if inference would stay on our own network, else raise.

    Fails closed: an endpoint we cannot parse, or one with a scheme other
    than http/https, is refused rather than assumed safe. If we cannot tell
    where it points, it does not get paper text.
    """
    parsed = urlparse(url or "")
    host = parsed.hostname

    if parsed.scheme not in _PERMITTED_SCHEMES or not host:
        raise ExternalLLMRefused(
            f"Cannot tell where this LLM endpoint points, so it is refused: "
            f"{url!r}. Expected an http(s) URL with a host, such as "
            f"http://localhost:11434/api/generate. Set "
            f"{ALLOW_EXTERNAL_ENV}=1 only if an external model provider is "
            f"genuinely intended."
        )

    if is_private_host(host) or _external_allowed(allow_external):
        return url

    raise ExternalLLMRefused(
        f"Refusing to send content to the LLM endpoint {url!r}: host "
        f"{host!r} is not on our own network.\n\n"
        f"This project committed to the supervisor that paper content and "
        f"human-generated data (workshop transcripts, focus-group material) "
        f"go to a LOCAL model only and are never sent to a third-party "
        f"model provider.\n\n"
        f"If an external provider is genuinely intended -- which is a "
        f"decision for the funded hosting discussion, not a configuration "
        f"detail -- set {ALLOW_EXTERNAL_ENV}=1 to override this check."
    )
