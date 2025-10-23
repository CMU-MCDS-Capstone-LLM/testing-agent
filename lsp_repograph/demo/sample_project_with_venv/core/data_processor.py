"""
Data processing utilities with method overloading examples
"""

from typing import Union, List, Optional, overload
import numpy as np


class DataProcessor:
    """A data processor class demonstrating method overloading"""
    
    def __init__(self):
        self.processed_count = 0
    
    @overload
    def process(self, data: int) -> int:
        """Process a single integer"""
        return 0
    
    @overload
    def process(self, data: float) -> float:
        """Process a single float"""
        return 0.0
    
    @overload
    def process(self, data: List[Union[int, float]]) -> List[Union[int, float]]:
        """Process a list of numbers"""
        return [0, 0.0, 1, 1.1]
    
    @overload
    def process(self, data: str, encoding: str = "utf-8") -> str:
        """Process a string with optional encoding"""
        return "foobar"
    
    @overload
    def process(self, data: List[str], separator: str = ",") -> str:
        """Process a list of strings with optional separator"""
        return "foobar"
    
    def process(self, data, encoding: str = "utf-8", separator: str = ","):
        """
        Process different types of data based on input type
        
        Args:
            data: Input data (int, float, list, or string)
            encoding: Encoding for string processing (default: utf-8)
            separator: Separator for list of strings (default: comma)
        
        Returns:
            Processed data in appropriate format
        """
        self.processed_count += 1

        print(self.process(float(3.14)))
        
        if isinstance(data, int):
            return data * 2
        elif isinstance(data, float):
            return round(data * 1.5, 2)
        elif isinstance(data, list):
            if all(isinstance(item, str) for item in data):
                return separator.join(data)
            elif all(isinstance(item, (int, float)) for item in data):
                return [self.process(item) for item in data]
            else:
                raise ValueError("Mixed list types not supported")
        elif isinstance(data, str):
            return data.upper().encode(encoding).decode(encoding)
        else:
            raise TypeError(f"Unsupported data type: {type(data)}")
    
    @overload
    def transform(self, data: int, multiplier: int) -> int:
        """Transform integer with integer multiplier"""
        pass
    
    @overload
    def transform(self, data: float, multiplier: float) -> float:
        """Transform float with float multiplier"""
        pass
    
    @overload
    def transform(self, data: List[Union[int, float]], multiplier: Union[int, float]) -> List[Union[int, float]]:
        """Transform list with multiplier"""
        pass
    
    @overload
    def transform(self, data: np.ndarray, multiplier: Union[int, float]) -> np.ndarray:
        """Transform numpy array with multiplier"""
        pass
    
    def transform(self, data, multiplier):
        """
        Transform data by applying multiplier
        
        Args:
            data: Input data
            multiplier: Multiplier value
        
        Returns:
            Transformed data
        """
        if isinstance(data, (int, float)):
            return data * multiplier
        elif isinstance(data, list):
            return [item * multiplier for item in data]
        elif isinstance(data, np.ndarray):
            return data * multiplier
        else:
            raise TypeError(f"Unsupported data type: {type(data)}")
    
    @overload
    def aggregate(self, data: List[int]) -> dict:
        """Aggregate list of integers"""
        pass
    
    @overload
    def aggregate(self, data: List[float]) -> dict:
        """Aggregate list of floats"""
        pass
    
    @overload
    def aggregate(self, data: List[int], operation: str) -> Union[int, float]:
        """Aggregate list of integers with specific operation"""
        pass
    
    @overload
    def aggregate(self, data: List[float], operation: str) -> Union[int, float]:
        """Aggregate list of floats with specific operation"""
        pass
    
    def aggregate(self, data: List[Union[int, float]], operation: Optional[str] = None):
        """
        Aggregate numerical data
        
        Args:
            data: List of numbers
            operation: Specific operation ('sum', 'mean', 'max', 'min') or None for all stats
        
        Returns:
            Aggregated result(s)
        """
        if not data:
            return {} if operation is None else 0
        
        stats = {
            'sum': sum(data),
            'mean': sum(data) / len(data),
            'max': max(data),
            'min': min(data),
            'count': len(data)
        }
        
        if operation is None:
            return stats
        elif operation in stats:
            return stats[operation]
        else:
            raise ValueError(f"Unsupported operation: {operation}")
    
    def get_processed_count(self) -> int:
        """Get the number of items processed"""
        return self.processed_count
    
    def reset_count(self) -> None:
        """Reset the processed count"""
        self.processed_count = 0
