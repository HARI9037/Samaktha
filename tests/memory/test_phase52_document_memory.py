"""Phase 5.2 tests — DocumentMemoryStore.

Validates:
- Documents can be stored and retrieved by ID
- Metadata retrieval works correctly
- Context linking between documents and memory items
- Filtering by media type and tag
"""
import pytest

from app.core.contracts.multimodal import MediaType
from app.memory.documents import DocumentMemoryStore, DocumentRecord


@pytest.fixture
def store():
    return DocumentMemoryStore()


@pytest.fixture
def sample_record():
    return DocumentRecord(
        name="Quarterly Report",
        media_type=MediaType.DOCUMENT,
        source="https://example.com/q1.pdf",
        summary="Q1 financial results",
        tags=["finance", "q1", "2025"],
        metadata={"pages": 42, "author": "finance-team"},
    )


def test_store_and_retrieve(store, sample_record):
    stored = store.store(sample_record)
    retrieved = store.get(stored.document_id)

    assert retrieved is not None
    assert retrieved.name == "Quarterly Report"
    assert retrieved.media_type == MediaType.DOCUMENT
    assert retrieved.metadata["pages"] == 42


def test_store_updates_existing(store, sample_record):
    stored = store.store(sample_record)
    stored.summary = "Updated summary"
    store.store(stored)

    retrieved = store.get(stored.document_id)
    assert retrieved.summary == "Updated summary"


def test_delete(store, sample_record):
    stored = store.store(sample_record)
    assert store.delete(stored.document_id) is True
    assert store.get(stored.document_id) is None
    assert store.delete(stored.document_id) is False


def test_list_all(store):
    store.store(DocumentRecord(name="Doc1", media_type=MediaType.IMAGE, source="img1.png"))
    store.store(DocumentRecord(name="Doc2", media_type=MediaType.AUDIO, source="audio.mp3"))

    all_docs = store.list_all()
    assert len(all_docs) == 2


def test_find_by_media_type(store):
    store.store(DocumentRecord(name="Image", media_type=MediaType.IMAGE, source="img.png"))
    store.store(DocumentRecord(name="Report", media_type=MediaType.DOCUMENT, source="doc.pdf"))
    store.store(DocumentRecord(name="Chart", media_type=MediaType.IMAGE, source="chart.png"))

    images = store.find_by_media_type(MediaType.IMAGE)
    assert len(images) == 2
    assert all(d.media_type == MediaType.IMAGE for d in images)


def test_find_by_tag(store, sample_record):
    store.store(sample_record)
    store.store(DocumentRecord(name="Other", media_type=MediaType.DOCUMENT, source="x.pdf", tags=["other"]))

    finance_docs = store.find_by_tag("finance")
    assert len(finance_docs) == 1
    assert finance_docs[0].name == "Quarterly Report"


def test_link_context(store, sample_record):
    stored = store.store(sample_record)
    result = store.link_context(stored.document_id, "memory-item-abc")
    assert result is True

    retrieved = store.get(stored.document_id)
    assert "memory-item-abc" in retrieved.context_ids


def test_find_by_context(store, sample_record):
    stored = store.store(sample_record)
    store.link_context(stored.document_id, "ctx-123")

    linked = store.find_by_context("ctx-123")
    assert len(linked) == 1
    assert linked[0].document_id == stored.document_id


def test_link_context_returns_false_for_missing_doc(store):
    result = store.link_context("nonexistent-id", "ctx-xyz")
    assert result is False


def test_count(store):
    assert store.count() == 0
    store.store(DocumentRecord(name="A", media_type=MediaType.IMAGE, source="a.png"))
    store.store(DocumentRecord(name="B", media_type=MediaType.DOCUMENT, source="b.pdf"))
    assert store.count() == 2
