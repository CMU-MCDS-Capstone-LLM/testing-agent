#!/usr/bin/env python3
"""Setup environments for all 59 repos with timeout handling"""

import json
import subprocess
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import shutil

REPOS = [
    "1and1_confluencer__df895ac8e75c13e32e2369bc4d9c88aa036ab9d4",
    "aiortc_aiortc__270edaf4237cba1942fc0b8cc98f3ae4dfc3f0e1",
    "aiortc_aiortc__d30c24009196f6f520010f7cca1d24e7506163be",
    "alice-biometrics_petisco__9abf7b1f6ef8c55bdddcb9a5c2eff513f6a93130",
    "amesar_mlflow-tools__431737a891b13a73ec7bdbc507fad21531f2cbf3",
    "ansible-community_molecule__b7d7740db482624182dd6c31600ca1c09669cfc5",
    "apryor6_flaskerize__59d8319355bf95f26949fe13ac3d6be5b5282fb6",
    "azure_aztk__19dde429a702c29bdcf86a69805053ecfd02edee",
    "bcgov_theorgbook__728f86e941dfb6bdbee27628d28425757af5f22d",
    "bretttolbert_verbecc-svc__24a848d285ae2c6f3e5b06d1a8ee718cb3f17133",
    "celery_celery__9b39fc41998c708c6612f0c7bf4393bf48f72e9b",
    "cloud-custodian_cloud-custodian__12e3e8084ddb2e7f5ccbc5ea3c3bd3e4c7e9c207",
    "ctlearn-project_ctlearn__2375af87fa36b7c93c5a3be5cab81784d4a2f64e",
    "cyberbotics_urdf2webots__723168dbfff6132aa5591837d43c960679a0a2c4",
    "czheo_syntax_sugar_python__1dbc1d44855acd57f280cca03878681e8dc26b01",
    "deepspace2_styleframe__ffc8d7615fb37996ad7824a0e0501351a8f66b14",
    "educationaltestingservice_skll__f870a65904a449103d8f147e9746e548965f27d1",
    "emlid_ntripbrowser__9161c1943a8623892b174c98cdf686a4a0ce8673",
    "godaddy_tartufo__553dc5fb7ddef597cafda451954fa4cba23acde6",
    "google_capirca__eb768ea7e8cb33ab16786ddeb52b53122c740c65",
    "googlesamples_assistant-sdk-python__38e4e642cbfc2b0dd5ddf0151e87a867273f9a30",
    "grahame_sedge__3badf078e2f4153db161cada1c7a23901e36ab7f",
    "greenbone_python-gvm__75a11ed482b70b5ffceaac939294ebaad2d7fe58",
    "hbldh_pybankid__79e424cef579d6bffc1e40048e46febbd53aded5",
    "himkt_pyner__76106a9a4202497de9719b5a5563cadd697bd3d0",
    "htrc_htrc-feature-reader__7eae68aa368f3e1bc41b36a4f504f8bbe6ff46c8",
    "huggingface_transfer-learning-conv-ai__16074b209c8a94c887c2b869d773ea5f56d8593b",
    "hxlstandard_libhxl-python__0babff28e04c7da97cae91de78e86295bc42b118",
    "ictu_quality-time__d3a9a16a72348cece48c9788cf10db6cc043ec7c",
    "intelpni_brainiak__e62dc1d02ad1a3f2e7f8ef909b035349cd5552c5",
    "jsybrandt_agatha__b570ef0eed11a0d55f1e00d0291fccad62f06222",
    "keepsafe_aiohttp__e51fb1ff1ebdde566b96af0090c5c63cf1a62b1b",
    "kinto_kinto__951dd25ca87f6e4b47a87d254cc187331c4d031c",
    "logicaldash_lise__028d0b34a4dadc59b18c88fa3381967c23245e63",
    "mete0r_pyhwp__0c5c5e7898e5c82ad5543ad4f990cbc69439619a",
    "microsoft_nni__b955ac99a46094d2d701d447e9df07509767cc32",
    "mixpanel_mixpanel-python__e8a9330448f8fd4ec2cdb1ab35e0de9a05d9717f",
    "naver_claf__cffe4993564244545f085ede95eb848b94d07bde",
    "nlpia_nlpia-bot__054d5d207cba12d9b5c4765454be1c51424ea4f3",
    "obsidianforensics_hindsight__973b3d3278609c144f11542bd24164243ee165af",
    "ojarva_python-sshpubkeys__e3ee2d2635e8489ef6e3a57520e3bf1b61d94962",
    "openstack_ironic-inspector__f4648facf76ff2ac742fc11bb81880f262e61ee2",
    "openstack_oslo.messaging__5a842ae15582e4eedfb1b2510eaf4a8997701f58",
    "paradoxalarminterface_pai__fac6f807b02028921310e48d14f3b71b365e283b",
    "pimoroni_inky__cba36514eb8c881f8bd1d92b0b6a5bf12b4b72fb",
    "princetonuniversity_psyneulink__5253a55c46d529b69397fc1d54d3f8e7262c337b",
    "rapid-design-of-systems-laboratory_beluga__078e3e56fe5b86d9c188aaf249a72296bd6fa753",
    "reannz_faucet__4a23ef8e3074c8749435de2bd8e2a299a6db9d92",
    "redhat-cip_hardware__a429c38cf6e6630f6bc1d1793f1aa2a75b21cc03",
    "romanz_trezor-agent__e1bbdb4bccb9c81a34123cc89fbb6ef2750ab33b",
    "simonlindholm_decomp-permuter__cfbb706402fe106ae19762279eab8294a531f20c",
    "skoczen_will__437f8be397b864dc83c67af8942467907ccf1c21",
    "slackapi_python-slack-sdk__5f4d92a8048814fc4938753594e74d7cfc74c27a",
    "tankerhq_tbump__54b12e29d860336593ff24a514f4d2c9c483b470",
    "terryyin_google-translate-python__ac375b49cf1e72e0a79f78ba1a74e57b6c3f8aed",
    "tgalal_python-axolotl__f74a936745db2c2f04575bd63308d6b6c0cc91ce",
    "thombashi_tcconfig__7ba8676b3b9347ef15142bfeba30d611822c154d",
    "trungdong_prov__acb9b05f0bd99b3fbd58e5f1a684d1cfc28961f8",
    "zalando_spilo__a83681c756fe8dfc8e5117c690bde16319e3e943",
]

BASE_PATH = Path("/home/ubuntu/testing-agent/full_data-success_only-all")
ENVS_DIR = BASE_PATH / "envs"
REPOS_DIR = BASE_PATH / "repos"

def find_available_python(requested_version):
    """Find available Python version - return requested or fallback to 3.10"""
    # Try requested version first
    python_exe = f"python{requested_version}"
    if shutil.which(python_exe):
        return python_exe

    # Try major.minor version (e.g., "3.8.18" -> "3.8")
    major_minor = ".".join(requested_version.split(".")[:2])
    python_exe = f"python{major_minor}"
    if shutil.which(python_exe):
        return python_exe

    # Fallback to 3.10
    return "python3.10"

def setup_repo_env(repo_name):
    """Setup environment for a single repo"""
    decision_json = ENVS_DIR / repo_name / "decision.json"
    repo_path = REPOS_DIR / repo_name
    venv_path = repo_path / ".venv_helper"

    # Skip if already has venv
    if venv_path.exists():
        return repo_name, "SKIP", "venv already exists"

    if not decision_json.exists():
        return repo_name, "FAIL", "decision.json not found"

    if not repo_path.exists():
        return repo_name, "FAIL", "repo path not found"

    try:
        with open(decision_json) as f:
            decision = json.load(f)

        variables = decision.get("variables", {})
        python_version = variables.get("python_version_tag", "3.11").split("-")[0]
        apt_packages = variables.get("project_apt_packages", [])
        pip_deps = variables.get("pip_deps", [])

        # 1. Install apt packages (with timeout 120s)
        if apt_packages:
            apt_cmd = ["sudo", "apt-get", "install", "-y"] + apt_packages
            try:
                subprocess.run(apt_cmd, capture_output=True, text=True, timeout=120)
            except subprocess.TimeoutExpired:
                return repo_name, "WARN", "apt install timeout"
            except Exception as e:
                return repo_name, "WARN", f"apt install error: {str(e)[:50]}"

        # 2. Create venv (with timeout 60s)
        python_exe = find_available_python(python_version)
        create_cmd = [python_exe, "-m", "venv", str(venv_path)]
        try:
            result = subprocess.run(create_cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                return repo_name, "FAIL", f"venv creation failed"
        except subprocess.TimeoutExpired:
            return repo_name, "FAIL", "venv creation timeout"

        # 3. Install pip deps (with timeout 180s per dep)
        pip_exe = venv_path / "bin" / "pip"

        # Upgrade pip (with timeout)
        try:
            subprocess.run([str(pip_exe), "install", "--upgrade", "pip"],
                         capture_output=True, timeout=60)
        except subprocess.TimeoutExpired:
            pass  # Continue anyway
        except Exception:
            pass

        # Always install pytest and pytest-cov with compatible versions
        default_deps = ["pytest>=7.0", "pytest-cov>=4.0"]
        all_deps = default_deps + (pip_deps if pip_deps else [])

        # Install each dep with timeout
        for dep in all_deps:
                try:
                    subprocess.run(
                        [str(pip_exe), "install"] + dep.split(),
                        capture_output=True,
                        text=True,
                        cwd=str(repo_path),
                        timeout=180
                    )
                except subprocess.TimeoutExpired:
                    return repo_name, "WARN", f"pip install timeout on {dep[:30]}"
                except Exception as e:
                    return repo_name, "WARN", f"pip install error: {str(e)[:30]}"

        # Handle editable installation (e.g., pip install -e ".[dev]")
        install_editable = variables.get("install_editable", False)
        if install_editable:
            pip_loc_e_dep = variables.get("pip_loc_e_dep", ".")
            editable_spec = f"-e {repo_path}/{pip_loc_e_dep}" if pip_loc_e_dep != "." else f"-e {repo_path}"
            try:
                subprocess.run(
                    [str(pip_exe), "install", editable_spec],
                    capture_output=True,
                    text=True,
                    cwd=str(repo_path),
                    timeout=180
                )
            except subprocess.TimeoutExpired:
                return repo_name, "WARN", f"pip editable install timeout"
            except Exception as e:
                return repo_name, "WARN", f"pip editable install error: {str(e)[:30]}"

        return repo_name, "OK", "setup completed"

    except Exception as e:
        return repo_name, "FAIL", f"Error: {str(e)[:50]}"

def main():
    print(f"Setting up environments for {len(REPOS)} repos in parallel...\n")

    results = {"OK": [], "SKIP": [], "WARN": [], "FAIL": []}

    # Use ThreadPoolExecutor with 4 parallel workers (to avoid system overload)
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(setup_repo_env, repo): repo for repo in REPOS}

        completed = 0
        for future in as_completed(futures):
            completed += 1
            repo_name, status, message = future.result()
            results[status].append((repo_name, message))
            print(f"[{completed}/{len(REPOS)}] {repo_name}: {status} - {message}")

    print(f"\n\n{'='*80}")
    print(f"SUMMARY")
    print(f"{'='*80}")
    print(f"✅ OK (setup completed): {len(results['OK'])}")
    for repo, msg in results['OK']:
        print(f"  - {repo}")

    print(f"\n⏭️  SKIP (venv already exists): {len(results['SKIP'])}")
    for repo, msg in results['SKIP']:
        print(f"  - {repo}")

    if results['WARN']:
        print(f"\n⚠️  WARN (setup but with issues): {len(results['WARN'])}")
        for repo, msg in results['WARN']:
            print(f"  - {repo}: {msg}")

    if results['FAIL']:
        print(f"\n❌ FAIL (setup failed): {len(results['FAIL'])}")
        for repo, msg in results['FAIL']:
            print(f"  - {repo}: {msg}")

if __name__ == "__main__":
    sys.exit(main())
