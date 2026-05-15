from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    repo_url: str
    openrouter_key: str
    github_token: Optional[str] = None
    model: str = "openai/gpt-4o-mini"