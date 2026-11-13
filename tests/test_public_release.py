import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import local_agent
import settings
from knowledge_base import KnowledgeBase


def load_script(name, relative):
    spec = importlib.util.spec_from_file_location(name, settings.ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PublicReleaseTests(unittest.TestCase):
    def test_example_config_works_without_personal_paths(self):
        config = settings.read_config(settings.ROOT / "config.example.json")
        with patch.object(settings, "CONFIG", config), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(settings.path_value("MEETING_CONTEXT_ROOT", ""), settings.ROOT / "materials")
            self.assertEqual(settings.list_value("MEETING_SOURCE_DIRS"), ("docs", "projects"))
            self.assertEqual(settings.path_value("HUOSHAN_CONFIG", ""), settings.ROOT / "secrets/huoshan.json")
        with patch.object(settings, "CONFIG", config), patch.dict(os.environ, {"HUOSHAN_MODEL": "override"}):
            self.assertEqual(settings.value("HUOSHAN_MODEL"), "override")

    def test_configured_tools_and_retriever_stay_in_material_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "projects/demo").mkdir(parents=True)
            (root / "projects/demo/flow.go").write_text("package demo\n// verified fact\n")
            (root / "resume.md").write_text("Fictional candidate: Go queue project")
            with patch.object(local_agent, "SOURCE_DIRS", ("projects",)), patch.object(local_agent, "EXTRA_FILES", ()):
                tools = local_agent.WorkspaceTools(root)
                self.assertIn("projects/demo/flow.go", tools.list_files())
                self.assertIn("verified fact", tools.read_file("projects/demo/flow.go"))
            kb = KnowledgeBase(root, sources=[("Resume", "resume.md")])
            self.assertIn("Go queue", kb.retrieve("Go"))
            with self.assertRaises(ValueError):
                KnowledgeBase(root, sources=[("Outside", "../outside.md")])
            self.assertEqual(local_agent.WorkspaceTools(root / "missing").files(), [])
            for paths in (["../outside"], [str(root)]):
                with patch.object(settings, "CONFIG", {"PATHS": paths}), self.assertRaises(ValueError):
                    settings.list_value("PATHS")

    def test_generated_service_uses_checkout_paths_and_audio_settings(self):
        service = load_script("service_config_test", "bin/service_config.py")
        root = Path("/opt/example-checkout")
        config = service.service_config(root)
        self.assertEqual(config["WorkingDirectory"], str(root))
        self.assertEqual(config["ProgramArguments"][0], str(root / ".venv-app/bin/python"))
        self.assertEqual(config["ProcessType"], "Interactive")
        self.assertTrue(config["LegacyTimers"])
        self.assertEqual(config["EnvironmentVariables"]["MEETING_CONFIG_FILE"], str(root / "config.local.json"))
        self.assertNotIn("HUOSHAN_CONFIG", config["EnvironmentVariables"])

    def test_release_checker_flags_leaks_without_printing_values(self):
        checker = load_script("release_checker_test", "scripts/check_public.py")
        self.assertTrue(checker.inspect_blob("var/session.jsonl", b"private transcript"))
        self.assertTrue(checker.inspect_blob("config.local.json", b"{}"))
        personal_path = "/Users" + "/example/private/file"
        self.assertTrue(checker.inspect_blob("app.py", personal_path.encode()))
        token = "sk-" + "A" * 32
        self.assertTrue(checker.inspect_blob("settings.py", token.encode()))
        self.assertFalse(checker.inspect_blob("config.example.json", b'{"key": "REPLACE_WITH_YOUR_KEY"}'))
        self.assertFalse(checker.inspect_blob("examples/reference.md", b"Fictional demonstration"))


if __name__ == "__main__":
    unittest.main()
