import subprocess
import sys
from typing import Optional, Tuple

from github import Github, GithubException


def parse_repo_url(url: str) -> Tuple[str, str]:
    url = url.rstrip("/")
    if "github.com" in url:
        parts = url.split("github.com/", 1)[1].split("/")
        if len(parts) < 2:
            raise ValueError(f"Cannot parse owner/repo from URL: {url}")
        return parts[0], parts[1]
    raise ValueError(f"Not a GitHub URL: {url}")


def _get_repo(repo_url: str, token: Optional[str]):
    owner, repo_name = parse_repo_url(repo_url)
    g = Github(token) if token else Github()
    try:
        return g.get_repo(f"{owner}/{repo_name}")
    except GithubException as e:
        raise ValueError(f"Could not access repository {owner}/{repo_name}: {e}") from e


def get_tree(repo_url: str, token: Optional[str]) -> Tuple[list, list]:
    """
    Returns (flat_paths, all_paths):
      - flat_paths: list of file paths (blobs only)
      - all_paths:  list of all paths (blobs + trees/dirs)
    """
    repo = _get_repo(repo_url, token)
    branch = repo.default_branch
    print(f"Default branch: {branch}", file=sys.stderr)

    try:
        tree = repo.get_git_tree(branch, recursive=True)
    except GithubException as e:
        raise ValueError(f"Could not fetch repository tree: {e}") from e

    if tree.raw_data.get("truncated"):
        print(
            "WARNING: repository tree is truncated (too many files). "
            "Some checks may be incomplete.",
            file=sys.stderr,
        )

    flat_paths = [item.path for item in tree.tree if item.type == "blob"]
    all_paths = [item.path for item in tree.tree]
    return flat_paths, all_paths


def get_file_content(repo_url: str, path: str, token: Optional[str]) -> str:
    """Fetch decoded text content of a single file from the repo."""
    repo = _get_repo(repo_url, token)
    try:
        contents = repo.get_contents(path)
        return contents.decoded_content.decode("utf-8", errors="replace")
    except GithubException as e:
        raise ValueError(f"Could not fetch file {path}: {e}") from e


def get_commit_count(repo_url: str, token: Optional[str], threshold: int = 5) -> int:
    """Return commit count, stopping iteration once threshold+1 is reached."""
    repo = _get_repo(repo_url, token)
    count = 0
    for _ in repo.get_commits():
        count += 1
        if count > threshold:
            break
    return count


def clone_repo(repo_url: str, token: Optional[str], target_dir: str) -> None:
    """Shallow-clone repo into target_dir (depth=1)."""
    if token and "github.com" in repo_url:
        clone_url = repo_url.replace("https://github.com/", f"https://{token}@github.com/")
    else:
        clone_url = repo_url
    subprocess.run(
        ["git", "clone", "--depth", "1", "--quiet", clone_url, target_dir],
        check=True, capture_output=True, timeout=120,
    )
