#!/usr/bin/env python3
"""
Debug script to diagnose repograph issues.
Tests each step of the repograph pipeline to find where it fails.
"""

import json
import sys
import tempfile
from pathlib import Path

import yaml

def test_lsp_client():
    """Test if MultilspyLSPClient can be imported and initialized"""
    print("=" * 80)
    print("TEST 1: MultilspyLSPClient import and initialization")
    print("=" * 80)

    try:
        from lsp_repograph.core.multilspy_client import MultilspyLSPClient
        print("✓ MultilspyLSPClient imported successfully")
    except ImportError as e:
        print(f"❌ Failed to import MultilspyLSPClient: {e}")
        return False

    repo_path = Path("/home/ubuntu/testing-agent/full_data-success_only-all/repos/grahame_sedge__3badf078e2f4153db161cada1c7a23901e36ab7f")
    venv_python = repo_path / ".venv_helper" / "bin" / "python"

    if not venv_python.exists():
        print(f"❌ Venv python not found: {venv_python}")
        return False

    print(f"✓ Venv python found: {venv_python}")

    custom_init = {
        "initializationOptions": {
            "workspace": {
                "environmentPath": str(venv_python)
            }
        }
    }

    try:
        client = MultilspyLSPClient(str(repo_path), custom_init_params=custom_init)
        print("✓ MultilspyLSPClient initialized")
        return True, client
    except Exception as e:
        print(f"❌ Failed to initialize MultilspyLSPClient: {e}")
        return False, None


def test_find_refs(client):
    """Test find_refs_by_fqn for different modules"""
    print("\n" + "=" * 80)
    print("TEST 2: find_refs_by_fqn for different modules")
    print("=" * 80)

    test_modules = [
        ("argparse", "Standard library"),
        ("requests", "Third-party"),
        ("sedge", "Local package"),
    ]

    results = {}
    for module, desc in test_modules:
        try:
            print(f"\nTesting: {module} ({desc})")
            refs = client.find_refs_by_fqn(module=module)
            count = len(refs)
            print(f"  Found {count} references")
            if count > 0:
                print(f"  Sample ref: {refs[0]}")
            results[module] = count
        except Exception as e:
            print(f"  ❌ Error: {e}")
            results[module] = -1

    return results


def test_with_different_configs():
    """Test find_refs with different custom_init configurations"""
    print("\n" + "=" * 80)
    print("TEST 3: Different custom_init configurations")
    print("=" * 80)

    from lsp_repograph.core.multilspy_client import MultilspyLSPClient

    repo_path = Path("/home/ubuntu/testing-agent/full_data-success_only-all/repos/grahame_sedge__3badf078e2f4153db161cada1c7a23901e36ab7f")
    venv_python = repo_path / ".venv_helper" / "bin" / "python"

    configs = [
        ("No custom_init", None),
        ("With venv environmentPath", {
            "initializationOptions": {
                "workspace": {
                    "environmentPath": str(venv_python)
                }
            }
        }),
        ("With pythonPath", {
            "initializationOptions": {
                "workspace": {
                    "pythonPath": str(venv_python)
                }
            }
        }),
    ]

    for name, config in configs:
        try:
            print(f"\nTesting: {name}")
            client = MultilspyLSPClient(str(repo_path), custom_init_params=config)
            refs = client.find_refs_by_fqn(module="argparse")
            print(f"  ✓ Found {len(refs)} references to argparse")
            client.shutdown()
        except Exception as e:
            print(f"  ❌ Error: {e}")


def test_repo_indexing():
    """Test if LSP is actually indexing the repo files"""
    print("\n" + "=" * 80)
    print("TEST 4: Check if LSP is indexing repo files")
    print("=" * 80)

    from lsp_repograph.core.multilspy_client import MultilspyLSPClient

    repo_path = Path("/home/ubuntu/testing-agent/full_data-success_only-all/repos/grahame_sedge__3badf078e2f4153db161cada1c7a23901e36ab7f")
    venv_python = repo_path / ".venv_helper" / "bin" / "python"

    custom_init = {
        "initializationOptions": {
            "workspace": {
                "environmentPath": str(venv_python)
            }
        }
    }

    client = MultilspyLSPClient(str(repo_path), custom_init_params=custom_init)

    # Check for methods to get indexed files
    print(f"Available methods in client: {[m for m in dir(client) if not m.startswith('_')]}")

    # Try to find refs for things we know exist
    print("\nSearching for known imports:")
    known_imports = {
        "argparse": "in sedge/cli.py line 1",
        "requests": "in sedge/engine.py",
    }

    for module, location in known_imports.items():
        refs = client.find_refs_by_fqn(module=module)
        print(f"  {module} ({location}): {len(refs)} refs found")

    client.shutdown()


def main():
    print("REPOGRAPH DEBUGGING SCRIPT")
    print("=" * 80)

    # Test 1: LSP Client
    result = test_lsp_client()
    if not result or not result[0]:
        print("\n❌ Cannot continue - LSP client initialization failed")
        return 1

    client = result[1]

    # Test 2: find_refs with different modules
    test_find_refs(client)
    client.shutdown()

    # Test 3: Different configurations
    try:
        test_with_different_configs()
    except Exception as e:
        print(f"Error in test 3: {e}")

    # Test 4: Repo indexing
    try:
        test_repo_indexing()
    except Exception as e:
        print(f"Error in test 4: {e}")

    print("\n" + "=" * 80)
    print("DEBUGGING COMPLETE")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    sys.exit(main())
