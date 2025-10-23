"""
Tests for calculator functionality
"""

import unittest
from core.math_utils import Calculator, calculate_sum, calculate_product

class TestCalculator(unittest.TestCase):
    """Test cases for Calculator class"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.calc = Calculator()
    
    def test_add(self):
        """Test addition functionality"""
        result = self.calc.add(2, 3)
        self.assertEqual(result, 5)
        self.assertIn("2 + 3 = 5", self.calc.get_history())
    
    def test_multiply(self):
        """Test multiplication functionality"""  
        result = self.calc.multiply(4, 5)
        self.assertEqual(result, 20)
    
    def test_history(self):
        """Test history tracking"""
        self.calc.add(1, 1)
        self.calc.multiply(2, 3)
        history = self.calc.get_history()
        self.assertEqual(len(history), 2)
        
        self.calc.clear_history()
        self.assertEqual(len(self.calc.get_history()), 0)

class TestStandaloneFunctions(unittest.TestCase):
    """Test cases for standalone functions"""
    
    def test_calculate_sum(self):
        """Test calculate_sum function"""
        result = calculate_sum(10, 15)
        self.assertEqual(result, 25)
    
    def test_calculate_product(self):
        """Test calculate_product function"""
        result = calculate_product(6, 7)
        self.assertEqual(result, 42)

if __name__ == "__main__":
    unittest.main()
