from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

_TEMPLATES = Path(__file__).resolve().parents[2] / "coaching" / "templates"

_ENV: Environment | None = None


def template_dir() -> Path:
    """Return the H.7 Jinja fallback directory. Assumes package data is installed."""
    return _TEMPLATES


def render_rule_template(rule_id: str, bindings: Mapping[str, Any]) -> str:
    """Return rendered ``{rule_id}.j2`` prose. Assumes the template exists."""
    env = _environment()
    text = env.get_template(f"{rule_id}.j2").render(**dict(bindings))
    return text.strip() + "\n"


def render_string(template: str, bindings: Mapping[str, Any]) -> str:
    """Return a YAML explanation/alternative string rendered as Jinja."""
    env = _environment()
    return env.from_string(template).render(**dict(bindings)).strip()


def _environment() -> Environment:
    global _ENV
    if _ENV is None:
        _ENV = Environment(
            loader=FileSystemLoader(str(_TEMPLATES)),
            undefined=StrictUndefined,
            autoescape=select_autoescape(default=False),
            trim_blocks=True,
            lstrip_blocks=True,
        )
    return _ENV
