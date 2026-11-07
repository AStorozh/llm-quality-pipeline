"""A very small JSON-schema validator.

Only the subset the project actually needs is supported: object shapes with
required keys, arrays with a typed item, primitives and enums. That keeps the
"no runtime dependencies" promise while still refusing malformed model output
instead of letting it through half-checked.
"""
from __future__ import annotations

TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
}


class SchemaError(ValueError):
    """The value does not match the schema. The message says where."""


def validate(value, schema: dict, path: str = "$"):
    """Return ``value`` if it matches ``schema``, else raise SchemaError."""
    expected = schema.get("type")
    if expected:
        python_type = TYPES.get(expected)
        if python_type is None:
            raise SchemaError("%s: unknown type %r in schema" % (path, expected))
        # bool is an int in Python; never let it pass as a number.
        if isinstance(value, bool) != (expected == "boolean"):
            raise SchemaError("%s: expected %s, got %s"
                              % (path, expected, _name(value)))
        if not isinstance(value, python_type):
            raise SchemaError("%s: expected %s, got %s"
                              % (path, expected, _name(value)))

    if "enum" in schema and value not in schema["enum"]:
        raise SchemaError("%s: %r is not one of %s" % (path, value, schema["enum"]))

    if expected == "object":
        for key in schema.get("required", []):
            if key not in value:
                raise SchemaError("%s: missing required key %r" % (path, key))
        properties = schema.get("properties") or {}
        for key, item in value.items():
            if key in properties:
                validate(item, properties[key], "%s.%s" % (path, key))

    if expected == "array" and "items" in schema:
        for index, item in enumerate(value):
            validate(item, schema["items"], "%s[%d]" % (path, index))

    return value


def coerce(value, schema: dict):
    """Validate, returning ``None`` instead of raising.

    Useful where a malformed answer should fall back to another strategy
    rather than abort the run.
    """
    try:
        return validate(value, schema)
    except SchemaError:
        return None


def _name(value) -> str:
    return type(value).__name__
