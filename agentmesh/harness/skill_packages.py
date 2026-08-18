from __future__ import annotations

import hashlib
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath

from agentmesh.models import SkillPackage, SkillPackageStatus, SkillSourceScope, now_utc
from agentmesh.skill_runtime.discovery import SkillRoot, discover_skills
from agentmesh.store import SQLiteStore

_MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
_MAX_FILE_BYTES = 5 * 1024 * 1024
_MAX_FILES = 500


class SkillPackageError(ValueError):
    pass


class SkillPackageService:
    def __init__(self, repository: SQLiteStore, package_dir: Path):
        self.repository = repository
        self.package_dir = package_dir
        self.package_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
        members = archive.infolist()
        if len(members) > _MAX_FILES:
            raise SkillPackageError(f"Skill package exceeds {_MAX_FILES} files")
        total = 0
        for info in members:
            path = PurePosixPath(info.filename)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise SkillPackageError("Skill package contains an unsafe path")
            mode = (info.external_attr >> 16) & 0o170000
            if stat.S_ISLNK(mode):
                raise SkillPackageError("Skill package symlinks are not allowed")
            if info.file_size > _MAX_FILE_BYTES:
                raise SkillPackageError("Skill package contains an oversized file")
            total += info.file_size
            if total > _MAX_ARCHIVE_BYTES:
                raise SkillPackageError("Skill package expands beyond the size limit")
        return members

    def import_zip(self, archive_bytes: bytes, *, file_name: str, created_by: str) -> SkillPackage:
        if len(archive_bytes) > _MAX_ARCHIVE_BYTES:
            raise SkillPackageError("Skill package archive exceeds the size limit")
        digest = hashlib.sha256(archive_bytes).hexdigest()
        package_id = f"skill_package_{digest[:16]}"
        existing = self.repository.get_skill_package(package_id)
        if existing is not None:
            return existing
        archive_path = self.package_dir / f"{package_id}.zip"
        root = self.package_dir / package_id
        archive_path.write_bytes(archive_bytes)
        try:
            with zipfile.ZipFile(archive_path) as archive:
                members = self._members(archive)
                root.mkdir(parents=True, exist_ok=False)
                for info in members:
                    target = root.joinpath(*PurePosixPath(info.filename).parts)
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, target.open("wb") as destination:
                        shutil.copyfileobj(source, destination)
        except (zipfile.BadZipFile, OSError, SkillPackageError):
            shutil.rmtree(root, ignore_errors=True)
            archive_path.unlink(missing_ok=True)
            raise

        try:
            discovered = discover_skills([SkillRoot(root, SkillSourceScope.WORKSPACE)])
        except Exception as error:
            shutil.rmtree(root, ignore_errors=True)
            archive_path.unlink(missing_ok=True)
            raise SkillPackageError(f"Skill package validation failed: {type(error).__name__}") from error
        diagnostics = [
            {"level": item.level, "code": item.code, "message": item.message, "path": item.path}
            for item in discovered.diagnostics
        ]
        if not discovered.skills:
            shutil.rmtree(root, ignore_errors=True)
            archive_path.unlink(missing_ok=True)
            raise SkillPackageError("Skill package contains no valid SKILL.md")
        first = sorted(discovered.skills.values(), key=lambda item: item.name)[0]
        package = SkillPackage(
            id=package_id,
            name=first.name if len(discovered.skills) == 1 else Path(file_name).stem,
            version=first.version,
            source_uri=f"upload://{file_name}",
            content_hash=digest,
            root_path=str(root),
            resources=sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()),
            diagnostics=diagnostics,
            license=first.license,
            compatibility=first.compatibility,
            created_by=created_by,
        )
        return self.repository.save_skill_package(package)

    def activate(self, package_id: str) -> SkillPackage:
        package = self.repository.get_skill_package(package_id)
        if package is None:
            raise LookupError("Skill package not found")
        for existing in self.repository.skill_packages:
            if existing.id == package.id or existing.name != package.name or existing.status != SkillPackageStatus.ACTIVE:
                continue
            existing.status = SkillPackageStatus.DISABLED
            existing.updated_at = now_utc()
            self.repository.save_skill_package(existing)
        package.status = SkillPackageStatus.ACTIVE
        package.updated_at = now_utc()
        return self.repository.save_skill_package(package)

    def disable(self, package_id: str) -> SkillPackage:
        package = self.repository.get_skill_package(package_id)
        if package is None:
            raise LookupError("Skill package not found")
        package.status = SkillPackageStatus.DISABLED
        package.updated_at = now_utc()
        return self.repository.save_skill_package(package)
