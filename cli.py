app.py#!/usr/bin/env python3
"""CLI entry point for the repository analyzer."""
import argparse
import json
import os
import sys
from pathlib import Path

# Load .env from project root
_env = Path(__file__).parent / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

from repo_analyzer import Config, analyze_full
from repo_analyzer.report import build_text_report, save_results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze a GitHub repository and output a quality score (0-100).\n"
                    "Optionally verify technical claims from a paper against the code."
    )
    parser.add_argument("--repo", required=True, help="GitHub repository URL")
    parser.add_argument("--token", default=None, help="GitHub token (or GITHUB_TOKEN env var)")
    parser.add_argument("--openrouter-key", default=None, dest="openrouter_key",
                        help="OpenRouter API key (or OPENROUTER_KEY env var)")
    parser.add_argument("--model", default=None, help="OpenRouter model ID")
    parser.add_argument(
        "--paper-sections", default=None, dest="paper_sections", metavar="FILE",
        help="Path to sections JSON produced by parse_pdf_with_marker.py "
             "(enables claim extraction and verification).",
    )
    parser.add_argument(
        "--claims-json", default=None, dest="claims_json", metavar="FILE",
        help="Path to pre-extracted claims JSON (e.g. from claim_extraction_mvp.py). "
             "Skips PDF parsing and claim extraction, goes straight to verification.",
    )
    parser.add_argument("--output-dir", default="./results", dest="output_dir",
                        help="Directory to save results (default: ./results)")
    parser.add_argument("--json-only", action="store_true", dest="json_only",
                        help="Print JSON only, skip human-readable text")
    args = parser.parse_args()

    openrouter_key = args.openrouter_key or os.environ.get("OPENROUTER_KEY", "")
    if not openrouter_key:
        print("Error: OpenRouter API key required. Use --openrouter-key or set OPENROUTER_KEY.", file=sys.stderr)
        sys.exit(1)

    config = Config(
        repo_url=args.repo,
        openrouter_key=openrouter_key,
        github_token=args.token or os.environ.get("GITHUB_TOKEN"),
        model=args.model or os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
    )

    paper_sections = None
    pre_extracted_claims = None

    if args.claims_json:
        data = json.loads(Path(args.claims_json).read_text(encoding="utf-8"))
        if isinstance(data, dict) and "result" in data:
            pre_extracted_claims = data["result"]
        elif isinstance(data, list):
            pre_extracted_claims = data
        else:
            print("Error: unrecognised claims JSON format.", file=sys.stderr)
            sys.exit(1)
    elif args.paper_sections:
        paper_sections = json.loads(Path(args.paper_sections).read_text(encoding="utf-8"))

    try:
        report = analyze_full(config, paper_sections=paper_sections, pre_extracted_claims=pre_extracted_claims)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    json_path, txt_path = save_results(report, args.output_dir)
    print(f"Saved: {json_path}", file=sys.stderr)
    print(f"       {txt_path}", file=sys.stderr)

    if not args.json_only:
        print("\n" + build_text_report(report) + "\n")

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()