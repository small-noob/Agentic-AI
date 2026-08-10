import unittest

from registry import ToolError, ToolRegistry


def build() -> ToolRegistry:
    registry = ToolRegistry()

    @registry.tool("Echo a message.", message="What to echo.", times="How many copies.")
    def echo(message: str, times: int = 1) -> str:
        return " ".join([message] * times)

    return registry


class RegistryTests(unittest.TestCase):
    def test_schema_is_built_from_the_signature(self):
        spec = build().tools["echo"]
        self.assertEqual(spec.parameters["required"], ["message"])
        self.assertEqual(spec.parameters["properties"]["times"]["type"], "integer")
        self.assertEqual(spec.parameters["properties"]["message"]["description"], "What to echo.")

    def test_catalogue_marks_optional_arguments(self):
        self.assertIn("times: integer (optional)", build().describe())

    def test_type_hints_are_mandatory(self):
        registry = ToolRegistry()
        with self.assertRaises(TypeError):
            registry.tool("no hints")(lambda value: value)

    def test_unknown_tool_returns_an_observation_not_an_exception(self):
        registry = build()
        self.assertIn("Unknown tool", registry.call("nope", {}))
        self.assertFalse(registry.history[-1]["ok"])

    def test_missing_and_unknown_arguments_are_reported(self):
        registry = build()
        self.assertIn("Missing required argument", registry.call("echo", {}))
        self.assertIn("Unknown argument", registry.call("echo", {"message": "hi", "colour": "red"}))

    def test_string_digits_are_coerced_to_integers(self):
        self.assertEqual(build().call("echo", {"message": "hi", "times": "3"}), "hi hi hi")

    def test_tool_exceptions_become_observations(self):
        registry = ToolRegistry()

        @registry.tool("Always fails.")
        def boom() -> str:
            raise ToolError("nope")

        self.assertEqual(registry.call("boom", {}), "Tool error: nope")
        self.assertFalse(registry.called("boom"))

    def test_long_output_is_truncated(self):
        registry = ToolRegistry()
        registry.max_output_chars = 50

        @registry.tool("Returns a wall of text.")
        def flood() -> str:
            return "x" * 500

        self.assertIn("truncated", registry.call("flood", {}))


if __name__ == "__main__":
    unittest.main()
