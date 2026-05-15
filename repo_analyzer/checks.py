import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from typing import Callable, Optional

from .config import Config
from .github_client import clone_repo, get_commit_count, get_file_content
from .llm_client import call_llm

_README_RE = re.compile(r"^README(\.\w+)?$", re.IGNORECASE)
_LICENSE_RE = re.compile(r"^(LICENSE|LICENCE|COPYING|NOTICE)(\.\w+)?$", re.IGNORECASE)
_REQUIRE_RE = re.compile(r"^(requirements\.txt|pyproject\.toml)$", re.IGNORECASE)
_TEST_DIR_RE = re.compile(r"^(tests?|__tests__|spec|specs|e2e)$", re.IGNORECASE)

README_MIN_CHARS = 200
APP_TYPES = {"app"}
DATA_TYPES = {"algorithm_experiments", "model_training_experiments"}
EXPERIMENT_TYPES = {"algorithm_experiments", "model_training_experiments"}

_PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def _load_prompt(name: str) -> str:
    with open(os.path.join(_PROMPTS_DIR, name), encoding="utf-8") as f:
        return f.read()


def _sample_tree(all_paths: list, max_per_dir: int = 5, max_total: int = 500) -> list:
    dir_counts: dict = defaultdict(int)
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


def check_readme(flat_paths: list, config: Config) -> dict:
    for path in flat_paths:
        if _README_RE.match(os.path.basename(path)):
            try:
                content = get_file_content(config.repo_url, path, config.github_token)
                char_count = len(content)
                return {
                    "present": True,
                    "meaningful": char_count >= README_MIN_CHARS,
                    "char_count": char_count,
                    "matched_file": path,
                }
            except Exception as e:
                return {"present": True, "meaningful": None, "matched_file": path, "error": str(e)}
    return {"present": False, "meaningful": False, "matched_file": None}


def check_license(flat_paths: list) -> dict:
    for path in flat_paths:
        if _LICENSE_RE.match(os.path.basename(path)):
            return {"present": True, "matched_file": path}
    return {"present": False, "matched_file": None}


def check_requirements(flat_paths: list) -> dict:
    for path in flat_paths:
        if _REQUIRE_RE.match(os.path.basename(path)):
            return {"applicable": True, "present": True, "matched_file": path}
    return {"applicable": True, "present": False, "matched_file": None}


def check_execution_files(flat_paths: list, config: Config) -> dict:
    prompt = _load_prompt("execution_files.txt").replace("{file_list}", "\n".join(flat_paths))
    result = call_llm(prompt, config.openrouter_key, config.model)
    if "error" in result:
        return {"present": False, "error": result["error"], "llm_suggested": [], "verified": []}
    suggested = result.get("entry_points", [])
    path_set = set(flat_paths)
    verified = [p for p in suggested if p in path_set]
    return {"present": bool(verified), "llm_suggested": suggested, "verified": verified}


def check_repo_type(all_paths: list, config: Config) -> dict:
    capped = _sample_tree(all_paths)
    prompt = _load_prompt("repo_type.txt").replace("{file_list}", "\n".join(capped))
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
        for part in path.replace("\\", "/").split("/")[:-1]:
            if _TEST_DIR_RE.match(part):
                return {"applicable": True, "present": True, "method": "regex", "files": [part + "/"]}

    prompt = _load_prompt("test_files.txt").replace("{file_list}", "\n".join(flat_paths))
    result = call_llm(prompt, config.openrouter_key, config.model)
    if "error" in result:
        return {"applicable": True, "present": False, "error": result["error"], "files": []}
    path_set = set(flat_paths)
    verified = [p for p in result.get("test_files", []) if p in path_set]
    return {"applicable": True, "present": bool(verified), "method": "llm", "files": verified}


def check_data_files(flat_paths: list, config: Config) -> dict:
    prompt = _load_prompt("data_files.txt").replace("{file_list}", "\n".join(flat_paths))
    result = call_llm(prompt, config.openrouter_key, config.model)
    if "error" in result:
        return {"applicable": True, "present": False, "error": result["error"], "files": []}
    path_set = set(flat_paths)
    verified = [p for p in result.get("data_files", []) if p in path_set]
    return {"applicable": True, "present": bool(verified), "files": verified}


def check_experiment_scripts(flat_paths: list, config: Config, readme_content: str = "") -> dict:
    readme_section = (
        f"README content:\n{readme_content[:3000]}" if readme_content else ""
    )
    prompt = (
        _load_prompt("experiment_scripts.txt")
        .replace("{file_list}", "\n".join(flat_paths))
        .replace("{readme_section}", readme_section)
    )
    result = call_llm(prompt, config.openrouter_key, config.model)
    if "error" in result:
        return {"applicable": True, "present": False, "error": result["error"], "files": []}
    path_set = set(flat_paths)
    verified = [p for p in result.get("experiment_files", []) if p in path_set]
    return {"applicable": True, "present": bool(verified), "files": verified}


def check_commits(config: Config) -> dict:
    count = get_commit_count(config.repo_url, config.github_token, threshold=5)
    return {"present": count > 5, "count": count}


def check_syntax(flat_paths: list, clone_dir: str) -> dict:
    py_files = [p for p in flat_paths if p.endswith(".py")]
    if not py_files:
        return {"ok": True, "errors": [], "summary": "no Python files"}

    result = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", "."],
        cwd=clone_dir, capture_output=True, text=True, timeout=60,
    )
    error_lines = [
        line.strip()
        for line in (result.stdout + result.stderr).splitlines()
        if line.strip() and ("SyntaxError" in line or "***" in line or "Error" in line)
    ]
    ok = result.returncode == 0
    summary = f"all {len(py_files)} files ok" if ok else f"{len(error_lines)} error(s) in {len(py_files)} files"
    return {"ok": ok, "errors": error_lines[:10], "summary": summary}


def check_docstrings(flat_paths: list, clone_dir: str) -> dict:
    py_files = [p for p in flat_paths if p.endswith(".py")]
    if not py_files:
        return {"coverage_pct": None, "documented": 0, "total": 0, "summary": "no Python files"}

    total = documented = 0
    for rel_path in py_files:
        try:
            with open(os.path.join(clone_dir, rel_path), encoding="utf-8", errors="replace") as f:
                tree = ast.parse(f.read())
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
        return {"coverage_pct": 0, "documented": 0, "total": 0, "summary": "no functions or classes found"}
    pct = round(documented / total * 100)
    return {"coverage_pct": pct, "documented": documented, "total": total,
            "summary": f"{pct}% ({documented}/{total} functions/classes)"}


Progress = Optional[Callable[[str, float], None]]


def run_all_checks(
    flat_paths: list,
    all_paths: list,
    config: Config,
    on_progress: Progress = None,
) -> dict:
    def _progress(msg: str, pct: float) -> None:
        print(msg, file=sys.stderr)
        if on_progress:
            on_progress(msg, pct)

    results: dict = {}

    _progress("Checking README...", 0.10)
    results["readme"] = check_readme(flat_paths, config)

    _progress("Checking license...", 0.15)
    results["license"] = check_license(flat_paths)

    _progress("Checking commits...", 0.20)
    results["commits"] = check_commits(config)

    _progress("Identifying entry-point files...", 0.30)
    results["execution_files"] = check_execution_files(flat_paths, config)

    _progress("Classifying repository type...", 0.40)
    repo_type_result = check_repo_type(all_paths, config)
    results["repo_type"] = repo_type_result
    repo_type = repo_type_result.get("value", "algorithm_experiments")

    if repo_type in APP_TYPES:
        results["requirements"] = {"applicable": False}
        _progress("Checking tests...", 0.50)
        results["tests"] = check_tests(flat_paths, all_paths, config)
    else:
        _progress("Checking requirements file...", 0.50)
        results["requirements"] = check_requirements(flat_paths)
        results["tests"] = {"applicable": False}

    if repo_type in DATA_TYPES:
        _progress("Identifying data files...", 0.60)
        results["data_files"] = check_data_files(flat_paths, config)
    else:
        results["data_files"] = {"applicable": False}

    if repo_type in EXPERIMENT_TYPES:
        _progress("Identifying experiment scripts...", 0.70)
        readme_content = ""
        readme_check = results.get("readme", {})
        if readme_check.get("present") and readme_check.get("matched_file"):
            try:
                readme_content = get_file_content(config.repo_url, readme_check["matched_file"], config.github_token)
            except Exception:
                pass
        results["experiment_scripts"] = check_experiment_scripts(flat_paths, config, readme_content)
    else:
        results["experiment_scripts"] = {"applicable": False}

    _progress("Cloning repository for syntax and docstring checks...", 0.75)
    tmp_dir = tempfile.mkdtemp()
    try:
        clone_repo(config.repo_url, config.github_token, tmp_dir)
        _progress("Checking syntax...", 0.85)
        results["syntax"] = check_syntax(flat_paths, tmp_dir)
        _progress("Measuring docstring coverage...", 0.92)
        results["docstrings"] = check_docstrings(flat_paths, tmp_dir)
    except Exception as e:
        print(f"WARNING: clone failed: {e}", file=sys.stderr)
        results["syntax"] = {"ok": None, "errors": [], "summary": f"clone failed: {e}"}
        results["docstrings"] = {"coverage_pct": None, "documented": 0, "total": 0,
                                 "summary": f"clone failed: {e}"}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return results