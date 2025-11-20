#!/usr/bin/env python3
"""Run repograph on 12 specified repos and update their repograph_result.json"""

import json
import sys
from pathlib import Path
from lsp_repograph.core.multilspy_client import MultilspyLSPClient
import yaml

# 12 repos to process
REPOS = [
    "aiortc_aiortc__270edaf4237cba1942fc0b8cc98f3ae4dfc3f0e1",
    "aiortc_aiortc__d30c24009196f6f520010f7cca1d24e7506163be",
    "alice-biometrics_petisco__9abf7b1f6ef8c55bdddcb9a5c2eff513f6a93130",
    "amesar_mlflow-tools__431737a891b13a73ec7bdbc507fad21531f2cbf3",
    "apryor6_flaskerize__59d8319355bf95f26949fe13ac3d6be5b5282fb6",
    "bcgov_theorgbook__728f86e941dfb6bdbee27628d28425757af5f22d",
    "bretttolbert_verbecc-svc__24a848d285ae2c6f3e5b06d1a8ee718cb3f17133",
    "cyberbotics_urdf2webots__723168dbfff6132aa5591837d43c960679a0a2c4",
    "czheo_syntax_sugar_python__1dbc1d44855acd57f280cca03878681e8dc26b01",
    "deepspace2_styleframe__ffc8d7615fb37996ad7824a0e0501351a8f66b14",
    "emlid_ntripbrowser__9161c1943a8623892b174c98cdf686a4a0ce8673",
    "godaddy_tartufo__553dc5fb7ddef597cafda451954fa4cba23acde6",
]

BASE_PATH = Path("/home/ubuntu/testing-agent/full_data-success_only-all")
REPOS_DIR = BASE_PATH / "repos"
YAMLS_DIR = BASE_PATH / "repo-yamls"
NAME_MAP_PATH = Path("/home/ubuntu/testing-agent/name_map.json")

def load_name_map():
    """Load the name_map.json that maps repo names to yaml file names"""
    with open(NAME_MAP_PATH) as f:
        return json.load(f)

def get_yaml_for_repo(repo_name, name_map):
    """Get yaml file path for a repo using name_map"""
    yaml_name = name_map.get(repo_name)
    if yaml_name:
        return YAMLS_DIR / f"{yaml_name}.yaml"
    return None

def load_yaml(path):
    """Load YAML file"""
    with open(path) as f:
        return yaml.safe_load(f)

def convert_package_to_module(name):
    """Convert package names to module names"""
    PACKAGE_TO_MODULE = {
        "slackclient": "slack",
        "slack-sdk": "slack_sdk",
        "pyyaml": "yaml",
        "beautifulsoup4": "bs4",
        "opencv-python": "cv2",
        "scikit-learn": "sklearn",
        "pillow": "PIL",
    }
    return PACKAGE_TO_MODULE.get(name, name)

def run_repograph_for_repo(repo_name, yaml_path):
    """Run repograph for a single repo"""
    repo_path = REPOS_DIR / repo_name

    if not repo_path.exists():
        print(f"❌ {repo_name}: repo directory not found")
        return False

    if not yaml_path.exists():
        print(f"❌ {repo_name}: yaml file not found at {yaml_path}")
        return False

    # Check venv exists
    venv_python = repo_path / ".venv_helper" / "bin" / "python"
    if not venv_python.exists():
        print(f"❌ {repo_name}: venv not found at {venv_python}")
        return False

    try:
        # Load migration config
        config = load_yaml(yaml_path)
        source = config.get("source")
        target = config.get("target")

        # Convert package names to module names
        source = convert_package_to_module(source)
        target = convert_package_to_module(target) if target else None

        if not source:
            print(f"❌ {repo_name}: no source in yaml")
            return False

        print(f"🔍 {repo_name}: source={source}, target={target}")

        # Create client with venv
        custom_init = {
            "initializationOptions": {
                "workspace": {
                    "environmentPath": str(venv_python)
                }
            }
        }

        client = MultilspyLSPClient(str(repo_path), custom_init_params=custom_init)

        try:
            # Find references for source
            refs = client.find_refs_by_fqn(module=source)

            # Format results (same as testing_agent does)
            files = []
            seen = set()
            for ref in refs:
                abs_path = Path(ref["absolute_path"])
                try:
                    rel_path = abs_path.relative_to(repo_path)
                    rel_str = str(rel_path)
                    if rel_str not in seen:
                        seen.add(rel_str)
                        files.append(rel_str)
                except ValueError:
                    pass

            result = {
                "source": {
                    "module": source,
                    "qualpath": None
                },
                "library_consumers": {
                    "files": files,
                    "references": [
                        {
                            "relative_path": str(Path(ref["absolute_path"]).relative_to(repo_path)),
                            "absolute_path": ref["absolute_path"],
                            "line": ref["line"],
                            "character": ref["character"]
                        }
                        for ref in refs
                    ]
                },
                "workspace_callers": {}
            }

            # Write result
            output_dir = repo_path / ".testing_agent"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / "repograph_result.json"

            with open(output_file, "w") as f:
                json.dump(result, f, indent=2)

            found_count = len(files)
            ref_count = len(refs)
            status = "✅" if found_count > 0 else "⚠️"
            print(f"{status} {repo_name}: found {found_count} files, {ref_count} refs")
            return found_count > 0

        finally:
            client.shutdown()

    except Exception as e:
        print(f"❌ {repo_name}: {type(e).__name__}: {str(e)[:150]}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main entry point"""
    print(f"Running repograph on {len(REPOS)} repos...\n")

    # Load name_map
    name_map = load_name_map()

    success_count = 0
    fail_count = 0

    for repo_name in REPOS:
        # Get yaml path from name_map
        yaml_path = get_yaml_for_repo(repo_name, name_map)

        if yaml_path is None:
            print(f"❌ {repo_name}: not found in name_map")
            fail_count += 1
            continue

        if run_repograph_for_repo(repo_name, yaml_path):
            success_count += 1
        else:
            fail_count += 1
        print()

    print(f"\n{'='*60}")
    print(f"Summary: {success_count} successful, {fail_count} failed")
    print(f"{'='*60}")

    return 0 if fail_count == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
