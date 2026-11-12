"""Quote grounding: a claim that quotes a source must quote it word for word."""


def check_quote(quote: str, source: str) -> bool:
    """True when quote appears verbatim in source; only differences in whitespace are ignored."""
    words = " ".join(quote.split())
    return bool(words) and words in " ".join(source.split())
