"""Safe JSON document loading and source fingerprinting."""

import hashlib
import json
from pathlib import Path


class DocumentLoadError(ValueError):
    """A safe, structured input-loading error."""

    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self):
        return {
            "code": self.code,
            "message": self.message,
            **self.details,
        }


class _DuplicateKeyError(ValueError):
    def __init__(self, key):
        self.key = key
        super().__init__(f"Duplicate JSON key: {key!r}")


class _NonStandardNumberError(ValueError):
    def __init__(self, token):
        self.token = token
        super().__init__(f"Non-standard JSON number: {token}")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(key)
        result[key] = value
    return result


def _reject_nonstandard_number(token):
    raise _NonStandardNumberError(token)


def load_json_document(path, role):
    """Return (document, source metadata) or raise DocumentLoadError."""
    path = Path(path)
    context = {
        "document_role": role,
        "file_name": path.name,
    }

    try:
        raw = path.read_bytes()
    except OSError as error:
        raise DocumentLoadError(
            "FILE_READ_ERROR",
            f"Could not read {path.name}: {error.strerror or 'file access failed'}",
            context,
        ) from None

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise DocumentLoadError(
            "INVALID_ENCODING",
            "The file must contain valid UTF-8 JSON.",
            context,
        ) from None

    try:
        document = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonstandard_number,
        )
    except json.JSONDecodeError as error:
        raise DocumentLoadError(
            "INVALID_JSON",
            f"Invalid JSON at line {error.lineno}, column {error.colno}: "
            f"{error.msg}",
            {**context, "line": error.lineno, "column": error.colno},
        ) from None
    except _DuplicateKeyError as error:
        raise DocumentLoadError(
            "DUPLICATE_JSON_KEY",
            str(error),
            {**context, "key": error.key},
        ) from None
    except _NonStandardNumberError as error:
        raise DocumentLoadError(
            "NON_STANDARD_NUMBER",
            str(error),
            {**context, "token": error.token},
        ) from None

    if not isinstance(document, dict):
        raise DocumentLoadError(
            "INVALID_ROOT_TYPE",
            "The document's top-level JSON value must be an object.",
            context,
        )

    source = {
        **context,
        "format": "json",
        "byte_size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    return document, source
