"""Loads versioned prompt template files. See
docs/superpowers/specs/2026-09-21-extraction-verification-design.md §4."""

from pathlib import Path
from typing import Callable

PROMPTS_DIR = Path(__file__).resolve().parent


def load_prompt_template(name: str) -> str:
    """Returns the raw template text for prompts/<name>.txt. `name` excludes
    the .txt extension, e.g. 'extraction_strict_tacit_v1'."""
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")


def load_prompt(name: str) -> Callable[[str], str]:
    """For the single-placeholder extraction prompts: returns a function that
    fills in the passage text via plain string replacement (not str.format,
    since some templates display literal JSON braces to the model)."""
    template = load_prompt_template(name)

    def build_prompt(passage: str) -> str:
        return template.replace("{passage}", passage)

    return build_prompt
