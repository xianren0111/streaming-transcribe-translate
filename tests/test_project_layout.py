import ast
import os
import tempfile
import unittest
from pathlib import Path

from streaming_transcribe_translate import desktop_app, streaming_bridge
from streaming_transcribe_translate.paths import LOG_FILE, ROOT


class ProjectLayoutTests(unittest.TestCase):
    def test_configuration_and_data_paths_survive_working_directory_changes(self):
        project = Path(__file__).resolve().parent.parent
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                self.assertEqual(ROOT, project)
                self.assertEqual(desktop_app.ENV_FILE, project / ".env")
                self.assertEqual(desktop_app.SUBTITLE_SETTINGS_FILE, project / "subtitle_settings.json")
                self.assertEqual(desktop_app.RECORDS_ROOT, project / "records")
                self.assertEqual(LOG_FILE, project / "logs" / "streaming_live_translation.log")
                self.assertEqual(streaming_bridge._STREAMING_ROOT, project.parent / "Streaming")
            finally:
                os.chdir(previous)

    def test_application_uses_package_relative_local_imports(self):
        names = {path.stem for path in (ROOT / "streaming_transcribe_translate").glob("*.py")}
        for path in (ROOT / "streaming_transcribe_translate").glob("*.py"):
            with self.subTest(module=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module in names:
                        self.assertEqual(node.level, 1, f"Unqualified local import in {path.name}")

    def test_launcher_and_preserved_files_match_new_layout(self):
        launcher = (ROOT / "Start Translation.bat").read_text()
        self.assertIn("pythonw.exe -m streaming_transcribe_translate", launcher)
        self.assertIn("pyw.exe -3 -m streaming_transcribe_translate", launcher)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("[guides folder](docs/guides/)", readme)
        self.assertIn("not a standalone", readme)
        for relative in (
            "legacy\\streaming_live_translation.py",
            "docs\\DEVELOPER_GUIDE.md",
            "docs\\ENV_CONFIGURATION.md",
            "streaming_transcribe_translate\\__main__.py",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_gitignore_excludes_private_runtime_data_and_caches(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for entry in (
            ".env",
            "overlay_window.json",
            "web_url.txt",
            "logs/",
            "records/",
            "models/",
            "*.log",
            ".cache/",
        ):
            with self.subTest(entry=entry):
                self.assertIn(entry, ignored)
