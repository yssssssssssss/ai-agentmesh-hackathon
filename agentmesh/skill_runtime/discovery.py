from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agentmesh.models import SkillDefinition, SkillSourceScope
from agentmesh.skill_runtime.parser import SkillDiagnostic, parse_skill_file


@dataclass(frozen=True, slots=True)
class SkillRoot:
    path: Path
    scope: SkillSourceScope


@dataclass(slots=True)
class SkillDiscoveryResult:
    skills: dict[str, SkillDefinition] = field(default_factory=dict)
    diagnostics: list[SkillDiagnostic] = field(default_factory=list)
    scanned_directories: int = 0


def _diagnostic(path: Path, level: str, code: str, message: str) -> SkillDiagnostic:
    return SkillDiagnostic(level=level, code=code, message=message, path=str(path))  # type: ignore[arg-type]


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _skill_files(
    root: Path,
    diagnostics: list[SkillDiagnostic],
    *,
    max_depth: int,
    max_directories: int,
) -> tuple[list[Path], int]:
    try:
        canonical_root = root.resolve(strict=True)
    except OSError:
        diagnostics.append(_diagnostic(root, "warning", "skill_root_unavailable", "Skill root does not exist or is unreadable"))
        return [], 0
    if not canonical_root.is_dir():
        diagnostics.append(_diagnostic(root, "warning", "skill_root_not_directory", "Skill root is not a directory"))
        return [], 0

    files: list[Path] = []
    stack: list[tuple[Path, int]] = [(canonical_root, 0)]
    visited = 0
    while stack:
        directory, depth = stack.pop()
        visited += 1
        if visited > max_directories:
            diagnostics.append(
                _diagnostic(root, "error", "skill_scan_limit", f"Skill scan exceeded {max_directories} directories")
            )
            break
        skill_file = directory / "SKILL.md"
        if skill_file.is_file():
            files.append(skill_file)
        if depth >= max_depth:
            continue
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError as error:
            diagnostics.append(
                _diagnostic(directory, "warning", "skill_directory_unreadable", f"Could not scan directory: {type(error).__name__}")
            )
            continue
        for child in reversed(children):
            if child.name in {".git", "node_modules", "__pycache__"}:
                continue
            if child.is_symlink():
                try:
                    target = child.resolve(strict=True)
                except OSError:
                    diagnostics.append(_diagnostic(child, "warning", "skill_symlink_broken", "Broken Skill symlink skipped"))
                    continue
                if not _within(target, canonical_root):
                    diagnostics.append(
                        _diagnostic(child, "warning", "skill_symlink_escape", "Skill symlink points outside its trusted root")
                    )
                else:
                    diagnostics.append(_diagnostic(child, "warning", "skill_symlink_skipped", "Skill symlink skipped"))
                continue
            if child.is_dir():
                stack.append((child, depth + 1))
    return files, visited


def discover_skills(
    roots: list[SkillRoot],
    *,
    max_depth: int = 6,
    max_directories: int = 2000,
) -> SkillDiscoveryResult:
    """Discover Skills in precedence order; the first definition for a name wins."""
    result = SkillDiscoveryResult()
    remaining = max_directories
    for root in roots:
        if remaining <= 0:
            result.diagnostics.append(
                _diagnostic(root.path, "error", "skill_scan_limit", f"Skill scan exceeded {max_directories} directories")
            )
            break
        files, scanned = _skill_files(
            root.path,
            result.diagnostics,
            max_depth=max_depth,
            max_directories=remaining,
        )
        result.scanned_directories += scanned
        remaining -= scanned
        for file_path in sorted(files):
            parsed = parse_skill_file(file_path, source_scope=root.scope)
            result.diagnostics.extend(parsed.diagnostics)
            if parsed.skill is None:
                continue
            existing = result.skills.get(parsed.skill.name)
            if existing is not None:
                result.diagnostics.append(
                    _diagnostic(
                        file_path,
                        "warning",
                        "skill_name_collision",
                        f"Skill '{parsed.skill.name}' is shadowed by {existing.source_path}",
                    )
                )
                continue
            result.skills[parsed.skill.name] = parsed.skill
    return result
