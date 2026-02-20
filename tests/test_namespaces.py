"""
Sprint 2.4 — Scoped Namespace Tests

Covers:
- Namespace creation (explicit and auto-create on ingest)
- Ingest and search within a namespace
- Isolation between namespaces (no cross-contamination)
- get_stats() and clear() on a namespace
- Lifecycle: archive, delete (with and without data removal)
- list_namespaces() active/archived filtering
- Identity helper constants (TENANT_ID, AGENT_ID, CONVERSATION_ID)
- Backward compatibility — MemorySystem without namespaces works as before
- __repr__ of NamespacedMemory
"""

import os
import shutil
import tempfile

import pytest

from antaris_memory import (
    MemorySystem,
    NamespacedMemory,
    NamespaceManager,
    TENANT_ID,
    AGENT_ID,
    CONVERSATION_ID,
)


@pytest.fixture()
def store(tmp_path):
    """Fresh MemorySystem backed by a temp directory."""
    mem = MemorySystem(str(tmp_path))
    return mem


# ---------------------------------------------------------------------------
# 1. Namespace creation
# ---------------------------------------------------------------------------

def test_explicit_create_namespace(store):
    """create_namespace returns an info dict and registers the namespace."""
    info = store.create_namespace("alpha")
    assert info["status"] == "active"
    assert "created_at" in info


def test_auto_create_on_namespace_access(store):
    """Accessing memory.namespace('name') auto-registers the namespace."""
    ns = store.namespace("beta")
    assert ns is not None
    names = [n["name"] for n in store.list_namespaces()]
    assert "beta" in names


def test_namespace_returns_namespaced_memory(store):
    """memory.namespace() returns a NamespacedMemory proxy."""
    ns = store.namespace("gamma")
    assert isinstance(ns, NamespacedMemory)
    assert ns.name == "gamma"


def test_namespace_idempotent(store):
    """Calling namespace() twice returns the same cached proxy."""
    ns1 = store.namespace("delta")
    ns2 = store.namespace("delta")
    assert ns1 is ns2


def test_create_namespace_idempotent(store):
    """create_namespace is idempotent — calling twice is a no-op."""
    store.create_namespace("epsilon")
    store.create_namespace("epsilon")  # should not raise
    names = [n["name"] for n in store.list_namespaces()]
    assert names.count("epsilon") == 1


# ---------------------------------------------------------------------------
# 2. Ingest and search
# ---------------------------------------------------------------------------

def test_ingest_and_search_in_namespace(store):
    """Memories ingested into a namespace are retrievable by search."""
    ns = store.namespace("project-alpha")
    ns.ingest("API design notes from the architect meeting", source="architect")
    results = ns.search("API design")
    assert len(results) >= 1
    assert any("API" in r.content for r in results)


def test_namespace_ingest_returns_count(store):
    """ingest() returns a positive count of new memories added in that call."""
    ns = store.namespace("ingest-test")
    result = ns.ingest("First memory for namespace ingest count test")
    assert isinstance(result, int)
    assert result >= 1


# ---------------------------------------------------------------------------
# 3. Isolation between namespaces
# ---------------------------------------------------------------------------

def test_namespaces_are_isolated(store):
    """Memories from namespace A are NOT returned when searching namespace B."""
    ns_a = store.namespace("team-red")
    ns_b = store.namespace("team-blue")

    ns_a.ingest("Red team secret: operation falcon")
    ns_b.ingest("Blue team memo: status update")

    red_results = ns_a.search("falcon")
    blue_results = ns_b.search("falcon")  # should not see red team's content

    assert len(red_results) >= 1
    assert all("falcon" in r.content.lower() for r in red_results)
    assert len(blue_results) == 0


def test_two_namespaces_separate_directories(store):
    """Each namespace uses a distinct subdirectory under namespaces/."""
    store.namespace("ns-one")
    store.namespace("ns-two")
    base = os.path.join(store.workspace, "namespaces")
    subdirs = os.listdir(base)
    assert "ns-one" in subdirs
    assert "ns-two" in subdirs


def test_root_memory_not_visible_in_namespace(store):
    """Memories in the root MemorySystem are NOT visible via a namespace."""
    store.ingest("Root-level global memory about authentication")
    ns = store.namespace("isolated-ns")
    results = ns.search("authentication")
    assert len(results) == 0


# ---------------------------------------------------------------------------
# 4. get_stats and clear
# ---------------------------------------------------------------------------

def test_get_stats_returns_dict(store):
    """get_stats() returns a dict with at least 'total_memories'."""
    ns = store.namespace("stats-ns")
    ns.ingest("Sample entry one")
    ns.ingest("Sample entry two")
    stats = ns.get_stats()
    assert isinstance(stats, dict)
    assert stats.get("total_memories", 0) >= 2


def test_clear_removes_memories(store):
    """clear() removes all in-namespace memories and returns removed count."""
    ns = store.namespace("clearable")
    ns.ingest("Clearable namespace memory entry alpha for testing purposes")
    ns.ingest("Clearable namespace memory entry beta for testing purposes")
    removed = ns.clear()
    assert removed >= 2
    assert len(ns.memories) == 0


# ---------------------------------------------------------------------------
# 5. Lifecycle: archive
# ---------------------------------------------------------------------------

def test_archive_namespace(store):
    """archive_namespace() changes status to archived."""
    store.create_namespace("old-project")
    info = store.archive_namespace("old-project")
    assert info["status"] == "archived"
    assert info["archived_at"] is not None


def test_archived_namespace_excluded_from_list(store):
    """Archived namespaces are excluded from list_namespaces() by default."""
    store.create_namespace("archived-one")
    store.archive_namespace("archived-one")
    active_names = [n["name"] for n in store.list_namespaces()]
    assert "archived-one" not in active_names


def test_archived_namespace_visible_with_flag(store):
    """Archived namespaces appear when include_archived=True."""
    store.create_namespace("archived-two")
    store.archive_namespace("archived-two")
    all_names = [n["name"] for n in store.list_namespaces(include_archived=True)]
    assert "archived-two" in all_names


def test_archive_via_proxy(store):
    """NamespacedMemory.archive() delegates to parent manager."""
    ns = store.namespace("proxy-archive")
    ns.archive()
    info = store.list_namespaces(include_archived=True)
    match = next((n for n in info if n["name"] == "proxy-archive"), None)
    assert match is not None
    assert match["status"] == "archived"


# ---------------------------------------------------------------------------
# 6. Lifecycle: delete
# ---------------------------------------------------------------------------

def test_delete_namespace_removes_from_manifest(store):
    """delete_namespace() removes the namespace from the manifest."""
    store.create_namespace("temp-work")
    store.delete_namespace("temp-work")
    all_names = [n["name"] for n in store.list_namespaces(include_archived=True)]
    assert "temp-work" not in all_names


def test_delete_namespace_with_data(store):
    """delete_namespace(delete_data=True) also removes the workspace dir."""
    ns = store.namespace("to-be-deleted")
    ns.ingest("temporary memory")
    ns_dir = ns.workspace

    assert os.path.exists(ns_dir)
    store.delete_namespace("to-be-deleted", delete_data=True)
    assert not os.path.exists(ns_dir)


def test_delete_via_proxy(store):
    """NamespacedMemory.delete() delegates to parent manager."""
    ns = store.namespace("proxy-delete")
    ns.ingest("some content")
    ns.delete(delete_data=True)
    all_names = [n["name"] for n in store.list_namespaces(include_archived=True)]
    assert "proxy-delete" not in all_names


def test_cannot_delete_default_namespace(store):
    """Deleting the 'default' namespace raises ValueError."""
    with pytest.raises(ValueError, match="default"):
        store.delete_namespace("default")


# ---------------------------------------------------------------------------
# 7. list_namespaces
# ---------------------------------------------------------------------------

def test_list_namespaces_returns_list(store):
    """list_namespaces() returns a list of dicts."""
    store.create_namespace("list-one")
    store.create_namespace("list-two")
    ns_list = store.list_namespaces()
    assert isinstance(ns_list, list)
    names = [n["name"] for n in ns_list]
    assert "list-one" in names
    assert "list-two" in names


def test_list_namespaces_includes_default(store):
    """The 'default' namespace is always present in list_namespaces()."""
    ns_list = store.list_namespaces()
    names = [n["name"] for n in ns_list]
    assert "default" in names


def test_list_namespaces_has_required_keys(store):
    """Each namespace entry has name, status, and created_at."""
    store.create_namespace("keyed-ns")
    ns_list = store.list_namespaces()
    entry = next(n for n in ns_list if n["name"] == "keyed-ns")
    assert "status" in entry
    assert "created_at" in entry


# ---------------------------------------------------------------------------
# 8. Identity helper constants
# ---------------------------------------------------------------------------

def test_tenant_id_constant():
    assert TENANT_ID == "tenant"


def test_agent_id_constant():
    assert AGENT_ID == "agent"


def test_conversation_id_constant():
    assert CONVERSATION_ID == "conversation"


def test_namespace_using_tenant_prefix(store):
    """Namespaces created with TENANT_ID prefix work correctly."""
    ns_name = f"{TENANT_ID}-acme"
    ns = store.namespace(ns_name)
    ns.ingest("Acme tenant data")
    results = ns.search("Acme")
    assert len(results) >= 1


def test_namespace_using_agent_prefix(store):
    """Namespaces created with AGENT_ID prefix work correctly."""
    ns_name = f"{AGENT_ID}-researcher01"
    ns = store.namespace(ns_name)
    ns.ingest("Researcher findings")
    results = ns.search("Researcher")
    assert len(results) >= 1


def test_namespace_using_conversation_prefix(store):
    """Namespaces created with CONVERSATION_ID prefix work correctly."""
    ns_name = f"{CONVERSATION_ID}-abc123"
    ns = store.namespace(ns_name)
    ns.ingest("Turn 1: user asked about pricing")
    results = ns.search("pricing")
    assert len(results) >= 1


# ---------------------------------------------------------------------------
# 9. Backward compatibility
# ---------------------------------------------------------------------------

def test_backward_compat_ingest_search(store):
    """MemorySystem without namespaces still ingests and searches correctly."""
    store.ingest("Root memory: global architecture decision")
    results = store.search("architecture")
    assert len(results) >= 1


def test_backward_compat_save_load(tmp_path):
    """Save/load cycle on root MemorySystem is unaffected by namespace code."""
    mem = MemorySystem(str(tmp_path))
    mem.ingest("Important baseline memory")
    mem.save()

    mem2 = MemorySystem(str(tmp_path))
    results = mem2.search("baseline")
    assert len(results) >= 1


# ---------------------------------------------------------------------------
# 10. Namespace name validation
# ---------------------------------------------------------------------------

def test_invalid_namespace_name_raises(store):
    """Namespace names with invalid characters raise ValueError."""
    with pytest.raises(ValueError):
        store.namespace("has spaces")


def test_namespace_name_cannot_start_with_hyphen(store):
    """Namespace names cannot start with a hyphen."""
    with pytest.raises(ValueError):
        store.namespace("-badname")


# ---------------------------------------------------------------------------
# 11. NamespacedMemory repr
# ---------------------------------------------------------------------------

def test_namespaced_memory_repr(store):
    """__repr__ contains the namespace name and workspace."""
    ns = store.namespace("repr-test")
    r = repr(ns)
    assert "repr-test" in r
    assert "NamespacedMemory" in r


# ---------------------------------------------------------------------------
# 12. create() convenience method on proxy
# ---------------------------------------------------------------------------

def test_create_via_proxy(store):
    """NamespacedMemory.create() pre-registers the namespace."""
    ns = store.namespace("pre-created")
    info = ns.create()
    assert info["status"] == "active"
    names = [n["name"] for n in store.list_namespaces()]
    assert "pre-created" in names
