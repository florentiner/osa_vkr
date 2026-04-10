import ast
import os
import re
import shutil
import sys
import tempfile
from collections import defaultdict

from llm_client import call_llm
from config import Config
from github_client import get_file_content, clone_repo

# ── Regex patterns (matched against basename only) ────────────────────────────

README_RE = re.compile(r"^README(\.\w+)?$", re.IGNORECASE)
LICENSE_RE = re.compile(r"^(LICENSE|LICENCE|COPYING|NOTICE)(\.\w+)?$", re.IGNORECASE)
REQUIRE_RE = re.compile(r"^(requirements\.txt|pyproject\.toml)$", re.IGNORECASE)
TEST_DIR_RE = re.compile(r"^(tests?|__tests__|spec|specs|e2e)$", re.IGNORECASE)

README_MIN_CHARS = 200

# Gating sets
APP_TYPES        = {"app"}
DATA_TYPES       = {"algorithm_experiments", "model_training_experiments"}
EXPERIMENT_TYPES = {"algorithm_experiments", "model_training_experiments"}

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def _load_prompt(name: str) -> str:
    with open(os.path.join(PROMPTS_DIR, name), encoding="utf-8") as f:
        return f.read()


def _path_set(paths: list) -> set:
    return set(paths)


# ── Individual checks ─────────────────────────────────────────────────────────


def check_readme(flat_paths: list, config: Config) -> dict:
    for path in flat_paths:
        if README_RE.match(os.path.basename(path)):
            try:
                content = get_file_content(config.repo_url, path, config.github_token)
                char_count = len(content)
                meaningful = char_count >= README_MIN_CHARS
                return {
                    "present": True,
                    "meaningful": meaningful,
                    "char_count": char_count,
                    "matched_file": path,
                }
            except Exception as e:
                return {"present": True, "meaningful": None, "matched_file": path, "error": str(e)}
    return {"present": False, "meaningful": False, "matched_file": None}


def check_license(flat_paths: list) -> dict:
    for path in flat_paths:
        if LICENSE_RE.match(os.path.basename(path)):
            return {"present": True, "matched_file": path}
    return {"present": False, "matched_file": None}


def check_requirements(flat_paths: list) -> dict:
    for path in flat_paths:
        if REQUIRE_RE.match(os.path.basename(path)):
            return {"applicable": True, "present": True, "matched_file": path}
    return {"applicable": True, "present": False, "matched_file": None}


def check_execution_files(flat_paths: list, config: Config) -> dict:
    file_list = "\n".join(flat_paths)
    prompt = _load_prompt("execution_files.txt").replace("{file_list}", file_list)
    result = call_llm(prompt, config.openrouter_key, config.model)

    if "error" in result:
        return {"present": False, "error": result["error"], "llm_suggested": [], "verified": []}

    suggested = result.get("entry_points", [])
    path_set = _path_set(flat_paths)
    verified = [p for p in suggested if p in path_set]
    return {"present": len(verified) > 0, "llm_suggested": suggested, "verified": verified}


def _sample_tree(all_paths: list, max_per_dir: int = 5, max_total: int = 500) -> list:
    dir_counts = defaultdict(int)
    sampled = []
    for path in all_paths:
        parts = path.replace("\\", "/").split("/")
        parent = "/".join(parts[:-1]) if len(parts) > 1 else ""
        if dir_counts[parent] < max_per_dir:
            sampled.append(path)
            dir_counts[parent] += 1
        if len(sampled) >= max_total:
            break
    return sampled


def check_repo_type(all_paths: list, config: Config) -> dict:
    capped = _sample_tree(all_paths)
    file_list = "\n".join(capped)
    prompt = _load_prompt("repo_type.txt").replace("{file_list}", file_list)
    result = call_llm(prompt, config.openrouter_key, config.model)

    if "error" in result:
        return {"value": "algorithm_experiments", "confidence": "low",
                "reasoning": result.get("error", ""), "error": result["error"]}

    return {
        "value": result.get("repo_type", "algorithm_experiments"),
        "confidence": result.get("confidence", "low"),
        "reasoning": result.get("reasoning", ""),
    }


def check_tests(flat_paths: list, all_paths: list, config: Config) -> dict:
    for path in all_paths:
        parts = path.replace("\\", "/").split("/")
        for part in parts[:-1]:
            if TEST_DIR_RE.match(part):
                return {"applicable": True, "present": True, "method": "regex",
                        "files": [parts[0] + "/"]}

    file_list = "\n".join(flat_paths)
    prompt = _load_prompt("test_files.txt").replace("{file_list}", file_list)
    result = call_llm(prompt, config.openrouter_key, config.model)

    if "error" in result:
        return {"applicable": True, "present": False, "error": result["error"], "files": []}

    path_set = _path_set(flat_paths)
    verified = [p for p in result.get("test_files", []) if p in path_set]
    return {"applicable": True, "present": len(verified) > 0, "method": "llm", "files": verified}


def check_data_files(flat_paths: list, config: Config) -> dict:
    file_list = "\n".join(flat_paths)
    prompt = _load_prompt("data_files.txt").replace("{file_list}", file_list)
    result = call_llm(prompt, config.openrouter_key, config.model)

    if "error" in result:
        return {"applicable": True, "present": False, "error": result["error"], "files": []}

    path_set = _path_set(flat_paths)
    verified = [p for p in result.get("data_files", []) if p in path_set]
    return {"applicable": True, "present": len(verified) > 0, "files": verified}


def check_experiment_scripts(flat_paths: list, config: Config) -> dict:
    file_list = "\n".join(flat_paths)
    prompt = _load_prompt("experiment_scripts.txt").replace("{file_list}", file_list)
    result = call_llm(prompt, config.openrouter_key, config.model)

    if "error" in result:
        return {"applicable": True, "present": False, "error": result["error"], "files": []}

    path_set = _path_set(flat_paths)
    verified = [p for p in result.get("experiment_files", []) if p in path_set]
    return {"applicable": True, "present": len(verified) > 0, "files": verified}


def check_syntax(flat_paths: list, clone_dir: str) -> dict:
    """Run python -m compileall on all .py files in the cloned repo."""
    import subprocess
    py_files = [p for p in flat_paths if p.endswith(".py")]
    if not py_files:
        return {"ok": True, "errors": [], "summary": "no Python files"}

    result = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", "."],
        cwd=clone_dir, capture_output=True, text=True, timeout=60,
    )

    error_lines = []
    for line in (result.stdout + result.stderr).splitlines():
        line = line.strip()
        if line and ("SyntaxError" in line or "***" in line or "Error" in line):
            error_lines.append(line)

    ok = result.returncode == 0
    if ok:
        summary = f"all {len(py_files)} files ok"
    else:
        summary = f"{len(error_lines)} error(s) in {len(py_files)} files"

    return {"ok": ok, "errors": error_lines[:10], "summary": summary}


def check_docstrings(flat_paths: list, clone_dir: str) -> dict:
    """Measure docstring coverage of all .py files using ast."""
    py_files = [p for p in flat_paths if p.endswith(".py")]
    if not py_files:
        return {"coverage_pct": None, "summary": "no Python files"}

    total = 0
    documented = 0

    for rel_path in py_files:
        full_path = os.path.join(clone_dir, rel_path)
        try:
            with open(full_path, encoding="utf-8", errors="replace") as f:
                source = f.read()
            tree = ast.parse(source)
        except Exception:
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                total += 1
                if (node.body
                        and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)
                        and isinstance(node.body[0].value.value, str)):
                    documented += 1

    if total == 0:
        return {"coverage_pct": 0, "documented": 0, "total": 0,
                "summary": "no functions or classes found"}

    pct = round(documented / total * 100)
    return {
        "coverage_pct": pct,
        "documented": documented,
        "total": total,
        "summary": f"{pct}% ({documented}/{total} functions/classes)",
    }


# ── Orchestrator ──────────────────────────────────────────────────────────────


def run_all_checks(flat_paths: list, all_paths: list, config: Config) -> dict:
    results = {}

    # Always: readme (fetches content), license
    results["readme"] = check_readme(flat_paths, config)
    results["license"] = check_license(flat_paths)

    # Execution files + repo type (repo_type gates requirements)
    results["execution_files"] = check_execution_files(flat_paths, config)
    repo_type_result = check_repo_type(all_paths, config)
    results["repo_type"] = repo_type_result
    repo_type = repo_type_result.get("value", "algorithm_experiments")

    # Requirements: skip for app types
    if repo_type in APP_TYPES:
        results["requirements"] = {"applicable": False}
    else:
        results["requirements"] = check_requirements(flat_paths)

    # Tests: only for app types
    if repo_type in APP_TYPES:
        results["tests"] = check_tests(flat_paths, all_paths, config)
    else:
        results["tests"] = {"applicable": False}

    # Data files
    if repo_type in DATA_TYPES:
        results["data_files"] = check_data_files(flat_paths, config)
    else:
        results["data_files"] = {"applicable": False}

    # Experiment scripts
    if repo_type in EXPERIMENT_TYPES:
        results["experiment_scripts"] = check_experiment_scripts(flat_paths, config)
    else:
        results["experiment_scripts"] = {"applicable": False}

    # Clone repo once for syntax + docstring checks
    tmp_dir = tempfile.mkdtemp()
    try:
        print("Cloning repo for syntax/docstring analysis...", file=sys.stderr)
        clone_repo(config.repo_url, config.github_token, tmp_dir)
        results["syntax"] = check_syntax(flat_paths, tmp_dir)
        results["docstrings"] = check_docstrings(flat_paths, tmp_dir)
    except Exception as e:
        print(f"WARNING: clone failed: {e}", file=sys.stderr)
        results["syntax"] = {"ok": None, "errors": [], "summary": f"clone failed: {e}"}
        results["docstrings"] = {"coverage_pct": None, "summary": f"clone failed: {e}"}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return results
