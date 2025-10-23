#!/usr/bin/env python3
"""
Modular Demo REPL for JediLSPClient using multilspy
Provides interactive access to the three core APIs with a clean command structure
"""

import os
from lsp_repograph.repl.repl_client import REPLClient


def main():
    """Main entry point for the demo"""
    # Use the sample config file
    config_path = os.path.join(os.path.dirname(__file__), "config", "sample_project_with_venv.toml")
    
    if not os.path.exists(config_path):
        print(f"Error: Config file not found at {config_path}")
        return
    
    try:
        # Initialize demo client from config file
        demo = REPLClient.from_config_file(config_path)
        
        # Run the interactive REPL
        demo.run_repl()
        
    except Exception as e:
        print(f"Error initializing demo: {e}")
        return


if __name__ == "__main__":
    main()
