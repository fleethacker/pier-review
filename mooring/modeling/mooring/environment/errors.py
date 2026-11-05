"""Source-independent environment provider failures."""


class ProviderError(Exception):
    """A classified provider failure that must not trigger synthetic data.

    Kinds currently used by the API boundary are ``invalid_request``,
    ``bad_request``, ``no_data``, ``unavailable``, ``stale``, and
    ``malformed``.
    """

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
