import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import unittest
from app import parse_experience_years

class TestParseExperienceYears(unittest.TestCase):
    def test_parse_experience_years(self):
        cases = [
            ("5 years", 5.0),
            ("5.5 years", 5.5),
            ("5 years 6 months", 5.5),
            ("12.5 yrs", 12.5),
            ("8+ years", 8.0),
            ("Over 10 years", 10.0),
            ("6 months", 0.5),
            ("", None),
            ("N/A", None),
            ("not mentioned", None),
            ("24.0 years", 24.0),
            ("7", 7.0),
            (None, None)
        ]
        for input_text, expected in cases:
            with self.subTest(input_text=input_text):
                result = parse_experience_years(input_text)
                self.assertEqual(result, expected, f"Failed for input '{input_text}': got {result}, expected {expected}")

if __name__ == '__main__':
    unittest.main()
