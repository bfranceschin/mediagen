"""Profile-safe path regression tests; optional read-only OAuth smoke test.

Run outside the checkout, with no HERMES_AGENT_DIR or PYTHONPATH:
  HERMES_HOME=<profile> MEDIAGEN_TEST_LIVE=1 <Hermes venv python> -I -B <this file>
Only the opt-in live test contacts xAI, using GET /models (never generation).
"""
import ast
import builtins
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).with_name("mediagen.py")
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("mediagen_auth_test_target", SCRIPT)
mediagen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mediagen)


class PathResolutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = self.root / "custom" / "profiles" / "media-maker"
        self.user = self.root / "user"
        self.prefix = self.root / "installation" / "venv"

    def checkout(self, path):
        (path / "hermes_cli").mkdir(parents=True)
        (path / "hermes_cli" / "__init__.py").touch()
        return path

    def resolve(self, override=None, installed=None):
        env = {} if override is None else {"HERMES_AGENT_DIR": str(override)}
        spec = None if installed is None else type("Spec", (), {"origin": str(installed / "hermes_cli/__init__.py")})()
        with patch.dict(os.environ, env, clear=True), patch.object(mediagen, "HERMES_HOME", self.profile), patch.object(Path, "home", return_value=self.user), patch.object(sys, "prefix", str(self.prefix)), patch("importlib.util.find_spec", return_value=spec):
            return mediagen._resolve_hermes_agent_dir()

    def test_explicit_override_is_authoritative(self):
        self.checkout(self.profile.parent.parent / "hermes-agent")
        self.assertEqual(self.resolve(self.root / "explicit-missing"), self.root / "explicit-missing")

    def test_profile_checkout_precedes_shared(self):
        local = self.checkout(self.profile / "hermes-agent")
        self.checkout(self.profile.parent.parent / "hermes-agent")
        self.assertEqual(self.resolve(), local)

    def test_named_profile_finds_its_base_installation(self):
        shared = self.checkout(self.profile.parent.parent / "hermes-agent")
        self.assertEqual(self.resolve(), shared)

    def test_default_shared_installation(self):
        shared = self.checkout(self.user / ".hermes" / "hermes-agent")
        self.assertEqual(self.resolve(), shared)

    def test_installed_package_location(self):
        installed = self.checkout(self.root / "editable")
        self.assertEqual(self.resolve(installed=installed), installed)

    def test_venv_sibling_workspace(self):
        workspace = self.checkout(self.prefix.parent / "workspace")
        self.assertEqual(self.resolve(), workspace)

    def test_invalid_checkout_reports_code_not_credentials(self):
        with patch.object(mediagen, "HERMES_AGENT_DIR", self.root / "missing"):
            with self.assertRaisesRegex(RuntimeError, "Hermes source checkout not found"):
                mediagen.resolve_xai_credentials()

    def test_import_failure_is_not_missing_oauth(self):
        original = builtins.__import__
        def blocked(name, *args, **kwargs):
            if name in {"tools.xai_http", "hermes_cli.auth"}:
                raise ModuleNotFoundError("sensitive exception text must not leak", name="pm")
            return original(name, *args, **kwargs)
        with patch.object(mediagen, "_ensure_hermes_on_path"), patch("builtins.__import__", side_effect=blocked):
            for loader in (mediagen._try_xai_http_credentials, mediagen._try_xai_oauth_runtime_credentials):
                with self.assertRaisesRegex(RuntimeError, "module: pm") as caught:
                    loader()
                self.assertNotIn("sensitive exception text", str(caught.exception))

    def test_api_key_still_requires_opt_in(self):
        api = {"provider": "xai", "api_key": "unit-test-placeholder", "base_url": "https://api.x.ai/v1"}
        with patch.object(mediagen, "_try_xai_http_credentials", return_value=api), patch.object(mediagen, "_try_xai_oauth_runtime_credentials", return_value=None):
            self.assertEqual(mediagen.resolve_xai_credentials(), {})
            self.assertEqual(mediagen.resolve_xai_credentials(allow_api_key=True)["provider"], "xai")


@unittest.skipUnless(os.environ.get("MEDIAGEN_TEST_LIVE") == "1", "read-only live OAuth test not requested")
class LiveOAuthTests(unittest.TestCase):
    def test_profile_oauth_and_read_only_models(self):
        self.assertNotIn("HERMES_AGENT_DIR", os.environ)
        self.assertNotIn("PYTHONPATH", os.environ)
        self.assertEqual(mediagen.HERMES_HOME, Path(os.environ["HERMES_HOME"]).expanduser())
        self.assertFalse(Path.cwd().is_relative_to(mediagen.HERMES_AGENT_DIR.resolve()))
        creds = mediagen.require_xai_credentials(allow_api_key=False)
        self.assertEqual(creds.get("provider"), "xai-oauth")
        self.assertTrue(creds.get("api_key"))
        # Verify the helper still reads the active profile, not the shared home.
        from hermes_cli.config import get_hermes_home
        self.assertEqual(Path(get_hermes_home()), mediagen.HERMES_HOME)
        import httpx
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            response = client.get(creds["base_url"] + "/models", headers=mediagen._xai_headers(creds["api_key"]))
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json().get("data"), list)
        print("LIVE: provider=xai-oauth; credential_present=True; GET /models=200; profile_preserved=True")


if __name__ == "__main__":
    unittest.main(verbosity=2)
