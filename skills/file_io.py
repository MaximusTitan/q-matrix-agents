"""
skills/file_io.py

Base file I/O operations. All other KB skills build on top of these.
No path logic lives here — this module is path-agnostic.
"""

import os


def file_exists(path: str) -> bool:
    """
    Check whether a file exists at the given path.

    Args:
        path: Absolute path to the file.

    Returns:
        True if the file exists, False otherwise.
    """
    return os.path.isfile(path)


def directory_exists(path: str) -> bool:
    """
    Check whether a directory exists at the given path.

    Args:
        path: Absolute path to the directory.

    Returns:
        True if the directory exists, False otherwise.
    """
    return os.path.isdir(path)


def create_directory(path: str) -> None:
    """
    Create a directory and all intermediate directories if they don't exist.
    Safe to call even if the directory already exists.

    Args:
        path: Absolute path to the directory to create.

    Raises:
        OSError: If the directory cannot be created.
    """
    os.makedirs(path, exist_ok=True)


def read_file(path: str) -> str:
    """
    Read a text file and return its contents as a string.
    Strips leading/trailing Obsidian YAML frontmatter if present.

    Args:
        path: Absolute path to the file.

    Returns:
        File contents as a string.

    Raises:
        FileNotFoundError: If the file does not exist.
        OSError: If the file cannot be read.
    """
    if not file_exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Strip Obsidian YAML frontmatter if present
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) == 3:
            content = parts[2].strip()

    return content


def write_file(path: str, content: str) -> None:
    """
    Write a string to a file, creating intermediate directories if needed.
    Overwrites the file if it already exists.

    Args:
        path:    Absolute path to the file.
        content: String content to write.

    Raises:
        OSError: If the file cannot be written.
    """
    create_directory(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def append_file(path: str, content: str) -> None:
    """
    Append a string to an existing file. Creates the file if it doesn't exist.

    Args:
        path:    Absolute path to the file.
        content: String content to append.

    Raises:
        OSError: If the file cannot be written.
    """
    create_directory(os.path.dirname(path))
    with open(path, "a", encoding="utf-8") as f:
        f.write(content)


def list_directory(path: str) -> list[str]:
    """
    List all files and directories at the given path (non-recursive).

    Args:
        path: Absolute path to the directory.

    Returns:
        List of entry names (not full paths).

    Raises:
        FileNotFoundError: If the directory does not exist.
    """
    if not directory_exists(path):
        raise FileNotFoundError(f"Directory not found: {path}")
    return os.listdir(path)
