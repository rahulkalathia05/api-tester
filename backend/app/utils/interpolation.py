"""
Variable interpolation for API requests.

Replaces {{env.KEY}} placeholders in URLs, headers, and body with values
from the active environment before the request is executed.

Examples:
    {{env.BASE_URL}}      → https://api.example.com
    {{env.AUTH_TOKEN}}    → secret123
"""
import re

_PATTERN = re.compile(r"\{\{env\.([A-Za-z_][A-Za-z0-9_]*)\}\}")


def interpolate(template: str, variables: dict[str, str]) -> str:
    """Replace all {{env.KEY}} occurrences using the given variable map."""
    def replace(match: re.Match) -> str:
        key = match.group(1)
        return variables.get(key, match.group(0))   # leave unresolved if missing

    return _PATTERN.sub(replace, template)


def interpolate_dict(d: dict[str, str], variables: dict[str, str]) -> dict[str, str]:
    return {k: interpolate(v, variables) for k, v in d.items()}
