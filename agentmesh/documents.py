from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from pydantic import BaseModel, Field

from agentmesh.models import Source

logger = logging.getLogger(__name__)


class UnsupportedDocumentTypeError(ValueError):
    pass


class DocumentIngestionRequest(BaseModel):
    file_name: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=120)
    content: bytes
    workspace_id: str
    project_id: str
    uploaded_by: str


class ParsedDocument(BaseModel):
    title: str
    text: str
    source: Source
    workspace_id: str
    project_id: str
    uploaded_by: str
    metadata: dict[str, str] = Field(default_factory=dict)


class DocumentParser(Protocol):
    def parse(self, request: DocumentIngestionRequest) -> ParsedDocument: ...


class PlainTextDocumentParser:
    supported_content_types = {"text/plain", "text/markdown"}
    supported_extensions = {".txt", ".md", ".markdown"}

    def parse(self, request: DocumentIngestionRequest) -> ParsedDocument:
        extension = Path(request.file_name).suffix.lower()
        if request.content_type not in self.supported_content_types and extension not in self.supported_extensions:
            raise UnsupportedDocumentTypeError(f"Unsupported document type: {request.content_type}")

        raw_text = request.content.decode("utf-8")
        title, text = self._split_title(raw_text, request.file_name)
        return ParsedDocument(
            title=title,
            text=text,
            source=Source(
                title=request.file_name,
                source_type="document",
                reference=f"document://{request.file_name}",
            ),
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            uploaded_by=request.uploaded_by,
            metadata={"parser": "plain_text", "content_type": request.content_type},
        )

    @staticmethod
    def _split_title(raw_text: str, file_name: str) -> tuple[str, str]:
        lines = [line.strip() for line in raw_text.splitlines()]
        non_empty_lines = [line for line in lines if line]
        if not non_empty_lines:
            return file_name, ""

        first_line = non_empty_lines[0]
        if first_line.startswith("# "):
            title = first_line[2:].strip() or file_name
            body_lines = non_empty_lines[1:]
            return title, "\n".join(body_lines)
        return file_name, "\n".join(non_empty_lines)


class ExternalDocumentParserConnector:
    def parse(self, request: DocumentIngestionRequest) -> ParsedDocument:
        raise NotImplementedError("External document parsing is provided by another project.")


class PDFDocumentParser:
    """基于 PyMuPDF 的 PDF 文档解析器。"""

    supported_content_types = {"application/pdf"}
    supported_extensions = {".pdf"}

    def parse(self, request: DocumentIngestionRequest) -> ParsedDocument:
        extension = Path(request.file_name).suffix.lower()
        if request.content_type not in self.supported_content_types and extension not in self.supported_extensions:
            raise UnsupportedDocumentTypeError(f"Unsupported document type: {request.content_type}")

        try:
            import fitz  # PyMuPDF
        except ImportError as e:
            raise UnsupportedDocumentTypeError("PDF 解析需要安装 pymupdf: pip install pymupdf") from e

        try:
            doc = fitz.open(stream=request.content, filetype="pdf")
        except Exception as e:
            raise UnsupportedDocumentTypeError(f"无法打开 PDF 文件: {e}") from e

        pages_text: list[str] = []
        for page in doc:
            text = page.get_text("text")
            if text.strip():
                pages_text.append(text.strip())
        doc.close()

        full_text = "\n\n".join(pages_text)
        title = self._extract_title(full_text, request.file_name)

        return ParsedDocument(
            title=title,
            text=full_text,
            source=Source(
                title=request.file_name,
                source_type="document",
                reference=f"document://{request.file_name}",
            ),
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            uploaded_by=request.uploaded_by,
            metadata={
                "parser": "pdf",
                "content_type": request.content_type,
                "page_count": str(len(pages_text)),
            },
        )

    @staticmethod
    def _extract_title(text: str, file_name: str) -> str:
        """尝试从 PDF 文本中提取标题，回退到文件名。"""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return Path(file_name).stem
        first_line = lines[0]
        if len(first_line) <= 100:
            return first_line
        return Path(file_name).stem


class WordDocumentParser:
    """解析 OOXML `.docx` 正文文本。"""

    supported_content_types = {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    supported_extensions = {".docx"}

    def parse(self, request: DocumentIngestionRequest) -> ParsedDocument:
        extension = Path(request.file_name).suffix.lower()
        if request.content_type not in self.supported_content_types and extension not in self.supported_extensions:
            raise UnsupportedDocumentTypeError(f"Unsupported document type: {request.content_type}")
        try:
            text = _extract_ooxml_text(request.content, ["word/document.xml"])
        except (BadZipFile, KeyError, ElementTree.ParseError) as error:
            raise UnsupportedDocumentTypeError(f"无法解析 Word 文档: {error}") from error
        return _parsed_document(request, "word", _title_from_text(text, request.file_name), text)


class SlideDocumentParser:
    """解析 OOXML `.pptx` 幻灯片文本。"""

    supported_content_types = {"application/vnd.openxmlformats-officedocument.presentationml.presentation"}
    supported_extensions = {".pptx"}

    def parse(self, request: DocumentIngestionRequest) -> ParsedDocument:
        extension = Path(request.file_name).suffix.lower()
        if request.content_type not in self.supported_content_types and extension not in self.supported_extensions:
            raise UnsupportedDocumentTypeError(f"Unsupported document type: {request.content_type}")
        try:
            text = _extract_ooxml_text(request.content, ["ppt/slides/"])
        except (BadZipFile, KeyError, ElementTree.ParseError) as error:
            raise UnsupportedDocumentTypeError(f"无法解析 Slide 文档: {error}") from error
        return _parsed_document(request, "slide", _title_from_text(text, request.file_name), text)


class ImageOCRDocumentParser:
    """通过外部 tesseract 命令解析图片文本。"""

    supported_content_types = {"image/png", "image/jpeg", "image/webp", "image/tiff"}
    supported_extensions = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}

    def parse(self, request: DocumentIngestionRequest) -> ParsedDocument:
        extension = Path(request.file_name).suffix.lower()
        if request.content_type not in self.supported_content_types and extension not in self.supported_extensions:
            raise UnsupportedDocumentTypeError(f"Unsupported document type: {request.content_type}")

        command = os.getenv("AGENTMESH_TESSERACT_COMMAND", "tesseract")
        language = os.getenv("AGENTMESH_TESSERACT_LANG", "eng")
        timeout = int(os.getenv("AGENTMESH_TESSERACT_TIMEOUT_SECONDS", "30"))
        suffix = extension if extension in self.supported_extensions else ".png"
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix) as file:
                file.write(request.content)
                file.flush()
                completed = subprocess.run(
                    [command, file.name, "stdout", "-l", language],
                    capture_output=True,
                    timeout=timeout,
                    check=False,
                )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise UnsupportedDocumentTypeError(f"OCR 命令不可用: {error}") from error

        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip() or "OCR command failed"
            raise UnsupportedDocumentTypeError(f"OCR 解析失败: {detail}")
        text = completed.stdout.decode("utf-8", errors="replace").strip()
        return _parsed_document(request, "image_ocr", _title_from_text(text, request.file_name), text)


def _extract_ooxml_text(content: bytes, xml_prefixes: list[str]) -> str:
    chunks: list[str] = []
    with tempfile.NamedTemporaryFile(suffix=".zip") as file:
        file.write(content)
        file.flush()
        with ZipFile(file.name) as archive:
            names = sorted(
                name
                for name in archive.namelist()
                if any(name == prefix or name.startswith(prefix) for prefix in xml_prefixes)
                and name.endswith(".xml")
            )
            if not names:
                raise KeyError("OOXML text parts not found")
            for name in names:
                root = ElementTree.fromstring(archive.read(name))
                texts = [node.text.strip() for node in root.iter() if node.tag.endswith("}t") and node.text and node.text.strip()]
                if texts:
                    chunks.append("\n".join(texts))
    return "\n\n".join(chunks)


def _title_from_text(text: str, file_name: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines and len(lines[0]) <= 100:
        return lines[0]
    return Path(file_name).stem


def _parsed_document(request: DocumentIngestionRequest, parser_name: str, title: str, text: str) -> ParsedDocument:
    return ParsedDocument(
        title=title,
        text=text,
        source=Source(
            title=request.file_name,
            source_type="document",
            reference=f"document://{request.file_name}",
        ),
        workspace_id=request.workspace_id,
        project_id=request.project_id,
        uploaded_by=request.uploaded_by,
        metadata={
            "parser": parser_name,
            "content_type": request.content_type,
            "content_sha256": hashlib.sha256(request.content).hexdigest(),
        }
    )


class CompositeDocumentParser:
    """组合多个解析器，按文件类型路由。"""

    def __init__(
        self,
        parsers: list[
            PlainTextDocumentParser
            | PDFDocumentParser
            | WordDocumentParser
            | SlideDocumentParser
            | ImageOCRDocumentParser
        ]
        | None = None,
    ):
        self._parsers = parsers or [
            PDFDocumentParser(),
            WordDocumentParser(),
            SlideDocumentParser(),
            ImageOCRDocumentParser(),
            PlainTextDocumentParser(),
        ]

    def parse(self, request: DocumentIngestionRequest) -> ParsedDocument:
        extension = Path(request.file_name).suffix.lower()
        for parser in self._parsers:
            if request.content_type in parser.supported_content_types or extension in parser.supported_extensions:
                return parser.parse(request)
        raise UnsupportedDocumentTypeError(
            f"不支持的文档类型: {request.content_type} ({request.file_name})"
        )

    @property
    def supported_extensions(self) -> set[str]:
        result: set[str] = set()
        for parser in self._parsers:
            result.update(parser.supported_extensions)
        return result

    @property
    def supported_content_types(self) -> set[str]:
        result: set[str] = set()
        for parser in self._parsers:
            result.update(parser.supported_content_types)
        return result
