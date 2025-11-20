#!/usr/bin/env python3
"""
Deeper debugging to find why cli.py is not being indexed.
"""

from pathlib import Path
from lsp_repograph.core.multilspy_client import MultilspyLSPClient

repo_path = Path("/home/ubuntu/testing-agent/full_data-success_only-all/repos/grahame_sedge__3badf078e2f4153db161cada1c7a23901e36ab7f")
venv_python = repo_path / ".venv_helper" / "bin" / "python"

print("Checking repo structure and files:\n")

# List Python files in repo
py_files = list(repo_path.glob("**/*.py"))
py_files = [f for f in py_files if ".venv_helper" not in str(f)]
print(f"Python files in repo (excluding .venv_helper):")
for f in sorted(py_files):
    rel_path = f.relative_to(repo_path)
    print(f"  {rel_path}")

print("\n" + "=" * 80)
print("Checking if LSP can find definitions in specific files")
print("=" * 80)

custom_init = {
    "initializationOptions": {
        "workspace": {
            "environmentPath": str(venv_python)
        }
    }
}

client = MultilspyLSPClient(str(repo_path), custom_init_params=custom_init)

# Try to find definitions of specific things we know exist
test_cases = [
    ("sedge.cli", "main", "Function in cli.py"),
    ("sedge.engine", "SedgeEngine", "Class in engine.py"),
    ("sedge", "SedgeEngine", "Class from sedge module"),
]

print("\nSearching for definitions:")
for module, name, desc in test_cases:
    try:
        defs = client.find_def_by_fqn(f"{module}.{name}")
        print(f"  {module}.{name} ({desc}): {len(defs)} defs found")
        if defs:
            print(f"    -> {defs[0].get('absolute_path', 'N/A')}")
    except Exception as e:
        print(f"  {module}.{name}: Error - {e}")

print("\n" + "=" * 80)
print("Checking imports in each Python file")
print("=" * 80)

for f in sorted(py_files):
    rel_path = f.relative_to(repo_path)
    content = f.read_text()

    # Find import lines
    import_lines = [line for line in content.split('\n') if 'import' in line.lower()]

    if import_lines:
        print(f"\n{rel_path}:")
        for line in import_lines[:3]:
            print(f"  {line}")

print("\n" + "=" * 80)
print("Testing find_refs at different paths")
print("=" * 80)

# Try searching for argparse with different context
print("\nSearching for 'argparse' references from different starting points:")

test_paths = [
    repo_path,
    repo_path / "sedge",
    repo_path / "tests",
]

for test_path in test_paths:
    if test_path.exists():
        try:
            # We can't change the client's repo_path, but we can see what it finds
            refs = client.find_refs_by_fqn(module="argparse")
            rel_refs = [
                str(Path(r['absolute_path']).relative_to(repo_path))
                for r in refs
            ]
            print(f"  From {test_path.relative_to(repo_path) or '.'}:")
            for ref in rel_refs:
                print(f"    {ref}")
        except Exception as e:
            print(f"    Error: {e}")

client.shutdown()

print("\n" + "=" * 80)
print("CONCLUSION:")
print("=" * 80)
print("If cli.py is not in the results above, LSP is not indexing it.")
print("This could be because:")
print("1. sedge/cli.py is in .gitignore or excluded from LSP")
print("2. LSP workspace initialization didn't include it")
print("3. There's a syntax error in cli.py that prevents parsing")
print("4. LSP is only scanning certain file patterns")
