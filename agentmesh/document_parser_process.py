"""Owned POSIX parser process; resource containment, not a filesystem/network sandbox."""
from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from time import monotonic

import psutil

from agentmesh.documents import (
    DocumentIngestionRequest,
    DocumentParseError,
    ParsedDocument,
    UnsupportedDocumentTypeError,
    validate_parsed_limits,
)

MAX_INPUT_BYTES = 20 * 1024 * 1024
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_MEMORY_BYTES = 512 * 1024 * 1024
ERROR_CODES = frozenset({
    'document_type_unsupported', 'document_text_encoding_invalid', 'document_parsed_text_too_large',
    'document_parser_metadata_too_large', 'document_pdf_page_limit_exceeded', 'document_archive_limit_exceeded',
    'document_archive_xml_unsafe', 'document_parser_memory_exceeded', 'document_parser_failed',
    'document_parser_resource_limits_unavailable', 'document_parser_output_too_large',
})


def _resident_bytes(process: subprocess.Popen) -> int:
    try:
        root = psutil.Process(process.pid)
        children = root.children(recursive=True)
        if len(children) > 8:
            raise DocumentParseError('document_parser_process_limit_exceeded')
        total = 0
        for item in [root, *children]:
            with suppress(psutil.NoSuchProcess):
                total += item.memory_info().rss
        return total
    except psutil.NoSuchProcess:
        return 0
    except psutil.Error:
        raise DocumentParseError('document_parser_monitor_unavailable') from None


def _stop_process(process: subprocess.Popen) -> None:
    # Also kill surviving OCR children in this owned session after the worker exits.
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        raise DocumentParseError('document_parser_cleanup_failed') from None


def _read_output(directory: Path) -> ParsedDocument:
    try:
        descriptor = os.open(directory / 'output.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_OUTPUT_BYTES:
                raise DocumentParseError('document_parser_output_too_large')
            payload = json.loads(stream.read(MAX_OUTPUT_BYTES + 1))
        if not isinstance(payload, dict):
            raise ValueError
        if set(payload) == {'error'} and payload['error'] in ERROR_CODES:
            if payload['error'] == 'document_type_unsupported':
                raise UnsupportedDocumentTypeError('document_type_unsupported')
            raise DocumentParseError(payload['error'])
        if set(payload) != {'result'}:
            raise ValueError
        parsed = ParsedDocument.model_validate(payload['result'])
        validate_parsed_limits(parsed)
        return parsed
    except UnsupportedDocumentTypeError:
        raise
    except (OSError, ValueError, TypeError):
        raise DocumentParseError('document_parser_output_invalid') from None


class IsolatedDocumentParser:
    def __init__(self, *, timeout_seconds: float = 90):
        if not 0 < timeout_seconds <= 90:
            raise ValueError('document_parser_timeout_invalid')
        self.timeout_seconds = timeout_seconds

    def parse(self, request: DocumentIngestionRequest, *,
              cancelled: Callable[[], bool] | None = None) -> ParsedDocument:
        if os.name != 'posix':
            raise DocumentParseError('document_parser_platform_unsupported')
        if len(request.content) > MAX_INPUT_BYTES:
            raise DocumentParseError('document_input_too_large')
        if cancelled is not None and cancelled():
            raise DocumentParseError('document_parser_cancelled')
        with tempfile.TemporaryDirectory(prefix='agentmesh-parser-') as temporary:
            directory = Path(temporary)
            metadata = request.model_dump(exclude={'content'})
            encoded = json.dumps(metadata, ensure_ascii=False).encode('utf-8')
            if len(encoded) > 8192:
                raise DocumentParseError('document_parser_request_invalid')
            for name, content in [('input.bin', request.content), ('request.json', encoded)]:
                with os.fdopen(os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
                    stream.write(content)
            environment = {key: os.environ[key] for key in (
                'PATH', 'LANG', 'LC_ALL', 'AGENTMESH_TESSERACT_COMMAND', 'AGENTMESH_TESSERACT_LANG',
                'AGENTMESH_TESSERACT_TIMEOUT_SECONDS', 'TESSDATA_PREFIX',
            ) if key in os.environ}
            environment.update(TMPDIR=temporary, AGENTMESH_SKIP_DOTENV='1')
            deadline = monotonic() + self.timeout_seconds
            try:
                process = subprocess.Popen([sys.executable, '-I', '-m', 'agentmesh.document_parser_worker'],
                    cwd=temporary, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
            except OSError:
                raise DocumentParseError('document_parser_start_failed') from None
            try:
                while process.poll() is None:
                    if cancelled is not None and cancelled():
                        raise DocumentParseError('document_parser_cancelled')
                    if monotonic() >= deadline:
                        raise DocumentParseError('document_parser_timeout')
                    if _resident_bytes(process) > MAX_MEMORY_BYTES:
                        raise DocumentParseError('document_parser_memory_exceeded')
                    with suppress(subprocess.TimeoutExpired):
                        process.wait(timeout=min(0.1, max(0.001, deadline - monotonic())))
                if cancelled is not None and cancelled():
                    raise DocumentParseError('document_parser_cancelled')
                if process.returncode != 0:
                    raise DocumentParseError('document_parser_worker_failed')
                parsed = _read_output(directory)
                if any(getattr(parsed, key) != getattr(request, key)
                       for key in ('workspace_id', 'project_id', 'uploaded_by')):
                    raise DocumentParseError('document_parser_owner_mismatch')
                return parsed
            finally:
                _stop_process(process)
