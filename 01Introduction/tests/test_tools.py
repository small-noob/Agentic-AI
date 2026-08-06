import unittest

from tools import ToolEnvironment, _safe_calculate


class ToolTests(unittest.TestCase):
    def test_calculates_modular_power_seed(self):
        self.assertEqual(_safe_calculate("pow(20250807,123457,1000000)"), 730807)

    def test_normalizes_weak_model_caret_notation(self):
        env = ToolEnvironment()
        self.assertEqual(
            env.calculate("20250807^123457 % 1000000"),
            "730807",
        )

    def test_calculates_odd_branch(self):
        env = ToolEnvironment()
        self.assertEqual(
            env.calculate("(730807 * 2025 + 271828) % 1000000"),
            "156003",
        )

    def test_calculator_rejects_code_execution(self):
        with self.assertRaises(ValueError):
            _safe_calculate("__import__('os').system('echo unsafe')")

    def test_large_plain_power_requires_modular_pow(self):
        with self.assertRaises(ValueError):
            _safe_calculate("20250807 ** 123457")


if __name__ == "__main__":
    unittest.main()
