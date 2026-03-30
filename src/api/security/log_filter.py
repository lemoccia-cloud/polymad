"""
Logging filter that redacts sensitive data before it reaches any log sink.

Patterns redacted:
  - Full Ethereum addresses (0x + 40 hex chars)
  - JWT tokens (three base64url segments)
  - Long opaque tokens / secrets (40+ base64url chars)

Apply this filter to ALL loggers at application startup.
"""
import logging
import re

_SENSITIVE_PATTERNS: list[re.Pattern] = [
    # Full Ethereum addresses — keep first 6 chars prefix in logs via addr_prefix= pattern instead
    re.compile(r"0x[0-9a-fA-F]{38,}"),
    # JWT tokens (three base64url-encoded segments separated by dots)
    re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),
    # Long opaque tokens (API keys, secrets, nonces ≥ 40 chars of base64url)
    re.compile(r"[A-Za-z0-9_\-]{40,}"),
]

_REDACTED = "[REDACTED]"


class SensitiveDataFilter(logging.Filter):
    """
    Logging filter that scans formatted log messages and replaces any
    sensitive patterns with [REDACTED].

    Usage:
        import logging
        from src.api.security.log_filter import SensitiveDataFilter

        _filter = SensitiveDataFilter()
        for handler in logging.root.handlers:
            handler.addFilter(_filter)
        logging.root.addFilter(_filter)
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True

        redacted = msg
        for pattern in _SENSITIVE_PATTERNS:
            redacted = pattern.sub(_REDACTED, redacted)

        if redacted != msg:
            record.msg = redacted
            record.args = ()

        return True


def install_sensitive_filter() -> None:
    """
    Install SensitiveDataFilter on the root logger and all existing handlers.
    Call once at application startup before any request is processed.
    """
    log_filter = SensitiveDataFilter()
    root = logging.getLogger()
    root.addFilter(log_filter)
    for handler in root.handlers:
        handler.addFilter(log_filter)
