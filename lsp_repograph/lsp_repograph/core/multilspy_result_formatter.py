"""
Result formatter for multilspy responses
Converts multilspy responses into consistent format for AI agents
"""

from pathlib import Path
from typing import List, Dict, Any, Optional
import urllib.parse
import os


class MultilspyResultFormatter:
    """Format multilspy responses for consistent output"""
    
    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path)
    
    def format_workspace_symbol(self, symbols: List[Dict[str, Any]], result_type: str) -> List[Dict[str, Any]]:
        """
        Format multilspy workspace symbol results
        
        Args:
            symbols: List of multilspy workspace symbol results
            
        Returns:
            List of formatted symbol information
        """
        # formatted = []
        
        # for symbol in symbols:
        #     try:
        #         formatted_symbol = self._format_single_workspace_symbol(symbol)
        #         if formatted_symbol:
        #             formatted.append(formatted_symbol)
        #     except Exception as e:
        #         print(f"Error formatting workspace symbol: {e}")
        #         continue
                
        # return formatted
        return symbols
    
    def format_definitions(self, definitions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Format multilspy definition results
        
        Args:
            definitions: List of multilspy definition results
            
        Returns:
            List of formatted definition results
        """
        formatted = []
        
        for definition in definitions:
            try:
                formatted_def = self._format_location_result(definition, 'definition')
                if formatted_def:
                    formatted.append(formatted_def)
            except Exception as e:
                print(f"Error formatting definition: {e}")
                continue
                
        return formatted
    
    def format_references(self, references: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Format multilspy reference results
        
        Args:
            references: List of multilspy reference results
            
        Returns:
            List of formatted reference results
        """
        formatted = []
        
        for reference in references:
            try:
                formatted_ref = self._format_location_result(reference, 'reference')
                if formatted_ref:
                    formatted.append(formatted_ref)
            except Exception as e:
                print(f"Error formatting reference: {e}")
                continue
                
        return formatted
    
    def _format_single_workspace_symbol(self, symbol: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Format a single workspace symbol from multilspy
        
        Expected multilspy format:
        {
            'containerName': 'core.math_utils.AdvancedCalculator',
            'kind': 5,
            'location': {
                'range': {'end': {'character': 24, 'line': 38}, 'start': {'character': 6, 'line': 38}},
                'uri': 'file:///path/to/file.py'
            },
            'name': 'AdvancedCalculator'
        }
        """
        try:
            location = symbol['location']
            uri = location['uri']
            range_info = location['range']
            
            file_path = self._uri_to_path(uri)
            line_num = range_info['start']['line']
            
            # Get context around the symbol
            context = self._get_file_context(file_path, line_num, 2)
            
            return {
                'file': str(file_path.relative_to(self.repo_path)),
                'line': line_num + 1,  # Convert to 1-indexed for display
                'column': range_info['start']['character'],
                'context': context,
                'type': 'workspace_symbol',
                'symbol_kind': self._format_symbol_kind(symbol.get('kind', 1)),
                'name': symbol.get('name', ''),
                'container_name': symbol.get('containerName', '')
            }
            
        except Exception as e:
            print(f"Error formatting workspace symbol: {e}")
            return None
    
    def _format_location_result(self, location_result: Dict[str, Any], result_type: str) -> Optional[Dict[str, Any]]:
        """
        Format multilspy location result (definition/reference)
        
        Expected multilspy format:
        {
            'absolutePath': '/absolute/path/to/file.py',
            'range': {'end': {'character': 24, 'line': 38}, 'start': {'character': 6, 'line': 38}},
            'relativePath': 'relative/path/to/file.py',
            'uri': 'file:///absolute/path/to/file.py'
        }
        """
        try:
            # multilspy provides both absolute and relative paths
            if 'absolutePath' in location_result:
                file_path = Path(location_result['absolutePath'])
            elif 'uri' in location_result:
                file_path = self._uri_to_path(location_result['uri'])
            else:
                return None
            
            range_info = location_result['range']
            line_num = range_info['start']['line']
            
            # Get context based on result type
            if result_type == 'definition':
                context = self._get_file_context(file_path, line_num, 3)
            else:
                context = self._get_single_line_context(file_path, line_num)
            
            return {
                'file': str(file_path.relative_to(self.repo_path)),
                'line': line_num + 1,  # Convert to 1-indexed for display
                'column': range_info['start']['character'],
                'context': context,
                'type': result_type
            }
            
        except Exception as e:
            print(f"Error formatting location result: {e}")
            return None
    
    def _uri_to_path(self, uri: str) -> Path:
        """
        Convert file URI to Path object
        Handles platform-specific considerations for Windows
        """
        parsed_uri = urllib.parse.urlparse(uri)
        if parsed_uri.scheme != 'file':
            raise ValueError("Provided URI is not a 'file' scheme URI.")

        path = urllib.parse.unquote(parsed_uri.path)

        # Handle Windows-specific paths starting with an extra slash
        if os.name == 'nt' and path.startswith('/'):
            # On Windows, `file:///C:/path` becomes `/C:/path` after unquoting.
            # We need to remove the leading slash for a valid Windows path.
            path = path[1:]
            # Also, convert forward slashes to backslashes for Windows
            path = path.replace('/', '\\')

        return Path(path)
    
    def _format_symbol_kind(self, kind: int) -> str:
        """Convert LSP symbol kind number to string"""
        # LSP SymbolKind enumeration
        kinds = {
            1: "File", 2: "Module", 3: "Namespace", 4: "Package", 5: "Class",
            6: "Method", 7: "Property", 8: "Field", 9: "Constructor", 10: "Enum",
            11: "Interface", 12: "Function", 13: "Variable", 14: "Constant",
            15: "String", 16: "Number", 17: "Boolean", 18: "Array", 19: "Object",
            20: "Key", 21: "Null", 22: "EnumMember", 23: "Struct", 24: "Event",
            25: "Operator", 26: "TypeParameter"
        }
        return kinds.get(kind, "Unknown")
    
    def _get_file_context(self, file_path: Path, center_line: int, context_lines: int) -> str:
        """
        Get multiple lines of context around target line
        
        Args:
            file_path: Path to file
            center_line: 0-indexed line number to center on
            context_lines: Number of lines before and after to include
            
        Returns:
            Context string with multiple lines
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            start = max(0, center_line - context_lines)
            end = min(len(lines), center_line + context_lines + 1)
            
            context = ''.join(lines[start:end]).rstrip()
            return context
            
        except Exception as e:
            print(f"Error reading context from {file_path}: {e}")
            return ""
    
    def _get_single_line_context(self, file_path: Path, line_num: int) -> str:
        """
        Get single line context
        
        Args:
            file_path: Path to file
            line_num: 0-indexed line number
            
        Returns:
            Single line of code as string
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            if 0 <= line_num < len(lines):
                return lines[line_num].strip()
            return ""
            
        except Exception as e:
            print(f"Error reading line from {file_path}: {e}")
            return ""