"""Domain errors. The factory maps each to one HTTP status; raise these, not HTTPException."""


class ConflictError(Exception):
    """409: the thing already exists or changed underneath you."""


class NotFound(Exception):
    """404: no such thing."""


class ProviderNotConfigured(Exception):
    """503: a provider this call needs has no credentials. Never fake a success instead."""


class CaseCancelled(Exception):
    """The case was given up on (timed out or out of budget): no further tool call or write."""
