"""Independent worked examples for the neutral synchronous model."""
import unittest
from model import ReferenceModel


class WorkedExamples(unittest.TestCase):
    def test_reset_hold_saturation_and_clear(self):
        model = ReferenceModel()
        vectors = [
            ({"rst_n": 0, "clear": 0, "enable": 1, "amount": 7}, 0),
            ({"rst_n": 1, "clear": 0, "enable": 1, "amount": 5}, 5),
            ({"rst_n": 1, "clear": 0, "enable": 0, "amount": 7}, 5),
            ({"rst_n": 1, "clear": 0, "enable": 1, "amount": 4}, 7),
            ({"rst_n": 1, "clear": 1, "enable": 1, "amount": 7}, 0),
            ({"rst_n": 0, "clear": 0, "enable": 1, "amount": 7}, 0),
        ]
        for inputs, expected in vectors:
            with self.subTest(inputs=inputs, expected=expected):
                self.assertEqual(model.step(inputs), {"q": expected})


if __name__ == '__main__':
    unittest.main()
