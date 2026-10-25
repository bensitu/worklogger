"""Content limits shared by record editing and timer recovery."""

MAX_ENTRY_CONTENT_LENGTH = 16_000


def require_entry_content(content: str) -> str:
    """Accept optional record text within the supported character limit."""
    if not isinstance(content, str) or len(content) > MAX_ENTRY_CONTENT_LENGTH:
        raise ValueError("time_entry_content_too_long")
    return content
