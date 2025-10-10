import os
import sys
import toml
from pathlib import Path
from typing import Dict, Any, List
from pprint import pprint

# Add parent directory to path to import lsp_repograph
sys.path.insert(0, str(Path(__file__).parent.parent))

from lsp_repograph.core.multilspy_client import MultilspyLSPClient
from lsp_repograph.repl.commands import (
    Command,
    FindDefByFqnCommand,
    FindRefsByFqnCommand,
    FindDefByLocCommand,
    FindRefsByLocCommand,
)


class REPLClient:
    """Demo client that manages MultilspyLSPClient and available commands"""
    
    def __init__(self, repo_path: str, init_params: Dict[str, Any]):
        """Initialize DemoClient with repo path and LSP initialization parameters"""
        self.repo_path = repo_path
        self.init_params = init_params
        
        # Validate repo path
        if not os.path.exists(repo_path):
            raise ValueError(f"Repository path does not exist: {repo_path}")
        
        # Initialize LSP client
        print(f"Initializing JediLSPClient for repo: {repo_path}")
        print("Using initialization parameters:")
        pprint(init_params)
        
        try:
            self.client = MultilspyLSPClient(repo_path, init_params)
            # Store repo_path in client for position commands
            self.client.repo_path = Path(repo_path).resolve()
            print("Client initialized successfully!")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize client: {e}")
        
        # Initialize available commands
        self.commands: List[Command] = [
            FindDefByFqnCommand(),
            FindRefsByFqnCommand(),
            FindDefByLocCommand(),
            FindRefsByLocCommand(),
        ]
        
        # Create command lookup map
        self.command_map = {cmd.name: cmd for cmd in self.commands}
    
    @classmethod
    def from_config_file(cls, config_path: str) -> 'REPLClient':
        """Initialize from TOML config file"""
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Config file not found: {config_path}")
        
        try:
            config_dict = toml.load(config_path)
        except Exception as e:
            raise ValueError(f"Failed to parse TOML config: {e}")
        
        return cls.from_config_dict(config_dict)
    
    @classmethod
    def from_config_dict(cls, config_dict: Dict[str, Any]) -> 'REPLClient':
        """Initialize from config dictionary"""
        # Extract repo path
        repo_config = config_dict.get('repo', {})
        repo_path = repo_config.get('path')
        
        if not repo_path:
            raise ValueError("Missing required config field: repo.path")
        
        # Extract LSP initialization parameters
        init_params = config_dict.get('lsp', {})
        
        return cls(repo_path, init_params)
    
    def print_help(self):
        """Print available commands"""
        print("\n=== MultilspyLSPClient Demo REPL ===")
        print("Commands:")
        
        for cmd in self.commands:
            print(f"  {cmd.usage:<30} - {cmd.description}")
        
        print("  help                          - Show this help")
        print("  quit / exit                   - Exit REPL")
        print("\nNotes:")
        print("  • File paths are relative to the repo root")
        print("  • Line and character inputs are 0-indexed (LSP style)")
        print("  • FQN format: <module>:<qualpath>, e.g. pathlib:Path.read_text")

        # print("Examples:")
        # for cmd in self.commands:
        #     print(f"  {cmd.example}")
    
    def execute_command(self, command_line: str):
        """Execute a command from the command line input"""
        parts = command_line.strip().split()
        
        if not parts:
            return
        
        cmd_name = parts[0].lower()
        args = parts[1:]
        
        if cmd_name in ['help']:
            self.print_help()
            return
        
        if cmd_name in self.command_map:
            command = self.command_map[cmd_name]
            command.execute(self.client, args)
        else:
            print(f"Unknown command: {cmd_name}")
            print("Type 'help' for available commands")
    
    def run_repl(self):
        """Run the interactive REPL"""
        self.print_help()
        
        while True:
            try:
                command = input("\n>>> ").strip()
                
                if not command:
                    continue
                    
                if command in ['quit', 'exit']:
                    break
                
                self.execute_command(command)
                    
            except KeyboardInterrupt:
                print("\nExiting...")
                break
            except EOFError:
                print("\nExiting...")
                break
            except Exception as e:
                print(f"Error: {e}")
        
        print("Shutting down client...")
        self.client.shutdown()
        print("Goodbye!")
    
    def shutdown(self):
        """Shutdown the LSP client"""
        if hasattr(self, 'client'):
            self.client.shutdown()
