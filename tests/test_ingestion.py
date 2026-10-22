import io
from pathlib import Path

import pytest
from adam.core.config import KnowledgeConfig
from adam.core.storage import ConversationStore
from adam.knowledge.contracts import SourcePolicy, SourceRequest
from adam.knowledge.parsing import IngestionError
from adam.knowledge.service import KnowledgeService
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def service(tmp_path: Path) -> KnowledgeService:
    return KnowledgeService(
        ConversationStore(tmp_path / "data/runtime.sqlite3"),
        KnowledgeConfig(allowed_roots=[tmp_path]),
    )


def test_duplicate_move_edit_delete_and_namespaces(tmp_path: Path) -> None:
    knowledge = service(tmp_path)
    a, b, moved = (tmp_path / name for name in ["a.md", "b.md", "moved.md"])
    a.write_text("# RiverLab\nThe retry limit is three.", encoding="utf-8")
    b.write_bytes(a.read_bytes())
    first = knowledge.ingest(SourceRequest(path=str(a), namespace="project"))
    assert (
        knowledge.ingest(SourceRequest(path=str(b), namespace="project")).source_id
        == first.source_id
    )
    assert len(knowledge.sources("project")) == 1
    a.rename(moved)
    b.unlink()
    assert (
        knowledge.ingest(SourceRequest(path=str(moved), namespace="project")).source_id
        == first.source_id
    )
    moved.write_text("# RiverLab\nThe retry limit is five.", encoding="utf-8")
    assert knowledge.refresh("project")[0].status == "STALE"
    edited = knowledge.ingest(SourceRequest(path=str(moved), namespace="project"))
    assert edited.source_id == first.source_id and edited.version == 2
    with knowledge.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM knowledge_versions").fetchone()[0] == 2
    assert (knowledge.blobs / (first.content_hash + ".bin")).exists()
    other = knowledge.ingest(SourceRequest(path=str(moved), namespace="other"))
    assert other.source_id != first.source_id
    moved.unlink()
    assert all(source.status == "MISSING" for source in knowledge.refresh())
    assert knowledge.chunks(
        edited
    )  # Canonical text remains available for explicit archive inspection.


def test_code_pdf_permissions_and_secret_rejection(tmp_path: Path) -> None:
    knowledge = service(tmp_path)
    code = tmp_path / "module.py"
    code.write_text("def double(value):\n    return value * 2\n", encoding="utf-8")
    record = knowledge.ingest(
        SourceRequest(path=str(code), policy=SourcePolicy(sensitivity="PRIVATE"))
    )
    assert record.media_type == "code" and record.policy.allowed_audiences == ["owner"]
    assert "lines:" in knowledge.chunks(record)[0].locator
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 10 250 Td (RiverLab launch is Tuesday.) Tj ET")
    page[NameObject("/Contents")] = stream
    data = io.BytesIO()
    writer.write(data)
    pdf = tmp_path / "notes.pdf"
    pdf.write_bytes(data.getvalue())
    document = knowledge.ingest(SourceRequest(path=str(pdf)))
    assert "Tuesday" in knowledge.chunks(document)[0].text
    assert knowledge.chunks(document)[0].locator.startswith("page:1")
    secret = tmp_path / "secret.txt"
    secret.write_text("api_key=never-persist-this-credential", encoding="utf-8")
    with pytest.raises(IngestionError):
        knowledge.ingest(SourceRequest(path=str(secret)))
    assert b"never-persist-this" not in knowledge.store.path.read_bytes()
    with pytest.raises(IngestionError):
        knowledge.ingest(SourceRequest(path=str(code), policy=SourcePolicy(sensitivity="SECRET")))
    with pytest.raises(IngestionError):
        knowledge.safe_path(str(tmp_path.parent / "outside.txt"))
