import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Config:
    repo_url: str
    openrouter_key: str
    github_token: Optional[str] = None
    model: str = "openai/gpt-4o-mini"
    thesis_text: Optional[str] = None
    output_dir: str = field(default_factory=lambda: os.path.join(os.path.dirname(__file__), "results"))


def load_config(args) -> Config:
    openrouter_key = getattr(args, "openrouter_key", None) or os.environ.get("OPENROUTER_KEY", "")
    if not openrouter_key:
        raise ValueError("OpenRouter API key is required. Set OPENROUTER_KEY env var or use --openrouter-key.")

    github_token = getattr(args, "token", None) or os.environ.get("GITHUB_TOKEN")

    model = (
        getattr(args, "model", None)
        or os.environ.get("OPENROUTER_MODEL")
        or "openai/gpt-4o-mini"
    )

    thesis_text = None
    thesis_path = getattr(args, "thesis", None)
    if thesis_path:
        with open(thesis_path, encoding="utf-8") as f:
            thesis_text = f.read()

    output_dir = (
        getattr(args, "output_dir", None)
        or os.path.join(os.path.dirname(__file__), "results")
    )

    return Config(
        repo_url=args.repo,
        openrouter_key=openrouter_key,
        github_token=github_token,
        model=model,
        thesis_text=thesis_text,
        output_dir=output_dir,
    )
