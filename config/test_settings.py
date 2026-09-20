import json
import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

BASE_DIR = Path(settings.BASE_DIR)

PROBE = (
    "import json, django.conf as c; from config import settings as s; "
    "print(json.dumps({k: getattr(s, k, None) for k in ("
    "'DEBUG','ALLOWED_HOSTS','CSRF_TRUSTED_ORIGINS','SECURE_SSL_REDIRECT','SECURE_PROXY_SSL_HEADER',"
    "'SESSION_COOKIE_SECURE','CSRF_COOKIE_SECURE','SECURE_HSTS_SECONDS','WSGI_APPLICATION','STATIC_ROOT')}, default=str))"
)


def load_settings(**env):
    """Ayarları ayrı süreçte, verilen ortam değişkenleriyle içe aktarır (.env'in karışmaması için boş değerler verilir)."""
    full_env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "PYTHONPATH": str(BASE_DIR),
        "DJANGO_SECRET_KEY": "",
        "DJANGO_DEBUG": "",
        "DJANGO_ALLOWED_HOSTS": "",
        "DJANGO_CSRF_TRUSTED_ORIGINS": "",
        "DATABASE_URL": "",
        "DATABASE_URL_DIRECT": "",
        "VOTER_KEY_SALT": "",
    }
    full_env.update(env)
    return subprocess.run(
        [sys.executable, "-c", PROBE], env=full_env, cwd=BASE_DIR, capture_output=True, text=True
    )


class ProductionSettingsTests(SimpleTestCase):
    def production(self, **overrides):
        env = {
            "DJANGO_DEBUG": "False",
            "DJANGO_SECRET_KEY": "test-only",
            "DJANGO_ALLOWED_HOSTS": ".vercel.app",
            "DJANGO_CSRF_TRUSTED_ORIGINS": "https://kararsizim.vercel.app",
            "VOTER_KEY_SALT": "test-salt",
        }
        env.update(overrides)
        result = load_settings(**env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_security_flags_on_when_debug_off(self):
        s = self.production()
        self.assertFalse(s["DEBUG"])
        self.assertTrue(s["SECURE_SSL_REDIRECT"])
        self.assertEqual(s["SECURE_PROXY_SSL_HEADER"], ["HTTP_X_FORWARDED_PROTO", "https"])
        self.assertTrue(s["SESSION_COOKIE_SECURE"])
        self.assertTrue(s["CSRF_COOKIE_SECURE"])
        self.assertGreater(s["SECURE_HSTS_SECONDS"], 0)

    def test_hosts_and_origins_come_from_environment(self):
        s = self.production()
        self.assertEqual(s["ALLOWED_HOSTS"], [".vercel.app"])
        self.assertEqual(s["CSRF_TRUSTED_ORIGINS"], ["https://kararsizim.vercel.app"])

    def test_vercel_entrypoint_settings_present(self):
        s = self.production()
        self.assertEqual(s["WSGI_APPLICATION"], "config.wsgi.application")
        self.assertTrue(s["STATIC_ROOT"].endswith("staticfiles"))

    def test_security_flags_off_in_development(self):
        s = self.production(DJANGO_DEBUG="True", DJANGO_SECRET_KEY="")
        self.assertTrue(s["DEBUG"])
        self.assertFalse(s["SECURE_SSL_REDIRECT"])
        self.assertFalse(s["SESSION_COOKIE_SECURE"])
        self.assertFalse(s["CSRF_COOKIE_SECURE"])

    def test_production_refuses_to_start_without_secret_key(self):
        result = load_settings(DJANGO_DEBUG="False", DJANGO_SECRET_KEY="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY", result.stderr)

    def test_debug_defaults_to_false(self):
        result = load_settings(DJANGO_SECRET_KEY="x")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout.strip().splitlines()[-1])["DEBUG"])


class VercelFilesTests(SimpleTestCase):
    def test_vercel_json_is_minimal_and_points_to_real_file(self):
        config = json.loads((BASE_DIR / "vercel.json").read_text(encoding="utf-8"))
        self.assertEqual(set(config), {"$schema", "regions", "functions"})
        self.assertEqual(config["regions"], ["fra1"])
        for path in config["functions"]:
            self.assertTrue((BASE_DIR / path).is_file(), path)

    def test_no_legacy_vercel_wrappers(self):
        self.assertFalse((BASE_DIR / "api").exists())
        config = (BASE_DIR / "vercel.json").read_text(encoding="utf-8")
        for legacy in ('"builds"', '"routes"', '"rewrites"'):
            self.assertNotIn(legacy, config)

    def test_python_version_is_pinned_and_compatible_with_django(self):
        version = (BASE_DIR / ".python-version").read_text(encoding="utf-8").strip()
        major, minor = (int(part) for part in version.split(".")[:2])
        self.assertGreaterEqual((major, minor), (3, 12))

    def test_requirements_only_hold_runtime_dependencies(self):
        lines = [line.split("==")[0].split("[")[0].lower() for line in
                 (BASE_DIR / "requirements.txt").read_text(encoding="utf-8").split() if line]
        self.assertEqual(sorted(lines), ["dj-database-url", "django", "psycopg", "python-dotenv", "whitenoise"])

    def test_env_example_lists_every_setting_variable(self):
        example = (BASE_DIR / ".env.example").read_text(encoding="utf-8")
        for name in ("DJANGO_SECRET_KEY", "DJANGO_DEBUG", "DJANGO_ALLOWED_HOSTS", "DJANGO_CSRF_TRUSTED_ORIGINS",
                     "VOTER_KEY_SALT", "DATABASE_URL", "DATABASE_URL_DIRECT"):
            self.assertIn(name, example)

    def test_secrets_are_not_tracked(self):
        ignore = (BASE_DIR / ".gitignore").read_text(encoding="utf-8")
        for pattern in (".env", ".env.local", ".vercel/", "staticfiles/", "db.sqlite3"):
            self.assertIn(pattern, ignore)
