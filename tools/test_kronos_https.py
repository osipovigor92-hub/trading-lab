"""Offline gateway parser/transaction fixtures; no real Nginx or privileged calls."""
import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("kronos_https_fixture", ROOT / "integrations/kronos/configure-https.py")
HTTPS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = HTTPS
SPEC.loader.exec_module(HTTPS)

ORIGINAL = '''worker_processes 1;
pid /run/trading-lab-https.pid;
events { worker_connections 1024; }
http {
    server {
        listen 0.0.0.0:8443 ssl;
        ssl_certificate /etc/trading-lab-https/cert.pem;
        ssl_certificate_key /etc/trading-lab-https/key.pem;
        auth_basic "Trading Lab";
        auth_basic_user_file /etc/trading-lab-https/users;
        location / {
            limit_except GET {
                deny all;
            }
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            proxy_read_timeout 45s;
            proxy_pass http://127.0.0.1:8787;
            proxy_set_header Host "127.0.0.1:8787";
            proxy_set_header X-Forwarded-Proto $scheme;
        }
    }
}
'''


class ConfigurationTests(unittest.TestCase):
    def test_exact_clone_changes_only_method_guard_and_preserves_original_bytes(self):
        updated = HTTPS.forecast_configuration(ORIGINAL)
        self.assertEqual(updated.count("limit_except GET {"), 1)
        self.assertEqual(updated.count("limit_except GET POST {"), 1)
        self.assertEqual(updated.count("location = /api/kronos/forecast"), 1)
        self.assertEqual(updated.count('auth_basic "Trading Lab";'), 1)
        self.assertEqual(updated.count("auth_basic_user_file"), 1)
        self.assertEqual(updated.count('proxy_set_header Connection "";'), 2)
        self.assertEqual(updated.count("proxy_read_timeout 45s;"), 2)
        self.assertEqual(updated.count('proxy_set_header Host "127.0.0.1:8787";'), 2)
        start = updated.index(HTTPS.MARKER)
        end = updated.index("location / {", start)
        self.assertEqual(updated[:start] + updated[end:], ORIGINAL)
        self.assertEqual(HTTPS.forecast_configuration(updated), updated)

    def test_braces_semicolons_comments_quotes_and_variables_are_values(self):
        source = ORIGINAL.replace('proxy_read_timeout 45s;', '''# { } location = /api/kronos/forecast { malicious; }
            proxy_set_header X-Fixture "{;#}";
            proxy_set_header X-Closing "}";
            proxy_set_header X-Semicolon ";";
            proxy_set_header X-Escape "escaped \\\"quote\\\" and \\\\ slash";
            proxy_set_header X-Variable ${scheme};
            proxy_read_timeout 45s;''')
        updated = HTTPS.forecast_configuration(source)
        self.assertEqual(HTTPS.forecast_configuration(updated), updated)
        for header in ('X-Fixture "{;#}"', 'X-Closing "}"', 'X-Semicolon ";"', 'X-Variable ${scheme}'):
            self.assertEqual(updated.count(header), 2)

    def test_crlf_is_preserved_and_idempotent(self):
        source = ORIGINAL.replace("\n", "\r\n")
        updated = HTTPS.forecast_configuration(source)
        self.assertNotIn("\n", updated.replace("\r\n", ""))
        self.assertEqual(HTTPS.forecast_configuration(updated), updated)

    def test_unknown_route_rules_and_access_overrides_fail_closed(self):
        additions = [
            "rewrite ^ /index.html;", "return 403;", "include /tmp/routes.conf;",
            "if ($request_method = POST) { return 403; }", "auth_basic off;",
            "proxy_method GET;", "proxy_set_body '';", "allow all;",
        ]
        for addition in additions:
            with self.subTest(addition=addition), self.assertRaises(HTTPS.ConfigError):
                HTTPS.forecast_configuration(ORIGINAL.replace("proxy_http_version 1.1;", addition))

    def test_no_other_location_can_have_its_acl_overridden(self):
        for location in ("location /api/ { deny all; }", "location ~ ^/api/ { deny all; }",
                         "location = /other { return 403; }", "location /api/kronos/forecast { deny all; }"):
            with self.subTest(location=location), self.assertRaises(HTTPS.ConfigError):
                HTTPS.forecast_configuration(ORIGINAL.replace("location / {", location + "\n        location / {"))

    def test_existing_forecast_with_different_rules_or_without_helper_marker_is_refused(self):
        updated = HTTPS.forecast_configuration(ORIGINAL)
        cases = [updated.replace("GET POST", "GET"), updated.replace(HTTPS.MARKER, "# manual route"),
                 updated.replace("proxy_read_timeout 45s;", "proxy_read_timeout 30s;", 1)]
        for source in cases:
            with self.subTest(source=source), self.assertRaises(HTTPS.ConfigError):
                HTTPS.forecast_configuration(source)

    def test_root_guard_requires_get_only_deny_all_exactly(self):
        for guard in ("limit_except GET POST", "limit_except POST", 'limit_except "GET"'):
            with self.subTest(guard=guard), self.assertRaises(HTTPS.ConfigError):
                HTTPS.forecast_configuration(ORIGINAL.replace("limit_except GET", guard))
        for access in ("deny 127.0.0.1;", "allow all; deny all;", "deny all; deny all;"):
            with self.subTest(access=access), self.assertRaises(HTTPS.ConfigError):
                HTTPS.forecast_configuration(ORIGINAL.replace("deny all;", access))

    def test_server_auth_listen_loopback_host_and_hidden_config_are_required(self):
        cases = [ORIGINAL.replace('auth_basic "Trading Lab";', "auth_basic off;"),
                 ORIGINAL.replace('auth_basic "Trading Lab";', 'auth_basic "$host";'),
                 ORIGINAL.replace("auth_basic_user_file /etc/trading-lab-https/users;", ""),
                 ORIGINAL.replace("auth_basic_user_file /etc/trading-lab-https/users;", "auth_basic_user_file /tmp/users;"),
                 ORIGINAL.replace("0.0.0.0:8443 ssl", "0.0.0.0:8443"),
                 ORIGINAL.replace("0.0.0.0:8443 ssl", "127.0.0.1:8443 ssl"),
                 ORIGINAL.replace("http://127.0.0.1:8787", "http://example.com:8787"),
                 ORIGINAL.replace('Host "127.0.0.1:8787"', "Host $host"),
                 ORIGINAL.replace("http {", "include /tmp/server.conf;\nhttp {"),
                 ORIGINAL.replace("http {", "http { include /tmp/server.conf;"),
                 ORIGINAL.replace('auth_basic "Trading Lab";', 'include /tmp/access.conf; auth_basic "Trading Lab";')]
        for source in cases:
            with self.subTest(source=source), self.assertRaises(HTTPS.ConfigError):
                HTTPS.forecast_configuration(source)

    def test_request_headers_bodies_and_control_header_cannot_be_removed(self):
        for rule in ("proxy_pass_request_headers off;", "proxy_pass_request_body off;",
                     'proxy_set_header X-Lab-Control "";', "proxy_set_header X-Lab-Control fixture-secret;"):
            with self.subTest(rule=rule), self.assertRaises(HTTPS.ConfigError):
                HTTPS.forecast_configuration(ORIGINAL.replace("proxy_http_version 1.1;", rule))
        for context in ("http {", "server {"):
            for rule in ("proxy_pass_request_headers off;", "proxy_pass_request_body off;", "proxy_method GET;", "proxy_set_body '';"):
                with self.subTest(context=context, rule=rule), self.assertRaises(HTTPS.ConfigError):
                    HTTPS.forecast_configuration(ORIGINAL.replace(context, context + " " + rule))
        allowed = ORIGINAL.replace("proxy_http_version 1.1;", "proxy_pass_request_headers on; proxy_pass_request_body on; proxy_set_header X-Lab-Control $http_x_lab_control;")
        self.assertIn("GET POST", HTTPS.forecast_configuration(allowed))
        overridden = ORIGINAL.replace("http {", "http { proxy_pass_request_headers off;").replace("proxy_http_version 1.1;", "proxy_pass_request_headers on;")
        self.assertIn("GET POST", HTTPS.forecast_configuration(overridden))

    def test_ancestor_access_rules_cannot_bypass_basic_auth(self):
        for context in ("http {", "server {"):
            source = ORIGINAL.replace(context, context + " satisfy any; allow all;")
            with self.subTest(context=context), self.assertRaises(HTTPS.ConfigError):
                HTTPS.forecast_configuration(source)
        allowed = ORIGINAL.replace("http {", "http { satisfy all;")
        self.assertIn("GET POST", HTTPS.forecast_configuration(allowed))

    def test_duplicate_servers_roots_headers_or_methods_are_refused(self):
        duplicate_server = ORIGINAL[ORIGINAL.index("    server {"):ORIGINAL.rfind("}\n")]
        cases = [ORIGINAL.replace("http {", "http {\n" + duplicate_server),
                 ORIGINAL.replace("location / {", "location / {}\n        location / {"),
                 ORIGINAL.replace('proxy_set_header Host "127.0.0.1:8787";', 'proxy_set_header Host "127.0.0.1:8787"; proxy_set_header Host $host;'),
                 ORIGINAL.replace("limit_except GET {", "limit_except GET { deny all; } limit_except GET {")]
        for source in cases:
            with self.subTest(source=source), self.assertRaises(HTTPS.ConfigError):
                HTTPS.forecast_configuration(source)

    def test_malformed_configuration_is_rejected_without_content_in_error(self):
        for source in (ORIGINAL[:-3], ORIGINAL + "}", ORIGINAL + 'unfinished "private-fixture',
                       ORIGINAL + "private-fixture\\", ORIGINAL + "\x00"):
            with self.subTest(source=source), self.assertRaises(HTTPS.ConfigError) as caught:
                HTTPS.forecast_configuration(source)
            self.assertNotIn("private-fixture", str(caught.exception))


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kronos-https-fixture-")
        self.base = Path(self.temp.name).resolve()
        self.config = self.base / "nginx.conf"
        self.config.write_bytes(ORIGINAL.encode("utf-8"))
        self.config.chmod(0o640)
        self.metadata = self.config.stat()
        self.calls = []
        self.owner_patch = mock.patch.object(HTTPS.os, "fchown", create=True)
        self.owners = self.owner_patch.start()

    def tearDown(self):
        self.owner_patch.stop()
        self.temp.cleanup()

    def runner(self, command, **options):
        self.assertEqual(command[0], "/usr/sbin/nginx")
        self.assertEqual(command[-2:], ["-c", str(self.config)])
        self.assertEqual(options, {"capture_output": True, "timeout": 15, "check": False})
        self.calls.append((command, self.config.read_bytes()))
        return subprocess.CompletedProcess(command, 0, b"fixture", b"fixture")

    def configure(self, apply=False, runner=None):
        return HTTPS.configure(self.config, apply, runner or self.runner, root_owned=False)

    def test_check_is_default_and_never_creates_backup_or_reloads(self):
        result = self.configure()
        self.assertIn("CHECK OK", result)
        self.assertEqual(self.config.read_bytes(), ORIGINAL.encode())
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0][1], "-t")
        self.assertEqual(list(self.base.iterdir()), [self.config])

    def test_apply_validates_then_reloads_only_target_gateway_preserves_modes_and_backup(self):
        result = self.configure(apply=True)
        self.assertIn("APPLIED", result)
        self.assertEqual([entry[0][1:-2] for entry in self.calls], [["-t"], ["-t"], ["-s", "reload"]])
        self.assertEqual(self.calls[0][1], ORIGINAL.encode())
        self.assertEqual(self.calls[1][1], HTTPS.forecast_configuration(ORIGINAL).encode())
        backup, = self.base.glob(".nginx.conf.kronos-backup.*")
        self.assertEqual(backup.read_bytes(), ORIGINAL.encode())
        self.assertFalse(list(self.base.glob(".nginx.conf.kronos-new.*")))
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o640)
        self.assertEqual(self.owners.call_args_list[0].args[1:], (0, 0))
        self.assertEqual(self.owners.call_args_list[1].args[1:], (self.metadata.st_uid, self.metadata.st_gid))

    def test_second_apply_is_idempotent_and_performs_no_reload_or_extra_backup(self):
        self.configure(apply=True)
        first = self.config.read_bytes()
        backups = list(self.base.glob(".nginx.conf.kronos-backup.*"))
        self.calls.clear()
        result = self.configure(apply=True)
        self.assertIn("already verified", result)
        self.assertEqual(self.config.read_bytes(), first)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(list(self.base.glob(".nginx.conf.kronos-backup.*")), backups)

    def test_preflight_failure_writes_nothing_and_does_not_reflect_nginx_output(self):
        def failure(command, **options):
            self.runner(command, **options)
            return subprocess.CompletedProcess(command, 1, b"PRIVATE_FIXTURE", b"PRIVATE_FIXTURE")
        with self.assertRaises(HTTPS.ConfigError) as caught:
            self.configure(apply=True, runner=failure)
        self.assertNotIn("PRIVATE_FIXTURE", str(caught.exception))
        self.assertEqual(self.config.read_bytes(), ORIGINAL.encode())
        self.assertEqual(list(self.base.iterdir()), [self.config])

    def test_invalid_candidate_rolls_back_without_reloading(self):
        def failure(command, **options):
            result = self.runner(command, **options)
            if len(self.calls) == 2:
                return subprocess.CompletedProcess(command, 1)
            return result
        with self.assertRaises(HTTPS.ConfigError) as caught:
            self.configure(apply=True, runner=failure)
        self.assertIn("Original configuration restored", str(caught.exception))
        self.assertEqual(self.config.read_bytes(), ORIGINAL.encode())
        self.assertEqual([entry[0][1] for entry in self.calls], ["-t", "-t"])
        backup, = self.base.glob(".nginx.conf.kronos-backup.*")
        self.assertEqual(backup.read_bytes(), ORIGINAL.encode())
        self.assertFalse(list(self.base.glob(".nginx.conf.kronos-new.*")))
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o640)

    def test_reload_failure_restores_then_validates_and_reloads_original(self):
        def failure(command, **options):
            result = self.runner(command, **options)
            if len(self.calls) == 3:
                return subprocess.CompletedProcess(command, 1)
            return result
        with self.assertRaises(HTTPS.ConfigError) as caught:
            self.configure(apply=True, runner=failure)
        self.assertIn("Original configuration restored", str(caught.exception))
        self.assertEqual(self.config.read_bytes(), ORIGINAL.encode())
        self.assertEqual([entry[0][1:-2] for entry in self.calls], [["-t"], ["-t"], ["-s", "reload"], ["-t"], ["-s", "reload"]])
        self.assertEqual(self.calls[-1][1], ORIGINAL.encode())

    def test_rollback_reload_failure_is_reported_and_backup_retained(self):
        def failure(command, **options):
            result = self.runner(command, **options)
            if len(self.calls) in (3, 5):
                return subprocess.CompletedProcess(command, 1)
            return result
        with self.assertRaises(HTTPS.ConfigError) as caught:
            self.configure(apply=True, runner=failure)
        self.assertIn("reload could not be verified", str(caught.exception))
        self.assertEqual(self.config.read_bytes(), ORIGINAL.encode())
        self.assertEqual(len(list(self.base.glob(".nginx.conf.kronos-backup.*"))), 1)

    def test_external_change_during_preflight_is_not_overwritten(self):
        def changed(command, **options):
            result = self.runner(command, **options)
            self.config.write_bytes((ORIGINAL + "# independent change\n").encode())
            return result
        with self.assertRaises(HTTPS.ConfigError) as caught:
            self.configure(apply=True, runner=changed)
        self.assertIn("changed during preflight", str(caught.exception))
        self.assertTrue(self.config.read_text().endswith("# independent change\n"))
        self.assertFalse(list(self.base.glob(".nginx.conf.kronos-backup.*")))

    def test_symlink_configuration_is_refused_before_any_nginx_call(self):
        link = self.base / "link.conf"
        try:
            link.symlink_to(self.config)
        except OSError:
            self.skipTest("symlink creation unavailable")
        with self.assertRaises(HTTPS.ConfigError):
            HTTPS.configure(link, True, self.runner, root_owned=False)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.config.read_bytes(), ORIGINAL.encode())

    def test_nginx_timeout_is_failure_before_mutation(self):
        def timeout(command, **options):
            raise subprocess.TimeoutExpired(command, 15)
        with self.assertRaises(HTTPS.ConfigError):
            self.configure(apply=True, runner=timeout)
        self.assertEqual(self.config.read_bytes(), ORIGINAL.encode())
        self.assertFalse(list(self.base.glob(".nginx.conf.kronos-backup.*")))

    def test_interrupt_after_install_restores_original_and_keeps_private_backup(self):
        def interrupted(command, **options):
            result = self.runner(command, **options)
            if len(self.calls) == 2:
                raise KeyboardInterrupt()
            return result
        with self.assertRaises(HTTPS.ConfigError) as caught:
            self.configure(apply=True, runner=interrupted)
        self.assertIn("Original configuration restored", str(caught.exception))
        self.assertEqual(self.config.read_bytes(), ORIGINAL.encode())
        self.assertEqual(len(list(self.base.glob(".nginx.conf.kronos-backup.*"))), 1)


if __name__ == "__main__":
    unittest.main()
