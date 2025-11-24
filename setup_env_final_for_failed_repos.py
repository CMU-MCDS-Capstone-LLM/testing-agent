#!/usr/bin/env python3
"""
Final batch environment setup script.

This script:
1. Contains an internal repo list that MUST be processed.
2. Automatically skips known “already working” repos.
3. Automatically determines the correct Python version from decision.json.
4. Installs APT packages, pip dependencies, editable installs.
5. Creates correct venv for each repo.
6. Installs pytest / coverage.

Usage:
    python setup_env_final.py
"""

import json
import subprocess
import sys
from pathlib import Path

# --------------------------------------------------------------------
# 1. *** Repos that require environment setup ***
# --------------------------------------------------------------------
TARGET_REPOS = [
    # "aiortc_aiortc__270edaf4237cba1942fc0b8cc98f3ae4dfc3f0e1",
    # "alice-biometrics_petisco__9abf7b1f6ef8c55bdddcb9a5c2eff513f6a93130",
    # "apryor6_flaskerize__59d8319355bf95f26949fe13ac3d6be5b5282fb6",
    # "cloud-custodian_cloud-custodian__12e3e8084ddb2e7f5ccbc5ea3c3bd3e4c7e9c207",
    # "greenbone_python-gvm__75a11ed482b70b5ffceaac939294ebaad2d7fe58",
    # "htrc_htrc-feature-reader__7eae68aa368f3e1bc41b36a4f504f8bbe6ff46c8",
    # "huggingface_transfer-learning-conv-ai__16074b209c8a94c887c2b869d773ea5f56d8593b",
    # "hxlstandard_libhxl-python__0babff28e04c7da97cae91de78e86295bc42b118",
    # "ictu_quality-time__d3a9a16a72348cece48c9788cf10db6cc043ec7c",
    # "jsybrandt_agatha__b570ef0eed11a0d55f1e00d0291fccad62f06222",
    # "paradoxalarminterface_pai__fac6f807b02028921310e48d14f3b71b365e283b",
    # "simonlindholm_decomp-permuter__cfbb706402fe106ae19762279eab8294a531f20c",
    "1and1_confluencer__df895ac8e75c13e32e2369bc4d9c88aa036ab9d4",
    "ansible-community_molecule__b7d7740db482624182dd6c31600ca1c09669cfc5",
    "azure_aztk__19dde429a702c29bdcf86a69805053ecfd02edee",
    "bcgov_theorgbook__728f86e941dfb6bdbee27628d28425757af5f22d",
    "bretttolbert_verbecc-svc__24a848d285ae2c6f3e5b06d1a8ee718cb3f17133",
    "celery_celery__9b39fc41998c708c6612f0c7bf4393bf48f72e9b",
    "ctlearn-project_ctlearn__2375af87fa36b7c93c5a3be5cab81784d4a2f64e",
    "cyberbotics_urdf2webots__723168dbfff6132aa5591837d43c960679a0a2c4",
    "deepspace2_styleframe__ffc8d7615fb37996ad7824a0e0501351a8f66b14",
    "educationaltestingservice_skll__f870a65904a449103d8f147e9746e548965f27d1",
    "google_capirca__eb768ea7e8cb33ab16786ddeb52b53122c740c65",
    "googlesamples_assistant-sdk-python__38e4e642cbfc2b0dd5ddf0151e87a867273f9a30",
    "himkt_pyner__76106a9a4202497de9719b5a5563cadd697bd3d0",
    "intelpni_brainiak__e62dc1d02ad1a3f2e7f8ef909b035349cd5552c5",
    "keepsafe_aiohttp__e51fb1ff1ebdde566b96af0090c5c63cf1a62b1b",
    "kinto_kinto__951dd25ca87f6e4b47a87d254cc187331c4d031c",
    "logicaldash_lise__028d0b34a4dadc59b18c88fa3381967c23245e63",
    "mete0r_pyhwp__0c5c5e7898e5c82ad5543ad4f990cbc69439619a",
    "microsoft_nni__b955ac99a46094d2d701d447e9df07509767cc32",
    "mixpanel_mixpanel-python__e8a9330448f8fd4ec2cdb1ab35e0de9a05d9717f",
    "naver_claf__cffe4993564244545f085ede95eb848b94d07bde",
    "nlpia_nlpia-bot__054d5d207cba12d9b5c4765454be1c51424ea4f3",
    "ojarva_python-sshpubkeys__e3ee2d2635e8489ef6e3a57520e3bf1b61d94962",
    "openstack_oslo.messaging__5a842ae15582e4eedfb1b2510eaf4a8997701f58",
    "pimoroni_inky__cba36514eb8c881f8bd1d92b0b6a5bf12b4b72fb",
    "princetonuniversity_psyneulink__5253a55c46d529b69397fc1d54d3f8e7262c337b",
    "rapid-design-of-systems-laboratory_beluga__078e3e56fe5b86d9c188aaf249a72296bd6fa753",
    "reannz_faucet__4a23ef8e3074c8749435de2bd8e2a299a6db9d92",
    "redhat-cip_hardware__a429c38cf6e6630f6bc1d1793f1aa2a75b21cc03",
    "skoczen_will__437f8be397b864dc83c67af8942467907ccf1c21",
    "slackapi_python-slack-sdk__5f4d92a8048814fc4938753594e74d7cfc74c27a",
    "terryyin_google-translate-python__ac375b49cf1e72e0a79f78ba1a74e57b6c3f8aed",
    "tgalal_python-axolotl__f74a936745db2c2f04575bd63308d6b6c0cc91ce",
    "trungdong_prov__acb9b05f0bd99b3fbd58e5f1a684d1cfc28961f8",
    "zalando_spilo__a83681c756fe8dfc8e5117c690bde16319e3e943",
]

# --------------------------------------------------------------------
# 2. *** Repos that already work (skip) ***
# --------------------------------------------------------------------
SKIP_REPOS = {
    "aiortc_aiortc__d30c24009196f6f520010f7cca1d24e7506163be",
    "amesar_mlflow-tools__431737a891b13a73ec7bdbc507fad21531f2cbf3",
    "godaddy_tartufo__553dc5fb7ddef597cafda451954fa4cba23acde6",
    "obsidianforensics_hindsight__973b3d3278609c144f11542bd24164243ee165af",
    "openstack_ironic-inspector__f4648facf76ff2ac742fc11bb81880f262e61ee2",
    "romanz_trezor-agent__e1bbdb4bccb9c81a34123cc89fbb6ef2750ab33b",
    "thombashi_tcconfig__7ba8676b3b9347ef15142bfeba30d611822c154d",
}

DATA_ROOT = Path("/home/ubuntu/testing-agent/full_data-success_only-all")


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

def run(cmd, cwd=None):
    print(f"[RUN] {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr)
    return res.returncode == 0, res.stdout + res.stderr


def detect_python_version(decision):
    variables = decision.get("variables", {})
    evidence  = decision.get("evidence", {})

    tag = variables.get("python_version_tag", "")

    # 1. Use python_version_tag first
    if tag.startswith("3.7"):
        return "/usr/bin/python3.7"
    if tag.startswith("3.8"):
        return "/usr/bin/python3.8"
    if tag.startswith("3.9"):
        return "/usr/bin/python3.9"
    if tag.startswith("3.6"):
        return "/usr/bin/python3.8"  # migrate 3.6 → 3.8

    # 2. Parse constraints
    constraints = " ".join(evidence.get("python_version_constraints", []))
    if "3.7" in constraints:
        return "/usr/bin/python3.7"
    if "3.8" in constraints:
        return "/usr/bin/python3.8"
    if "3.9" in constraints:
        return "/usr/bin/python3.9"
    if "3.6" in constraints:
        return "/usr/bin/python3.8"

    # 3. Default (modern)
    return "/usr/bin/python3.10"


def create_venv(repo_path, python):
    venv = repo_path / ".venv_helper"
    run(["rm", "-rf", str(venv)])
    ok, _ = run([python, "-m", "venv", str(venv)])
    if not ok:
        raise RuntimeError("Venv creation failed.")
    return venv


import shlex

def pip_install(venv, packages, cwd=None):
    pip = venv / "bin" / "pip"

    for p in packages:
        # shlex.split() handles cases like "-r requirements/requirements.txt"
        args = shlex.split(p)

        # Special handling: if "-r" is used, check file existence
        if args[0] == "-r" and len(args) > 1:
            req_path = args[1].lstrip()  # remove accidental leading spaces
            req_full = (cwd / req_path) if cwd else Path(req_path)

            if not req_full.exists():
                print(f"[WARN] requirements file missing → {req_full}, skipping...")
                continue

        # Try pip install
        ok, out = run([str(pip), "install"] + args, cwd=cwd)

        if not ok:
            print(f"[WARN] pip failed for {p}, continuing")
            print(out)
            continue


# --------------------------------------------------------------------
# Main processing
# --------------------------------------------------------------------
def setup_repo(repo_id):
    if repo_id in SKIP_REPOS:
        print(f"[SKIP] {repo_id} already works.")
        return

    repo_path = DATA_ROOT / "repos" / repo_id
    decision_path = DATA_ROOT / "envs" / repo_id / "decision.json"

    print(f"\n========== Setting up {repo_id} ==========")

    if not decision_path.exists():
        print(f"[ERROR] decision.json not found for {repo_id}")
        return

    decision = json.load(open(decision_path))
    variables = decision.get("variables", {})

    # --- Determine python version ---
    python_bin = detect_python_version(decision)
    print(f"[INFO] Python selected: {python_bin}")

    # --- Install APT packages ---
    apt_pkgs = variables.get("project_apt_packages", [])
    if apt_pkgs:
        print(f"[APT] Installing: {apt_pkgs}")
        run(["sudo", "apt-get", "update"])
        run(["sudo", "apt-get", "install", "-y"] + apt_pkgs)

    # --- Create venv ---
    venv = create_venv(repo_path, python_bin)

    # --- Bootstrap pip ---
    pip_install(venv, ["pip<24.1"], cwd=repo_path)  

    # --- pip dependencies (pip_deps) ---
    pip_deps = variables.get("pip_deps", [])
    pip_install(venv, pip_deps, cwd=repo_path)      

    # --- Testing dependencies ---
    pip_install(venv, ["pytest", "pytest-cov", "coverage"])  

    print(f"[DONE] {repo_id}")


def main():
    for repo in TARGET_REPOS:
        setup_repo(repo)


if __name__ == "__main__":
    main()
