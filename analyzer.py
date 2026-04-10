#!/usr/bin/env python3
import argparse
import json
import sys

from config import load_config
from github_client import get_tree
from checks import run_all_checks
from report import build_report, build_text_report, save_results


def main():
    parser = argparse.ArgumentParser(
        description="Analyze a GitHub repository for thesis project quality criteria."
    )
    parser.add_argument("--repo", required=True, help="GitHub repository URL (e.g. https://github.com/owner/repo)")
    parser.add_argument("--token", default=None, help="GitHub personal access token (or set GITHUB_TOKEN env var)")
    parser.add_argument("--openrouter-key", default=None, dest="openrouter_key",
                        help="OpenRouter API key (or set OPENROUTER_KEY env var)")
    parser.add_argument("--model", default=None, help="OpenRouter model ID (default: openai/gpt-4o-mini)")
    parser.add_argument("--thesis", default=None, metavar="FILE",
                        help="Path to thesis text file (optional, stored in report metadata)")
    parser.add_argument("--output-dir", default=None, dest="output_dir",
                        help="Base directory for results (default: ./results/)")
    parser.add_argument("--json-only", action="store_true", dest="json_only",
                        help="Print only JSON output, skip human-readable text")
    args = parser.parse_args()

    # Load and validate config
    try:
        config = load_config(args)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"Error reading thesis file: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching repository: {config.repo_url}", file=sys.stderr)

    # Fetch repo tree via PyGitHub
    try:
        flat_paths, all_paths = get_tree(config.repo_url, config.github_token)
    except Exception as e:
        print(f"Error fetching repository: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Tree: {len(flat_paths)} files, {len(all_paths) - len(flat_paths)} directories", file=sys.stderr)

    # Run all checks
    print("Running checks...", file=sys.stderr)
    results = run_all_checks(flat_paths, all_paths, config)

    # Build and save report
    report = build_report(results, config.repo_url)
    if config.thesis_text:
        report["thesis_text_provided"] = True

    json_path, txt_path = save_results(report, config.output_dir)
    print(f"Results saved to: {json_path}", file=sys.stderr)
    print(f"             and: {txt_path}", file=sys.stderr)

    # Print output
    if not args.json_only:
        print("\n" + build_text_report(report) + "\n")

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
