"""QQ bot stack component."""











import re
from typing import Optional


_LOCALHOST_RE = re.compile(r"//localhost(?=[:/]|$)")


def normalize_localhost(url: Optional[str]) -> Optional[str]:
    """QQ bot stack component."""
    if url and isinstance(url, str):
        return _LOCALHOST_RE.sub("//127.0.0.1", url)
    return url
