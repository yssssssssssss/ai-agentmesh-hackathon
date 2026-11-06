from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agentmesh.document_staging import DocumentInputStaging, DocumentStagingError
from agentmesh.documents import DocumentIngestionRequest
from agentmesh.models import DocumentParseJob


def request() -> DocumentIngestionRequest:
    return DocumentIngestionRequest(file_name='原始资料.md', content_type='text/markdown',
        content='# 本人上传\n冻结的原始资料。'.encode(), workspace_id='workspace', project_id='project', uploaded_by='owner')


def job() -> DocumentParseJob:
    value = request()
    return DocumentParseJob(file_name=value.file_name, content_type=value.content_type, workspace_id=value.workspace_id,
                            project_id=value.project_id, uploaded_by=value.uploaded_by)


def test_original_input_can_be_reopened_without_the_future_or_caller_bytes(tmp_path):
    original = job()
    storage = DocumentInputStaging(tmp_path / 'inputs')
    staged = storage.save(original, request())
    assert staged.input_hash == hashlib.sha256(request().content).hexdigest()
    assert staged.input_size_bytes == len(request().content)
    assert not Path(staged.input_staging_ref).is_absolute()
    loaded = DocumentInputStaging(tmp_path / 'inputs').load(staged)
    assert loaded == request()


def test_corrupted_bytes_are_rejected_before_any_parser_runs(tmp_path):
    storage = DocumentInputStaging(tmp_path / 'inputs')
    staged = storage.save(job(), request())
    path = tmp_path / 'inputs' / staged.input_staging_ref
    path.write_bytes(b'changed input')
    with pytest.raises(DocumentStagingError, match='document_input_integrity_failed'):
        storage.load(staged)


def test_request_identity_cannot_be_substituted_for_a_job(tmp_path):
    storage = DocumentInputStaging(tmp_path / 'inputs')
    with pytest.raises(DocumentStagingError, match='document_input_owner_mismatch'):
        storage.save(job(), request().model_copy(update={'uploaded_by': 'peer'}))
    assert not list((tmp_path / 'inputs').glob('*'))


def test_opaque_reference_cannot_escape_storage_or_follow_a_symlink(tmp_path):
    storage = DocumentInputStaging(tmp_path / 'inputs')
    staged = storage.save(job(), request())
    with pytest.raises(DocumentStagingError, match='document_input_reference_invalid'):
        storage.load(staged.model_copy(update={'input_staging_ref': '../outside'}))
    path = tmp_path / 'inputs' / staged.input_staging_ref
    path.unlink()
    outside = tmp_path / 'outside'
    outside.write_bytes(request().content)
    path.symlink_to(outside)
    with pytest.raises(DocumentStagingError, match='document_input_reference_invalid'):
        storage.load(staged)
    storage.delete(staged)
    assert outside.read_bytes() == request().content


def test_stage_files_are_private_and_cleanup_is_idempotent(tmp_path):
    import stat

    storage = DocumentInputStaging(tmp_path / 'inputs')
    staged = storage.save(job(), request())
    path = tmp_path / 'inputs' / staged.input_staging_ref
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert storage.save(staged, request()).input_staging_ref == staged.input_staging_ref
    storage.delete(staged)
    storage.delete(staged)
    assert not path.exists()


def test_old_orphan_cleanup_preserves_registered_inputs_and_unrelated_files(tmp_path):
    import os

    storage = DocumentInputStaging(tmp_path / 'inputs')
    live = storage.save(job(), request())
    orphan = storage.save(job().model_copy(update={'id': 'orphan-job'}), request())
    unrelated = storage.root / 'unrelated.txt'
    unrelated.write_text('keep')
    outside = tmp_path / 'outside-private-file'
    outside.write_text('outside stays')
    link = storage.root / f"input_{'d' * 64}.bin"
    link.symlink_to(outside)
    temporary = storage.root / f".stage-{'e' * 32}.tmp"
    temporary.write_text('interrupted write')
    for name in (live.input_staging_ref, orphan.input_staging_ref, unrelated.name, link.name, temporary.name):
        os.utime(storage.root / name, (1, 1), follow_symlinks=False)
    assert storage.sweep_orphans(lambda ref: ref == live.input_staging_ref, older_than=2, limit=1) == 1
    assert storage.sweep_orphans(lambda ref: ref == live.input_staging_ref, older_than=2, limit=10) == 2
    assert (storage.root / live.input_staging_ref).read_bytes() == request().content
    assert not (storage.root / orphan.input_staging_ref).exists()
    assert unrelated.read_text() == 'keep'
    assert outside.read_text() == 'outside stays' and not link.exists() and not temporary.exists()
