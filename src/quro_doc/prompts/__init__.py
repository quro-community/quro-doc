from __future__ import annotations
from pathlib import Path
from jinja2 import Environment, FileSystemLoader


_PROMPT_DIR = Path(__file__).parent


def _init_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_PROMPT_DIR)),
        autoescape=False,
    )


_ENV = _init_env()


def render(template_name: str, **kwargs) -> str:
    template = _ENV.get_template(template_name)
    return template.render(**kwargs)
