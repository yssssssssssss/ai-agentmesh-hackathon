from __future__ import annotations

import io
import stat
import zipfile

import pytest

from agentmesh.harness.skill_packages import SkillPackageError, SkillPackageService
from agentmesh.skill_runtime.service import SkillCatalogService
from agentmesh.store import SQLiteStore


def _archive(name: str = "packaged-skill", version: str = "1") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            f"{name}/SKILL.md",
            f"---\nname: {name}\ndescription: Packaged test skill for catalog import.\nmetadata:\n  version: \"{version}\"\n---\n\n# Packaged Skill\n\nDo the task.\n",
        )
        archive.writestr(f"{name}/references/guide.md", "# Guide")
    return buffer.getvalue()


def test_package_is_quarantined_until_activation_and_can_roll_back(tmp_path) -> None:
    repository = SQLiteStore(tmp_path / "packages.sqlite3")
    service = SkillPackageService(repository, tmp_path / "packages")
    first = service.import_zip(_archive(version="1"), file_name="skill-v1.zip", created_by="admin")
    second = service.import_zip(_archive(version="2"), file_name="skill-v2.zip", created_by="admin")

    assert first.status == "quarantined"
    catalog = SkillCatalogService(repository)
    assert catalog.get_by_name("packaged-skill") is None

    service.activate(first.id)
    catalog.reload()
    assert catalog.get_by_name("packaged-skill") is not None

    service.activate(second.id)
    assert repository.get_skill_package(first.id).status == "disabled"  # type: ignore[union-attr]
    assert repository.get_skill_package(second.id).status == "active"  # type: ignore[union-attr]

    service.activate(first.id)
    assert repository.get_skill_package(first.id).status == "active"  # type: ignore[union-attr]
    assert repository.get_skill_package(second.id).status == "disabled"  # type: ignore[union-attr]


def test_package_rejects_path_traversal(tmp_path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../escape/SKILL.md", "---\nname: escape\ndescription: Escape.\n---\n")
    service = SkillPackageService(SQLiteStore(tmp_path / "packages.sqlite3"), tmp_path / "packages")

    with pytest.raises(SkillPackageError, match="unsafe path"):
        service.import_zip(buffer.getvalue(), file_name="escape.zip", created_by="admin")


def test_package_rejects_symlink_entries(tmp_path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("linked-skill/SKILL.md")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "../../outside")
    service = SkillPackageService(SQLiteStore(tmp_path / "packages.sqlite3"), tmp_path / "packages")

    with pytest.raises(SkillPackageError, match="symlinks"):
        service.import_zip(buffer.getvalue(), file_name="link.zip", created_by="admin")
