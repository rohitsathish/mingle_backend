# %%
"""
Convert the current working directory into a Markdown file.
The script builds a tree structure and compiles file contents,
skipping files and directories based on .gitignore and custom exclusion lists.
"""

from pathlib import Path
from datetime import datetime
import pathspec
import json
from typing import Optional, Set, List, Dict, Any
from genson import SchemaBuilder

# ------------------------------
# Configuration: Exclusions and Inclusions
# ------------------------------
# List of files to exclusively include (if non-empty, only these files will be processed)
ONLY_FILENAMES: List[str] = []
# List of file paths (relative to base_dir, using forward slashes) to always include (overrides .gitignore and custom exclusions)
INCLUDE_FILENAMES: List[str] = [
    "llm_system_prompts/project_prompt.md",
    "messages/messages_20250205_1843.json",
]

# List of file names to exclude (exact match)
EXCLUDE_FILENAMES: List[str] = ["compiled.md", "mingle_backend.md"]

# List of file extensions to exclude (lowercase, include the dot)
EXCLUDE_EXTENSIONS: Set[str] = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".exe",
    ".dll",
    ".so",
    ".DS_Store",
}

# List of directories to exclude (case-sensitive substring match)
EXCLUDE_DIRECTORIES: List[str] = [
    "node_modules",
    "__pycache__",
    ".git",
    ".env",
    "venv",
    "env",
    ".vscode",
    ".idea",
    "markdowner",
]

# ------------------------------
# Helper Functions
# ------------------------------


def get_base_dir() -> Path:
    """
    Returns the base directory.
    In script mode, returns parent of script location.
    In interactive mode, returns current working directory.
    """
    try:
        return Path(__file__).parent.parent  # Go up one level from markdowner directory
    except NameError:  # We're in interactive mode
        return Path.cwd()


def load_gitignore(base_dir: Path) -> Optional[pathspec.PathSpec]:
    """Load and parse the .gitignore file from base_dir if it exists."""
    gitignore_path = base_dir / ".gitignore"
    if not gitignore_path.exists():
        return None
    with open(gitignore_path, "r", encoding="utf-8") as f:
        patterns = [
            line.strip() for line in f if line.strip() and not line.startswith("#")
        ]
    return pathspec.PathSpec.from_lines("gitwildmatch", patterns)


def should_exclude(
    path: Path, base_dir: Path, gitignore_spec: Optional[pathspec.PathSpec]
) -> bool:
    """Determine if a path should be excluded based on .gitignore and custom lists.

    Priority:
    1. If ONLY_FILENAMES is not empty, include only those files
    2. Otherwise, check INCLUDE_FILENAMES for overrides
    3. Finally, apply standard exclusion rules
    """
    try:
        relative_path = path.relative_to(base_dir).as_posix()

        # Priority 1: Check ONLY_FILENAMES
        if ONLY_FILENAMES:
            if path.is_file():
                return relative_path not in ONLY_FILENAMES
            # For directories, check if any target file is under this directory
            return not any(
                only_file.startswith(relative_path + "/")
                for only_file in ONLY_FILENAMES
            )

        # Priority 2: Check INCLUDE_FILENAMES
        if relative_path in INCLUDE_FILENAMES:
            return False
    except ValueError:
        pass

    # Priority 3: Standard exclusion rules
    if path.is_file() and path.name in EXCLUDE_FILENAMES:
        return True

    if path.is_file() and path.suffix.lower() in EXCLUDE_EXTENSIONS:
        return True

    if any(ex_dir in part for part in path.parts for ex_dir in EXCLUDE_DIRECTORIES):
        return True

    if gitignore_spec and gitignore_spec.match_file(str(path)):
        return True

    return False


def count_file_lines(file_path: Path) -> int:
    """Count the number of lines in a file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def generate_tree_structure(
    base_dir: Path, gitignore_spec: Optional[pathspec.PathSpec]
) -> str:
    """Generate a tree-like structure of the project."""
    tree_lines = ["# Project Structure", "```"]

    def add_to_tree(path: Path, prefix: str = "", is_last: bool = True):
        if should_exclude(path, base_dir, gitignore_spec):
            return

        connector = "└── " if is_last else "├── "
        if path.is_file():
            line_count = count_file_lines(path)
            tree_lines.append(f"{prefix}{connector}{path.name} ({line_count} lines)")
        else:
            tree_lines.append(f"{prefix}{connector}{path.name}")

        if path.is_dir():
            children = sorted(
                [
                    child
                    for child in path.iterdir()
                    if (not child.name.startswith("."))
                    or (child.relative_to(base_dir).as_posix() in INCLUDE_FILENAMES)
                ]
            )
            visible_children = [
                child
                for child in children
                if not should_exclude(child, base_dir, gitignore_spec)
            ]
            for i, child in enumerate(visible_children):
                child_is_last = i == len(visible_children) - 1
                new_prefix = prefix + ("    " if is_last else "│   ")
                add_to_tree(child, new_prefix, child_is_last)

    add_to_tree(base_dir)
    tree_lines.append("```")
    return "\n".join(tree_lines)


def extract_json_schema(
    json_data: Dict[Any, Any], current_path: str = ""
) -> Dict[str, Any]:
    builder = SchemaBuilder()
    builder.add_object(json_data)
    return builder.to_schema()


def compile_markdown(dont_overwrite: bool = False) -> Path:
    """Compile project files into a Markdown document."""
    base_dir = get_base_dir()
    gitignore_spec = load_gitignore(base_dir)

    # Get base directory name
    base_dir_name = base_dir.name

    # Create output path in the same directory as the source
    if dont_overwrite:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = base_dir / f"{base_dir_name}_{timestamp}.md"
    else:
        output_file = base_dir / f"{base_dir_name}.md"

    content = []
    if not ONLY_FILENAMES:
        content.append(generate_tree_structure(base_dir, gitignore_spec))
        content.append("\n# File Contents\n")

    for path in sorted(base_dir.rglob("*")):
        if should_exclude(path, base_dir, gitignore_spec):
            continue

        if path.is_file():
            try:
                file_text = path.read_text(encoding="utf-8").strip()
                if not file_text:  # Skip empty files
                    continue

                relative_path = path.relative_to(base_dir)
                language = path.suffix[1:] if path.suffix else ""

                # Add clear file separator with metadata
                content.append(f"{'-'*5}\n\n")
                content.append(f"FILE: {relative_path}\n")

                # Add JSON schema if it's a JSON file
                if language == "json":
                    try:
                        json_data = json.loads(file_text)
                        schema = extract_json_schema(json_data)
                        content.append("SCHEMA:\n```json\n")
                        content.append(json.dumps(schema, indent=2))
                        content.append("\n```\n")
                        continue  # Skip adding the actual content for JSON files
                    except json.JSONDecodeError:
                        pass  # If JSON parsing fails, treat as normal file

                content.append("CONTENT:\n")
                content.append(f"```{language}\n{file_text}\n```\n")

            except Exception as e:
                print(f"Error processing {path}: {e}")

    with open(output_file, "w", encoding="utf-8") as f:
        if not ONLY_FILENAMES:
            header = f"# Project Files for {base_dir_name}\n\n"
            f.write(header)
        f.write("".join(content))

    return output_file


if __name__ == "__main__":
    try:
        output_file = compile_markdown(dont_overwrite=False)
        print(f"Successfully created Markdown compilation: \n {output_file}")
    except Exception as e:
        print(f"An error occurred: {e}")

# %%
