from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zipfile import ZipFile

import psutil
import pytest

import agentmesh.document_parser_process as process_module
import agentmesh.ingestion as ingestion_module
from agentmesh.document_parser_process import IsolatedDocumentParser
from agentmesh.documents import DocumentParseError, PlainTextDocumentParser, UnsupportedDocumentTypeError
from agentmesh.ingestion import DocumentIngestionService
from agentmesh.store import SQLiteStore
from tests.test_document_input_recovery import seed_owner
from tests.test_document_staging import request


def capture_processes(monkeypatch, command=None):
    processes = []
    start = subprocess.Popen

    def launch(args, **kwargs):
        process = start(command or args, **kwargs)
        processes.append((process, args, kwargs))
        return process

    monkeypatch.setattr(process_module.subprocess, 'Popen', launch)
    return processes


@pytest.mark.parametrize('kind', ['text', 'word', 'slide', 'pdf', 'image_adapter'])
def test_real_isolated_parser_preserves_supported_formats_and_private_process(tmp_path, monkeypatch, kind):
    value = request()
    if kind in {'word', 'slide'}:
        buffer = io.BytesIO()
        path = 'word/document.xml' if kind == 'word' else 'ppt/slides/slide1.xml'
        with ZipFile(buffer, 'w') as archive:
            archive.writestr(path, '<root xmlns:w="http://example.test"><w:t>Bounded project evidence</w:t></root>')
        value = value.model_copy(update={'content': buffer.getvalue(),
            'file_name': 'evidence.docx' if kind == 'word' else 'evidence.pptx',
            'content_type': 'application/octet-stream'})
    elif kind == 'pdf':
        import fitz
        with fitz.open() as document:
            document.new_page().insert_text((30, 50), 'Bounded project evidence')
            value = value.model_copy(update={'content': document.tobytes(), 'file_name': 'evidence.pdf',
                                           'content_type': 'application/pdf'})
    elif kind == 'image_adapter':
        command = tmp_path / 'test-ocr'
        command.write_text(f'#!{sys.executable} -I\nimport os\n'
            'assert "AI_API_KEY" not in os.environ and "PYTHONPATH" not in os.environ\n'
            'assert os.environ["TESSDATA_PREFIX"] == "controlled-test-language-path"\n'
            'print("Bounded project evidence")\n')
        command.chmod(0o700)
        monkeypatch.setenv('AGENTMESH_TESSERACT_COMMAND', str(command))
        monkeypatch.setenv('TESSDATA_PREFIX', 'controlled-test-language-path')
        value = value.model_copy(update={'content': b'controlled adapter input', 'file_name': 'evidence.png',
                                       'content_type': 'image/png'})
    processes = capture_processes(monkeypatch)
    monkeypatch.setenv('AI_API_KEY', 'must-not-enter-parser')
    monkeypatch.setenv('PYTHONPATH', '/untrusted-import-path')
    parsed = IsolatedDocumentParser().parse(value)
    assert ('冻结的原始资料' if kind == 'text' else 'Bounded project evidence') in parsed.text
    assert (parsed.workspace_id, parsed.project_id, parsed.uploaded_by) == (
        value.workspace_id, value.project_id, value.uploaded_by)
    process, command, options = processes[0]
    assert process.pid != os.getpid() and process.returncode == 0
    assert command[1:3] == ['-I', '-m'] and options['start_new_session']
    assert 'AI_API_KEY' not in options['env'] and 'PYTHONPATH' not in options['env']
    assert not Path(options['cwd']).exists()


@pytest.mark.parametrize('stop', ['timeout', 'cancel', 'memory'])
def test_bounded_parser_kills_and_reaps_actual_process(monkeypatch, stop):
    started = threading.Event()
    processes = capture_processes(monkeypatch, [sys.executable, '-I', '-c', 'import time; time.sleep(60)'])
    original_rss = process_module._resident_bytes

    def resident(process):
        started.set()
        return 513 * 1024 * 1024 if stop == 'memory' else original_rss(process)

    monkeypatch.setattr(process_module, '_resident_bytes', resident)
    cancelled = threading.Event()
    parser = IsolatedDocumentParser(timeout_seconds=0.5 if stop == 'timeout' else 10)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(parser.parse, request(), cancelled=cancelled.is_set)
        assert started.wait(5)
        if stop == 'cancel':
            cancelled.set()
        with pytest.raises(DocumentParseError, match={'timeout': 'document_parser_timeout',
            'cancel': 'document_parser_cancelled', 'memory': 'document_parser_memory_exceeded'}[stop]):
            future.result(5)
    process = processes[0][0]
    assert process.returncode is not None and not psutil.pid_exists(process.pid)
    assert not Path(processes[0][2]['cwd']).exists()


def test_service_shutdown_cancels_running_production_parser_and_keeps_retryable_input(tmp_path, monkeypatch):
    repository = SQLiteStore(tmp_path / 'shutdown.sqlite3')
    seed_owner(repository)
    processes = capture_processes(monkeypatch, [sys.executable, '-I', '-c', 'import time; time.sleep(60)'])
    started = threading.Event()
    original_rss = process_module._resident_bytes

    def resident(process):
        started.set()
        return original_rss(process)

    monkeypatch.setattr(process_module, '_resident_bytes', resident)
    service = DocumentIngestionService(repository, IsolatedDocumentParser())
    job = service.create_job(request())
    future = service.submit(job.id)
    assert started.wait(5)
    service.shutdown()
    failed = future.result(5)
    assert failed.status == 'failed' and failed.error == 'document_parser_cancelled'
    assert repository.documents == repository.sources == repository.user_memory_items == []
    assert (service.staging.root / job.input_staging_ref).exists()
    assert not psutil.pid_exists(processes[0][0].pid)
    service.shutdown()


@pytest.mark.parametrize('kind,code', [('binary', 'document_type_unsupported'),
    ('encoding', 'document_text_encoding_invalid'), ('text_limit', 'document_parsed_text_too_large'),
    ('zip_limit', 'document_archive_limit_exceeded'), ('xml_entities', 'document_archive_xml_unsafe'),
    ('xml_entities_utf16', 'document_archive_xml_unsafe')])
def test_real_worker_returns_static_errors_without_input_or_exception_bodies(kind, code):
    value = request()
    if kind == 'binary':
        value = value.model_copy(update={'file_name': 'input.bin', 'content_type': 'application/octet-stream'})
    elif kind == 'encoding':
        value = value.model_copy(update={'content': b'private body\xff'})
    elif kind == 'text_limit':
        value = value.model_copy(update={'content': b'private body' * 100000})
    else:
        buffer = io.BytesIO()
        with ZipFile(buffer, 'w') as archive:
            body = ('<root>' + 'private body' * 400000 + '</root>' if kind == 'zip_limit'
                    else '<!DOCTYPE root [<!ENTITY secret "private body">]><root>&secret;</root>')
            archive.writestr('word/document.xml', body.encode('utf-16') if kind == 'xml_entities_utf16' else body)
        value = value.model_copy(update={'file_name': 'input.docx', 'content_type': 'application/octet-stream',
                                        'content': buffer.getvalue()})
    with pytest.raises(UnsupportedDocumentTypeError if kind == 'binary' else DocumentParseError) as caught:
        IsolatedDocumentParser().parse(value)
    assert str(caught.value) == code


def test_actual_memory_allocation_is_stopped_by_resident_memory_monitor(monkeypatch):
    monkeypatch.setattr(process_module, 'MAX_MEMORY_BYTES', 32 * 1024 * 1024)
    processes = capture_processes(monkeypatch, [sys.executable, '-I', '-c',
        'import time; allocation = bytearray(b"x" * (96 * 1024 * 1024)); time.sleep(60)'])
    with pytest.raises(DocumentParseError, match='document_parser_memory_exceeded'):
        IsolatedDocumentParser(timeout_seconds=5).parse(request())
    assert not psutil.pid_exists(processes[0][0].pid)


def test_cancel_kills_actual_ocr_like_descendant_in_owned_process_group(monkeypatch):
    processes = capture_processes(monkeypatch, [sys.executable, '-I', '-c',
        'import subprocess,sys,time; child = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(60)"]); child.wait()'])
    started, cancelled = threading.Event(), threading.Event()
    children = []
    original_rss = process_module._resident_bytes

    def resident(process):
        children[:] = psutil.Process(process.pid).children()
        if children:
            started.set()
        return original_rss(process)

    monkeypatch.setattr(process_module, '_resident_bytes', resident)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(IsolatedDocumentParser().parse, request(), cancelled=cancelled.is_set)
        assert started.wait(5)
        cancelled.set()
        with pytest.raises(DocumentParseError, match='document_parser_cancelled'):
            future.result(5)
    assert not psutil.pid_exists(processes[0][0].pid)
    for child in children:
        try:
            child.wait(timeout=5)
        except psutil.TimeoutExpired:
            assert child.status() == psutil.STATUS_ZOMBIE


def test_revoked_owner_interrupts_process_on_claim_renewal_and_commits_nothing(tmp_path, monkeypatch):
    repository = SQLiteStore(tmp_path / 'revoked-process.sqlite3')
    owner = seed_owner(repository)
    processes = capture_processes(monkeypatch, [sys.executable, '-I', '-c', 'import time; time.sleep(60)'])
    started = threading.Event()
    original_rss = process_module._resident_bytes

    def resident(process):
        started.set()
        return original_rss(process)

    monkeypatch.setattr(process_module, '_resident_bytes', resident)
    monkeypatch.setattr(ingestion_module, '_CLAIM_HEARTBEAT_SECONDS', 0.05)
    service = DocumentIngestionService(repository, IsolatedDocumentParser())
    try:
        job = service.create_job(request())
        future = service.submit(job.id)
        assert started.wait(5)
        repository.save_user(owner.model_copy(update={'status': 'disabled'}))
        failed = future.result(5)
        assert failed.status == 'failed' and failed.error == 'document_parser_cancelled'
        assert not psutil.pid_exists(processes[0][0].pid)
        assert repository.documents == repository.sources == repository.user_memory_items == []
    finally:
        service.shutdown()


@pytest.mark.parametrize('kind,code', [('malformed', 'document_parser_output_invalid'),
    ('unknown_error', 'document_parser_output_invalid'), ('output_limit', 'document_parser_output_too_large'),
    ('owner', 'document_parser_owner_mismatch'), ('symlink', 'document_parser_output_invalid'),
    ('crash', 'document_parser_worker_failed')])
def test_untrusted_worker_response_is_bounded_and_cannot_change_owner(monkeypatch, kind, code):
    value = request()
    payload = {'result': PlainTextDocumentParser().parse(value).model_dump(mode='json')}
    if kind == 'owner':
        payload['result']['uploaded_by'] = 'foreign'
    if kind == 'unknown_error':
        payload = {'error': 'private native error body'}
    output = json.dumps(payload)
    if kind == 'malformed':
        output = 'private native output'
    script = f'from pathlib import Path; Path("output.json").write_text({output!r})'
    if kind == 'output_limit':
        script = 'from pathlib import Path; Path("output.json").write_bytes(b"x" * (2*1024*1024+1))'
    elif kind == 'symlink':
        script = 'from pathlib import Path; Path("output.json").symlink_to("input.bin")'
    elif kind == 'crash':
        script = 'import os,signal; os.kill(os.getpid(), signal.SIGKILL)'
    processes = capture_processes(monkeypatch, [sys.executable, '-I', '-c', script])
    with pytest.raises(DocumentParseError) as caught:
        IsolatedDocumentParser().parse(value)
    assert str(caught.value) == code and not psutil.pid_exists(processes[0][0].pid)


def test_lost_process_claim_cannot_overwrite_replacement_completed_import(tmp_path, monkeypatch):
    from datetime import timedelta

    from agentmesh.models import now_utc

    repository = SQLiteStore(tmp_path / 'replaced-process.sqlite3')
    seed_owner(repository)
    processes = capture_processes(monkeypatch, [sys.executable, '-I', '-c', 'import time; time.sleep(60)'])
    started = threading.Event()
    original_rss = process_module._resident_bytes

    def resident(process):
        started.set()
        return original_rss(process)

    monkeypatch.setattr(process_module, '_resident_bytes', resident)
    monkeypatch.setattr(ingestion_module, '_CLAIM_HEARTBEAT_SECONDS', 0.05)
    old = DocumentIngestionService(repository, IsolatedDocumentParser())
    replacement_repository = SQLiteStore(repository.db_path)
    replacement = DocumentIngestionService(replacement_repository, PlainTextDocumentParser())
    try:
        job = old.create_job(request())
        future = old.submit(job.id)
        assert started.wait(5)
        claimed = repository.get_document_parse_job(job.id)
        repository.save_document_parse_job(claimed.model_copy(update={
            'lease_expires_at': now_utc() - timedelta(seconds=1)}))
        completed = replacement.run_job(job.id)
        assert completed.status == 'completed' and completed.attempt_count == 2
        late = future.result(5)
        assert late.status == 'completed' and late.document_id == completed.document_id
        assert not psutil.pid_exists(processes[0][0].pid)
        assert len(repository.documents) == len(repository.sources) == 1
    finally:
        old.shutdown()
        replacement.shutdown()
        replacement_repository.close()
