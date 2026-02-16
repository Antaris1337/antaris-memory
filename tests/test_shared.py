"""Tests for SharedMemoryPool — multi-agent shared memory."""

import os
import shutil
import tempfile
import unittest

from antaris_memory.shared import SharedMemoryPool, AgentPermission


class TestAgentPermission(unittest.TestCase):

    def test_roles(self):
        read = AgentPermission("a1", "read")
        write = AgentPermission("a2", "write")
        admin = AgentPermission("a3", "admin")

        self.assertTrue(read.can_read())
        self.assertFalse(read.can_write())
        self.assertFalse(read.can_admin())

        self.assertTrue(write.can_read())
        self.assertTrue(write.can_write())
        self.assertFalse(write.can_admin())

        self.assertTrue(admin.can_read())
        self.assertTrue(admin.can_write())
        self.assertTrue(admin.can_admin())

    def test_namespace_access(self):
        agent = AgentPermission("a1", "write", ["frontend", "shared"])
        self.assertTrue(agent.can_access_namespace("frontend"))
        self.assertTrue(agent.can_access_namespace("shared"))
        self.assertFalse(agent.can_access_namespace("backend"))

        admin = AgentPermission("a2", "admin")
        self.assertTrue(admin.can_access_namespace("anything"))

    def test_invalid_role(self):
        with self.assertRaises(ValueError):
            AgentPermission("a1", "superuser")

    def test_serialization(self):
        perm = AgentPermission("a1", "write", ["ns1", "ns2"])
        d = perm.to_dict()
        restored = AgentPermission.from_dict(d)
        self.assertEqual(restored.agent_id, "a1")
        self.assertEqual(restored.role, "write")
        self.assertEqual(restored.namespaces, ["ns1", "ns2"])


class TestSharedMemoryPool(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pool = SharedMemoryPool(self.tmpdir, "test")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_register_and_list_agents(self):
        self.pool.register_agent("moro", "admin")
        self.pool.register_agent("forge", "write", ["backend"])
        self.pool.register_agent("pixel", "write", ["frontend"])

        agents = self.pool.list_agents()
        self.assertEqual(len(agents), 3)

    def test_write_and_read(self):
        self.pool.register_agent("moro", "write")
        self.pool.write("moro", "PostgreSQL is the database choice",
                        category="strategic")
        self.pool.write("moro", "Frontend uses React with TypeScript",
                        category="operational")

        results = self.pool.read("moro", "database")
        self.assertTrue(len(results) > 0)
        self.assertIn("PostgreSQL", results[0].content)

    def test_read_only_agent_cant_write(self):
        self.pool.register_agent("observer", "read")
        result = self.pool.write("observer", "Trying to write")
        self.assertIsNone(result)

    def test_unregistered_agent_cant_access(self):
        result = self.pool.write("unknown", "Trying to write")
        self.assertIsNone(result)
        results = self.pool.read("unknown", "anything")
        self.assertEqual(len(results), 0)

    def test_namespace_isolation(self):
        self.pool.register_agent("forge", "write", ["backend"])
        self.pool.register_agent("pixel", "write", ["frontend"])

        self.pool.write("forge", "API uses REST with JWT auth",
                        namespace="backend")
        self.pool.write("pixel", "Using Tailwind for styling",
                        namespace="frontend")

        # Forge can't see frontend namespace
        results = self.pool.read("forge", "Tailwind", namespace="frontend")
        self.assertEqual(len(results), 0)

        # Pixel can't see backend namespace
        results = self.pool.read("pixel", "REST API", namespace="backend")
        self.assertEqual(len(results), 0)

    def test_shared_namespace_accessible_to_all(self):
        self.pool.register_agent("forge", "write", ["backend"])
        self.pool.register_agent("pixel", "write", ["frontend"])

        self.pool.write("forge", "Project deadline is March 15",
                        namespace="shared")

        results = self.pool.read("pixel", "deadline")
        self.assertTrue(len(results) > 0)

    def test_admin_sees_all_namespaces(self):
        self.pool.register_agent("moro", "admin")
        self.pool.register_agent("forge", "write", ["backend"])

        self.pool.write("forge", "Secret backend implementation detail",
                        namespace="backend")

        results = self.pool.read("moro", "implementation")
        self.assertTrue(len(results) > 0)

    def test_conflict_detection(self):
        self.pool.register_agent("forge", "write")
        self.pool.register_agent("pixel", "write")

        self.pool.write("forge", "We should use PostgreSQL for the database project deployment")
        self.pool.write("pixel",
                        "We should not use PostgreSQL for the database project, MongoDB is better for deployment")

        conflicts = self.pool.get_conflicts()
        self.assertTrue(len(conflicts) > 0)
        self.assertEqual(conflicts[0]["type"], "contradiction")

    def test_resolve_conflict(self):
        self.pool.register_agent("a1", "write")
        self.pool.register_agent("a2", "write")

        self.pool.write("a1", "The project will succeed and is on track")
        self.pool.write("a2", "The project has failed and is not on track")

        conflicts = self.pool.get_conflicts()
        if conflicts:
            self.pool.resolve_conflict(0, "keep_a1", resolver="moro")
            unresolved = self.pool.get_conflicts()
            self.assertEqual(len(unresolved), 0)

    def test_propagate(self):
        self.pool.register_agent("scout", "write", ["qa", "shared"])
        self.pool.register_agent("forge", "write", ["backend", "shared"])

        self.pool.write("scout", "Found critical bug in auth module",
                        namespace="qa", category="strategic")
        self.pool.write("scout", "Login page renders correctly",
                        namespace="qa")

        count = self.pool.propagate("scout", "backend", query="bug auth")
        self.assertTrue(count > 0)

        # Forge can now see the propagated memory
        results = self.pool.read("forge", "bug auth", namespace="backend")
        self.assertTrue(len(results) > 0)

    def test_save_and_load(self):
        self.pool.register_agent("moro", "admin")
        self.pool.write("moro", "Important shared decision about architecture")

        self.pool.save()

        # Load into new pool
        pool2 = SharedMemoryPool(self.tmpdir, "test")
        count = pool2.load()
        self.assertEqual(count, 1)
        self.assertIn("moro", pool2.permissions)

    def test_stats(self):
        self.pool.register_agent("a1", "write", ["shared", "private"])
        self.pool.register_agent("a2", "write")

        self.pool.write("a1", "Memory from agent one", namespace="shared")
        self.pool.write("a2", "Memory from agent two", namespace="shared")
        self.pool.write("a1", "Private memory about internal implementation details", namespace="private")

        stats = self.pool.stats()
        self.assertEqual(stats["total_memories"], 3)
        self.assertEqual(stats["registered_agents"], 2)
        self.assertIn("shared", stats["namespaces"])

    def test_remove_agent(self):
        self.pool.register_agent("admin", "admin")
        self.pool.register_agent("temp", "write")

        self.assertTrue(
            self.pool.remove_agent("temp", requester="admin"))
        self.assertEqual(len(self.pool.list_agents()), 1)

    def test_remove_agent_requires_admin(self):
        self.pool.register_agent("writer", "write")
        self.pool.register_agent("other", "write")

        self.assertFalse(
            self.pool.remove_agent("other", requester="writer"))


if __name__ == "__main__":
    unittest.main()
