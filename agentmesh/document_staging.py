"""Private parser input cache. Job authority and recovery are owned by ingestion.

References are opaque and bound to a Job identity/hash. This controlled storage
directory is not a sandbox for arbitrary filesystem operations.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Callable
from contextlib import contextmanager, suppress
from pathlib import Path
from uuid import uuid4

from agentmesh.canonical_json import canonical_json_sha256
from agentmesh.documents import DocumentIngestionRequest
from agentmesh.models import DocumentParseJob

_MAX_INPUT_BYTES = 20 * 1024 * 1024
_REFERENCE = re.compile(r'input_[0-9a-f]{64}\.bin')
_TEMPORARY = re.compile(r'\.stage-[0-9a-f]{32}\.tmp')


class DocumentStagingError(RuntimeError):
    """Static codes only; parser input bytes never enter errors."""


def _reference(job: DocumentParseJob, content_hash: str) -> str:
    identity = {key: getattr(job, key) for key in (
        'id', 'workspace_id', 'project_id', 'uploaded_by', 'file_name', 'content_type',
    )}
    identity['content_hash'] = content_hash
    return f'input_{canonical_json_sha256(identity)}.bin'


class DocumentInputStaging:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    @contextmanager
    def _directory(self):
        try:
            descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError:
            raise DocumentStagingError('document_input_reference_invalid') from None
        try:
            try:
                if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o700:
                    os.fchmod(descriptor, 0o700)
            except OSError:
                raise DocumentStagingError('document_input_reference_invalid') from None
            yield descriptor
        finally:
            os.close(descriptor)

    @staticmethod
    def _checked_reference(job: DocumentParseJob) -> str:
        if (job.input_contract != 'document-input-v1' or not job.input_hash or not job.input_staging_ref
            or job.input_size_bytes is None or not 0 <= job.input_size_bytes <= _MAX_INPUT_BYTES):
            raise DocumentStagingError('document_input_unavailable')
        reference = job.input_staging_ref
        if not _REFERENCE.fullmatch(reference) or reference != _reference(job, job.input_hash):
            raise DocumentStagingError('document_input_reference_invalid')
        return reference

    def save(self, job: DocumentParseJob, request: DocumentIngestionRequest) -> DocumentParseJob:
        fields = ('workspace_id', 'project_id', 'uploaded_by', 'file_name', 'content_type')
        if any(getattr(job, key) != getattr(request, key) for key in fields):
            raise DocumentStagingError('document_input_owner_mismatch')
        if len(request.content) > _MAX_INPUT_BYTES:
            raise DocumentStagingError('document_input_too_large')
        digest = hashlib.sha256(request.content).hexdigest()
        reference = _reference(job, digest)
        staged = job.model_copy(update={'input_contract': 'document-input-v1', 'input_staging_ref': reference,
                                       'input_hash': digest, 'input_size_bytes': len(request.content)})
        if job.input_staging_ref:
            if job.input_staging_ref != reference or job.input_hash != digest:
                raise DocumentStagingError('document_input_identity_conflict')
            self.load(job)
            return staged
        temporary = f'.stage-{uuid4().hex}.tmp'
        with self._directory() as directory:
            try:
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                     0o600, dir_fd=directory)
                with os.fdopen(descriptor, 'wb') as stream:
                    stream.write(request.content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, reference, src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            except OSError:
                raise DocumentStagingError('document_input_write_failed') from None
            finally:
                with suppress(OSError):  # Interrupted temporary writes are swept after retention.
                    os.unlink(temporary, dir_fd=directory)
        return staged

    def load(self, job: DocumentParseJob) -> DocumentIngestionRequest:
        reference = self._checked_reference(job)
        with self._directory() as directory:
            try:
                descriptor = os.open(reference, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            except FileNotFoundError:
                raise DocumentStagingError('document_input_unavailable') from None
            except OSError:
                raise DocumentStagingError('document_input_reference_invalid') from None
            with os.fdopen(descriptor, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise DocumentStagingError('document_input_reference_invalid')
                if info.st_size != job.input_size_bytes or info.st_size > _MAX_INPUT_BYTES:
                    raise DocumentStagingError('document_input_integrity_failed')
                content = stream.read(_MAX_INPUT_BYTES + 1)
        if len(content) != job.input_size_bytes or hashlib.sha256(content).hexdigest() != job.input_hash:
            raise DocumentStagingError('document_input_integrity_failed')
        return DocumentIngestionRequest(**{key: getattr(job, key) for key in (
            'workspace_id', 'project_id', 'uploaded_by', 'file_name', 'content_type',
        )}, content=content)

    def delete(self, job: DocumentParseJob) -> None:
        reference = self._checked_reference(job)
        with self._directory() as directory:
            try:
                os.unlink(reference, dir_fd=directory)
                os.fsync(directory)
            except FileNotFoundError:
                pass
            except OSError:
                raise DocumentStagingError('document_input_delete_failed') from None

    def sweep_orphans(self, is_registered: Callable[[str], bool], *, older_than: float, limit: int = 100) -> int:
        """Bound both metadata scanning and deletions inside this private directory."""
        if not 1 <= limit <= 100:
            raise ValueError('document_input_cleanup_limit_invalid')
        removed = 0
        with self._directory() as directory, os.scandir(directory) as entries:
            for scanned, entry in enumerate(entries):
                if scanned >= 10 * limit or removed >= limit:
                    break
                if not (_REFERENCE.fullmatch(entry.name) or _TEMPORARY.fullmatch(entry.name)):
                    continue
                try:
                    info = entry.stat(follow_symlinks=False)
                    if info.st_mtime >= older_than or not (stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)):
                        continue
                    if is_registered(entry.name):
                        continue
                    os.unlink(entry.name, dir_fd=directory)
                    removed += 1
                except FileNotFoundError:
                    continue
                except OSError:
                    raise DocumentStagingError('document_input_delete_failed') from None
            if removed:
                try:
                    os.fsync(directory)
                except OSError:
                    raise DocumentStagingError('document_input_delete_failed') from None
        return removed
