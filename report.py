import json
import os
import re
from datetime import datetime, timezone
from typing import Tuple


REPO_TYPE_LABELS = {
    "app": "app",
    "algorithm_experiments": "algorithm experiments",
    "model_training_experiments": "model training experiments",
}

# Checks excluded from score (informational only)
SCORE_EXCLUDED = {"repo_type", "syntax", "docstrings"}


def _sanitize_dir_name(repo_url: str) -> str:
    name = repo_url.rstrip("/")
    if "github.com" in name:
        name = name.split("github.com/", 1)[1]
    name = name.replace("/", "__")
    name = re.sub(r"[^\w\-.]", "_", name)
    return name[:100]


def build_report(results: dict, repo_url: str) -> dict:
    checks = dict(results)

    score = 0
    max_applicable = 0

    for key, val in checks.items():
        if key in SCORE_EXCLUDED:
            continue
        if val.get("applicable") is False:
            continue
        max_applicable += 1
        # readme: counts only if present AND meaningful
        if key == "readme":
            if val.get("present") and val.get("meaningful"):
                score += 1
        elif val.get("present"):
            score += 1

    return {
        "repo_url": repo_url,
        "analyzed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checks": checks,
        "summary": {
            "score": score,
            "max_applicable": max_applicable,
        },
    }


def _check_line(key: str, val: dict) -> str:
    if key == "repo_type":
        label = REPO_TYPE_LABELS.get(val.get("value", ""), val.get("value", "other"))
        return f"repo_type: {label}"

    if key == "readme":
        if not val.get("present"):
            return "readme: no"
        if val.get("meaningful") is False:
            return "readme: yes (empty)"
        return "readme: yes"

    if key == "syntax":
        return f"syntax: {val.get('summary', 'unknown')}"

    if key == "docstrings":
        return f"docstrings: {val.get('summary', 'unknown')}"

    if val.get("applicable") is False:
        return f"{key}: not needed (not right type of repo)"

    return f"{key}: {'yes' if val.get('present') else 'no'}"


def build_text_report(report: dict) -> str:
    checks = report["checks"]
    order = [
        "readme",
        "license",
        "requirements",
        "execution_files",
        "repo_type",
        "tests",
        "data_files",
        "experiment_scripts",
        "syntax",
        "docstrings",
    ]
    lines = []
    for key in order:
        if key in checks:
            lines.append(_check_line(key, checks[key]))

    score = report["summary"]["score"]
    max_ap = report["summary"]["max_applicable"]
    lines.append(f"\nscore: {score}/{max_ap}")
    return "\n".join(lines)


def save_results(report: dict, output_dir: str) -> Tuple[str, str]:
    repo_url = report["repo_url"]
    dir_name = _sanitize_dir_name(repo_url)
    target_dir = os.path.join(output_dir, dir_name)
    os.makedirs(target_dir, exist_ok=True)

    json_path = os.path.join(target_dir, "report.json")
    txt_path = os.path.join(target_dir, "report.txt")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(build_text_report(report))

    return json_path, txt_path
