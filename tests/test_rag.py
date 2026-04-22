from arma3_builder.rag import HybridRetriever, MemoryStore, semantic_chunks
from arma3_builder.rag.ingest_classnames import classnode_to_document, parse_config_cpp
from arma3_builder.rag.store import Document


def test_semantic_chunking_splits_on_headings():
    text = """
# remoteExec

Description body for remoteExec that is long enough to be retained as a chunk by the semantic splitter — at least eighty characters.

## Syntax

`arguments remoteExec [order, targets]` -- this is the canonical syntax that consumers of the API should follow when remote-executing.

# remoteExecCall

Synchronous variant — also long enough to make it past the threshold filter that the chunker imposes.
"""
    chunks = semantic_chunks(text, base_metadata={"source": "biki"})
    titles = {c.title for c in chunks}
    assert "remoteExec" in titles
    assert "remoteExecCall" in titles


def test_memory_store_metadata_filter():
    store = MemoryStore()
    store.upsert([
        Document(id="1", text="rifleman", metadata={"source": "classnames", "side": "WEST"}),
        Document(id="2", text="rifleman", metadata={"source": "classnames", "side": "EAST"}),
    ])
    retriever = HybridRetriever(store=store)
    hits = retriever.classnames("rifleman", side="WEST")
    assert len(hits) == 1
    assert hits[0].metadata["side"] == "WEST"


def test_config_cpp_parser_extracts_classes():
    text = """
class CfgVehicles {
    class B_Soldier_F: Man {
        scope = 2;
        side = 1;
        faction = "BLU_F";
        displayName = "Rifleman";
    };
    class O_Soldier_F: Man {
        scope = 2;
        side = 0;
        faction = "OPF_F";
        displayName = "Rifleman";
    };
};
"""
    nodes = parse_config_cpp(text)
    names = {n.name for n in nodes}
    assert {"B_Soldier_F", "O_Soldier_F"}.issubset(names)
    docs = [classnode_to_document(n, tenant="a3") for n in nodes if n.name not in {"CfgVehicles"}]
    sides = {d.metadata.get("side") for d in docs}
    assert "WEST" in sides
    assert "EAST" in sides
