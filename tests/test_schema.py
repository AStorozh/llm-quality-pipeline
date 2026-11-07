import unittest

from newlxp import schema

PERSON = {
    "type": "object",
    "required": ["name", "tags"],
    "properties": {
        "name": {"type": "string"},
        "age": {"type": "integer"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "role": {"type": "string", "enum": ["student", "teacher"]},
        "active": {"type": "boolean"},
    },
}


class ValidateTest(unittest.TestCase):
    def test_accepts_a_matching_object(self):
        value = {"name": "Иван", "age": 20, "tags": ["a"], "role": "student",
                 "active": True, "extra": "ignored"}
        self.assertIs(schema.validate(value, PERSON), value)

    def test_missing_required_key(self):
        with self.assertRaises(schema.SchemaError) as caught:
            schema.validate({"name": "Иван"}, PERSON)
        self.assertIn("'tags'", str(caught.exception))

    def test_wrong_type_names_the_path(self):
        with self.assertRaises(schema.SchemaError) as caught:
            schema.validate({"name": 1, "tags": []}, PERSON)
        self.assertIn("$.name", str(caught.exception))

    def test_bad_item_inside_an_array(self):
        with self.assertRaises(schema.SchemaError) as caught:
            schema.validate({"name": "x", "tags": ["a", 2]}, PERSON)
        self.assertIn("$.tags[1]", str(caught.exception))

    def test_enum(self):
        with self.assertRaises(schema.SchemaError):
            schema.validate({"name": "x", "tags": [], "role": "dean"}, PERSON)

    def test_bool_is_not_an_integer(self):
        # Python says isinstance(True, int); a schema must not.
        with self.assertRaises(schema.SchemaError):
            schema.validate({"name": "x", "tags": [], "age": True}, PERSON)
        with self.assertRaises(schema.SchemaError):
            schema.validate({"name": "x", "tags": [], "active": 1}, PERSON)

    def test_coerce_returns_none_instead_of_raising(self):
        self.assertIsNone(schema.coerce({"name": 1}, PERSON))
        ok = {"name": "x", "tags": []}
        self.assertIs(schema.coerce(ok, PERSON), ok)
