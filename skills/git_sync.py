"""
skills/git_sync.py

Git sync operations for the KB repo.
Called by the orchestrator at the start (pull) and end (push) of every run.
The agents themselves never call this — only the orchestrator does.
"""

import os
import subprocess
from dotenv import load_dotenv

load_dotenv()
KB_ROOT = os.getenv("KB_ROOT")


def _run(cmd: list[str], cwd: str) -> str:
    """
    Run a shell command in a given directory.

    Returns:
        stdout as a string.

    Raises:
        RuntimeError: If the command exits with a non-zero code.
    """
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Git command failed: {' '.join(cmd)}\n"
            f"stderr: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def pull_kb() -> None:
    """
    Pull the latest state of the KB repo from remote.
    Called at the start of every orchestrator run.

    Raises:
        RuntimeError: If the pull fails (e.g. merge conflict, no remote).
    """
    print(f"[git_sync] Pulling latest KB from remote...")
    output = _run(["git", "pull", "--rebase"], cwd=KB_ROOT)
    print(f"[git_sync] Pull complete: {output or 'Already up to date.'}")


def push_kb(board: str, subject: str, grade: str, chapter: str) -> None:
    """
    Stage, commit, and push ONLY the paths this chapter's run could have touched.
    Called at the end of every orchestrator run after any writes.

    Deliberately scoped rather than `git add .` — a run for one chapter must never
    sweep up a concurrent run's changes to other chapters/grades into its commit.
    (`git add .` previously did exactly this: a single-chapter commit ended up
    bundling 455 files across 28 unrelated chapters from a concurrently-running
    batch.) `git commit` is scoped with the same pathspec so that even if another
    process's `git add` interleaves with this one, only this chapter's paths are
    committed here — anything else stays staged for that other process's own commit.

    Args:
        board, subject, grade, chapter: Used to construct the commit message and
                                        to scope which paths are staged/committed.

    Raises:
        RuntimeError: If the push fails.
    """
    paths = [
        os.path.join("textbooks", board, subject, grade, chapter),
        os.path.join("escalations", board, subject, grade, chapter),
        os.path.join("rulesets", board, subject, grade, "rules.md"),
    ]
    existing_paths = [p for p in paths if os.path.exists(os.path.join(KB_ROOT, p))]
    if not existing_paths:
        print("[git_sync] No KB changes to push.")
        return

    # Check if there's anything to commit, scoped to this chapter's own paths only.
    status = _run(["git", "status", "--porcelain", "--"] + existing_paths, cwd=KB_ROOT)
    if not status:
        print("[git_sync] No KB changes to push.")
        return

    commit_msg = f"agent run: {board}/{subject}/{grade}/{chapter}"

    print(f"[git_sync] Staging changes...")
    _run(["git", "add", "--"] + existing_paths, cwd=KB_ROOT)

    print(f"[git_sync] Committing: {commit_msg}")
    _run(["git", "commit", "-m", commit_msg, "--"] + existing_paths, cwd=KB_ROOT)

    print(f"[git_sync] Pushing to remote...")
    _run(["git", "push"], cwd=KB_ROOT)

    print(f"[git_sync] Push complete.")
