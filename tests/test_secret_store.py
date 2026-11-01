import base64
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dotenv import dotenv_values

from streaming_transcribe_translate import secret_store
from streaming_transcribe_translate.secret_store import SecretStoreError


def fake_protect(data):
    return b"enc:" + data[::-1]


def fake_unprotect(data):
    if not data.startswith(b"enc:"):
        raise SecretStoreError("bad")
    return data[4:][::-1]


class FakeDpapiTestCase(unittest.TestCase):
    def setUp(self):
        for name, value in (
            ("available", lambda: True),
            ("_crypt_protect", fake_protect),
            ("_crypt_unprotect", fake_unprotect),
        ):
            patcher = mock.patch.object(secret_store, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = Path(self.tmp.name) / ".env"


class SecretStoreTests(FakeDpapiTestCase):
    def test_round_trip(self):
        encoded = secret_store.protect("sk-test-value")
        self.assertNotIn("sk-test-value", encoded)
        self.assertEqual(secret_store.unprotect(encoded), "sk-test-value")

    def test_env_updates_blank_plaintext_for_both_keys(self):
        updates = secret_store.env_updates(
            {"OPENAI_API_KEY": "one", "JEV_API_KEY": "two", "OPENAI_BASE_URL": "http://localhost:11434/v1"}
        )
        self.assertEqual(updates["OPENAI_API_KEY"], "")
        self.assertEqual(updates["JEV_API_KEY"], "")
        self.assertEqual(secret_store.unprotect(updates["OPENAI_API_KEY_DPAPI"]), "one")
        self.assertEqual(secret_store.unprotect(updates["JEV_API_KEY_DPAPI"]), "two")
        self.assertEqual(updates["OPENAI_BASE_URL"], "http://localhost:11434/v1")

    def test_clearing_key_writes_empty_ciphertext(self):
        updates = secret_store.env_updates({"OPENAI_API_KEY": ""})
        self.assertEqual(updates, {"OPENAI_API_KEY_DPAPI": "", "OPENAI_API_KEY": ""})

    def test_plaintext_is_migrated_on_load(self):
        self.env.write_text('OPENAI_API_KEY="plain-secret"\nOTHER="x"\n', encoding="utf-8")
        secrets, failed = secret_store.read_env_secrets(self.env)
        self.assertEqual(secrets["OPENAI_API_KEY"], "plain-secret")
        self.assertEqual(failed, [])
        self.assertNotIn("plain-secret", self.env.read_text(encoding="utf-8"))
        values = dotenv_values(self.env)
        self.assertEqual(values["OPENAI_API_KEY"], "")
        self.assertEqual(values["OTHER"], "x")
        self.assertEqual(secret_store.unprotect(values["OPENAI_API_KEY_DPAPI"]), "plain-secret")
        again, failed = secret_store.read_env_secrets(self.env)
        self.assertEqual(again["OPENAI_API_KEY"], "plain-secret")
        self.assertEqual(failed, [])

    def test_write_env_never_stores_plaintext(self):
        self.env.write_text("", encoding="utf-8")
        secret_store.write_env(self.env, {"JEV_API_KEY": "jev-secret", "OPENAI_MODEL": "m"})
        text = self.env.read_text(encoding="utf-8")
        self.assertNotIn("jev-secret", text)
        secrets, _ = secret_store.read_env_secrets(self.env)
        self.assertEqual(secrets["JEV_API_KEY"], "jev-secret")

    def test_undecryptable_value_is_reported_not_raised(self):
        bad = base64.b64encode(b"other-user-blob").decode()
        self.env.write_text(f'OPENAI_API_KEY_DPAPI="{bad}"\n', encoding="utf-8")
        secrets, failed = secret_store.read_env_secrets(self.env)
        self.assertEqual(secrets["OPENAI_API_KEY"], "")
        self.assertEqual(failed, ["OPENAI_API_KEY"])
        with self.assertRaises(SecretStoreError):
            secret_store.unprotect("not base64!!")

    def test_protect_failure_becomes_oserror(self):
        def boom(data):
            raise SecretStoreError("nope")

        with mock.patch.object(secret_store, "_crypt_protect", boom):
            with self.assertRaises(OSError):
                secret_store.env_updates({"OPENAI_API_KEY": "x"})


class ControllerSecretTests(FakeDpapiTestCase):
    def test_controller_reports_decrypt_failure_without_crashing(self):
        from streaming_transcribe_translate import app_controller

        bad = base64.b64encode(b"other-user-blob").decode()
        self.env.write_text(f'OPENAI_API_KEY_DPAPI="{bad}"\n', encoding="utf-8")
        controller = app_controller.AppController.__new__(app_controller.AppController)
        controller.env_file = self.env
        controller.startup_notices = []
        config = controller._read_api_config()
        self.assertEqual(config["OPENAI_API_KEY"], "")
        self.assertEqual(
            controller.startup_notices,
            [{"title": secret_store.DECRYPT_FAILED_TITLE, "message": secret_store.DECRYPT_FAILED_MESSAGE}],
        )

    def test_controller_migrates_and_reads_plaintext_key(self):
        from streaming_transcribe_translate import app_controller

        self.env.write_text('OPENAI_API_KEY="plain"\n', encoding="utf-8")
        controller = app_controller.AppController.__new__(app_controller.AppController)
        controller.env_file = self.env
        controller.startup_notices = []
        self.assertEqual(controller._read_api_config()["OPENAI_API_KEY"], "plain")
        self.assertEqual(dotenv_values(self.env)["OPENAI_API_KEY"], "")
        self.assertEqual(controller.startup_notices, [])


@unittest.skipUnless(sys.platform == "win32", "DPAPI is Windows-only")
class RealDpapiTests(unittest.TestCase):
    def test_real_round_trip(self):
        encoded = secret_store.protect("round-trip-check")
        self.assertNotIn("round-trip-check", encoded)
        self.assertEqual(secret_store.unprotect(encoded), "round-trip-check")


if __name__ == "__main__":
    unittest.main()
