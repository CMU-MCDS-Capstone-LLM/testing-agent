"""
File utilities for creating test projects and managing files
"""

from pathlib import Path
import urllib
import os
def create_sample_project(base_path: str = None) -> str:
    """
    Create sample Python project for testing LSP functionality
    
    Args:
        base_path: Base directory to create sample project in
        
    Returns:
        Path to created sample project directory
    """
    if base_path is None:
        base_path = Path(__file__).parent.parent.parent / "examples"
    
    sample_dir = Path(base_path) / "sample_project"
    sample_dir.mkdir(parents=True, exist_ok=True)
    
    # Create __init__.py
    (sample_dir / "__init__.py").write_text("")
    
    # Sample math utilities module
    math_utils_content = '''"""
Math utilities for demonstration
"""

def calculate_sum(a, b):
    """Calculate the sum of two numbers"""
    return a + b

def calculate_product(a, b):
    """Calculate the product of two numbers"""
    return a * b

class Calculator:
    """A simple calculator class"""
    
    def __init__(self):
        self.history = []
    
    def add(self, x, y):
        """Add two numbers"""
        result = calculate_sum(x, y)
        self.history.append(f"{x} + {y} = {result}")
        return result
    
    def multiply(self, x, y):
        """Multiply two numbers"""
        result = calculate_product(x, y)
        self.history.append(f"{x} * {y} = {result}")
        return result
    
    def get_history(self):
        """Get calculation history"""
        return self.history
    
    def clear_history(self):
        """Clear calculation history"""
        self.history = []

class AdvancedCalculator(Calculator):
    """Advanced calculator with more operations"""
    
    def power(self, base, exponent):
        """Calculate power"""
        result = base ** exponent
        self.history.append(f"{base} ^ {exponent} = {result}")
        return result
    
    def sqrt(self, number):
        """Calculate square root"""
        import math
        result = math.sqrt(number)
        self.history.append(f"sqrt({number}) = {result}")
        return result
'''
    
    # Sample main application
    main_content = '''"""
Main application demonstrating calculator usage
"""

from sample_project.math_utils import Calculator, AdvancedCalculator, calculate_sum

def main():
    """Main application function"""
    # Test basic calculator
    calc = Calculator()
    result1 = calc.add(5, 3)
    result2 = calc.multiply(4, 7)
    
    print(f"Calculator results: {result1}, {result2}")
    print("Basic calculator history:", calc.get_history())
    
    # Test advanced calculator
    advanced_calc = AdvancedCalculator()
    result3 = advanced_calc.power(2, 8)
    result4 = advanced_calc.sqrt(16)
    
    print(f"Advanced calculator results: {result3}, {result4}")
    print("Advanced calculator history:", advanced_calc.get_history())
    
    # Test standalone function
    result5 = calculate_sum(10, 20)
    print(f"Direct calculation: {result5}")

def helper_function():
    """Helper function that uses Calculator"""
    calc = Calculator()
    calc.add(1, 2)
    return calc

class DataProcessor:
    """Class that uses calculator for processing"""
    
    def __init__(self):
        self.calculator = Calculator()
    
    def process_numbers(self, numbers):
        """Process a list of numbers"""
        total = 0
        for i, num in enumerate(numbers):
            if i == 0:
                total = num
            else:
                total = self.calculator.add(total, num)
        return total

if __name__ == "__main__":
    main()
'''
    
    # Sample tests
    test_content = '''"""
Tests for calculator functionality
"""

import unittest
from sample_project.math_utils import Calculator, calculate_sum, calculate_product

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
'''
    
    # Write files
    (sample_dir / "math_utils.py").write_text(math_utils_content)
    (sample_dir / "main.py").write_text(main_content)
    (sample_dir / "test_calculator.py").write_text(test_content)
    
    return str(sample_dir)