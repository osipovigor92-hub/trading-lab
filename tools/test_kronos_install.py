"""Linux installer control-flow fixtures. No root, pip, model or systemd calls.

Fixed paths are remapped inside a temporary test copy. Command fixtures record
privileged intent and simulate file installation under the CI user's ownership.
"""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("integrations/kronos/setup.py", "integrations/kronos/requirements.txt",
           "integrations/kronos/worker.py", "integrations/kronos/infer.py",
           "integrations/kronos/smoke.py", "src/trading-panel/kronos_client.py")
HARNESS = r'''
import json, os, pathlib, shutil, subprocess, sys
name, args = sys.argv[1], sys.argv[2:]
with open(os.environ["FIXTURE_EVENTS"], "a") as stream:
    stream.write(json.dumps({"name": name, "args": args}) + "\n")
if name == "id": print("0")
elif name == "uname": print("Linux")
elif name == "getent": print("tradingbot:x:1234:")
elif name == "runuser":
    assert args[:3] == ["-u", "tradingbot", "--"]
    sys.exit(subprocess.call(args[3:]))
elif name == "timeout":
    assert args[0] == "5s"
    sys.exit(subprocess.call(args[1:]))
elif name == "systemctl":
    assert args[0] == "daemon-reload" or args[-1] == "trading-kronos.service"
    if args[0] == "cat": sys.exit(0 if os.environ.get("FIXTURE_EXISTING") == "1" else 1)
elif name == "install":
    directories, mode, paths, i = False, None, [], 0
    while i < len(args):
        if args[i] == "-d": directories = True; i += 1
        elif args[i] in ("-o", "-g", "-m"):
            if args[i] == "-m": mode = int(args[i+1], 8)
            i += 2
        else: paths.append(pathlib.Path(args[i])); i += 1
    if directories:
        for path in paths: path.mkdir(parents=True, exist_ok=True); path.chmod(mode)
    else:
        assert len(paths) == 2
        shutil.copyfile(paths[0], paths[1]); paths[1].chmod(mode)
elif name == "python3":
    if "-c" in args:
        code = args[args.index("-c")+1]
        if "import venv, ensurepip" in code:
            if os.environ.get("FIXTURE_PREFLIGHT_FAIL") == "1":
                print("Python venv/ensurepip unavailable", file=sys.stderr); sys.exit(21)
            print("Python preflight: fixture only")
        else:
            assert "KronosClient" in code and "keys =" in code
            assert args[-2].endswith("src/trading-panel")
            print(json.dumps({"status": "unavailable" if os.environ.get("FIXTURE_STATUS_FAIL") == "1" else "loading", "enabled": os.environ.get("FIXTURE_STATUS_FAIL") != "1", "error": "fixture error" if os.environ.get("FIXTURE_STATUS_FAIL") == "1" else None}))
            if os.environ.get("FIXTURE_STATUS_FAIL") == "1": sys.exit(1)
    else:
        assert args[0] == "-B" and args[1].endswith("integrations/kronos/setup.py")
        assert args[2] == "--runtime"
        runtime = pathlib.Path(args[3])
        assert pathlib.Path.cwd() == runtime, "installer inherited an inaccessible checkout cwd"
        if os.environ.get("FIXTURE_SETUP_FAIL") == "1": sys.exit(23)
        token = runtime / "token"
        if not token.exists(): token.write_text("PRIVATE_FIXTURE_TOKEN")
        print("Setup fixture completed; no pip/model was invoked")
else: raise AssertionError(name)
'''


@unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "Linux Bash fake-command harness")
class InstallServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kronos-install-fixture-")
        self.base = Path(self.temp.name)
        self.repo, self.runtime = self.base / "checkout", self.base / "runtime"
        self.stage_root, self.logs = self.base / "stages", self.base / "logs"
        self.unit = self.base / "units/trading-kronos.service"
        self.bin, self.events = self.base / "bin", self.base / "events.jsonl"
        self.repo.mkdir(mode=0o700)
        self.logs.mkdir(); self.unit.parent.mkdir(); self.bin.mkdir()
        for source in SOURCES + ("integrations/kronos/trading-kronos.service.example",):
            target = self.repo / source
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / source, target)
        script = (ROOT / "integrations/kronos/install-service.sh").read_text(encoding="utf-8")
        for original, replacement in (("/opt/trading-kronos", self.runtime),
                  ("/var/lib/trading-kronos-install", self.stage_root),
                  ("/var/log/trading-kronos-install", self.logs / "install"),
                  ("/etc/systemd/system/trading-kronos.service", self.unit)):
            script = script.replace(original, str(replacement))
        self.script = self.repo / "integrations/kronos/install-service.sh"
        self.script.write_text(script, encoding="utf-8")
        helper = self.base / "commands.py"
        helper.write_text(HARNESS, encoding="utf-8")
        for name in ("id", "uname", "getent", "install", "systemctl", "runuser", "timeout", "python3"):
            command = self.bin / name
            command.write_text('#!/bin/sh\nexec "' + sys.executable + '" "' + str(helper) + '" "' + name + '" "$@"\n')
            command.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        FIXTURE_EVENTS=str(self.events), KRONOS_SETUP_PYTHON="python3")

    def tearDown(self):
        self.temp.cleanup()

    def run_fixture(self, **flags):
        env = dict(self.env, **{key: str(value) for key, value in flags.items()})
        result = subprocess.run([shutil.which("bash"), str(self.script)], cwd=self.repo,
                                env=env, text=True, capture_output=True, timeout=15)
        self.commands = [json.loads(line) for line in self.events.read_text().splitlines()]
        return result

    def system_actions(self):
        return [entry["args"] for entry in self.commands if entry["name"] == "systemctl"]

    def test_missing_unit_installs_exact_source_snapshot_and_only_model_service(self):
        result = self.run_fixture()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        stage = next(self.stage_root.glob("source.*"))
        self.assertEqual({str(p.relative_to(stage)) for p in stage.rglob("*") if p.is_file()}, set(SOURCES))
        for path in stage.rglob("*"):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o750 if path.is_dir() else 0o640)
        self.assertEqual(stat.S_IMODE(stage.stat().st_mode), 0o750)
        self.assertEqual(stat.S_IMODE(self.repo.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.runtime.stat().st_mode), 0o750)
        self.assertEqual(self.system_actions(), [["cat", "trading-kronos.service"], ["daemon-reload"], ["enable", "trading-kronos.service"], ["restart", "trading-kronos.service"]])
        self.assertNotIn("PRIVATE_FIXTURE_TOKEN", result.stdout)
        self.assertIn('"status": "loading"', result.stdout)
        self.assertTrue(self.unit.exists())
        self.assertEqual(stat.S_IMODE(next(self.logs.glob("install.*")).stat().st_mode), 0o600)
        setup = next(entry for entry in self.commands if entry["name"] == "runuser" and "--runtime" in entry["args"])
        self.assertEqual(setup["args"][:3], ["-u", "tradingbot", "--"])

    def test_existing_unit_stops_then_setup_failure_preserves_code_and_leaves_unit_uninstalled(self):
        result = self.run_fixture(FIXTURE_EXISTING=1, FIXTURE_SETUP_FAIL=1)
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertEqual(self.system_actions(), [["cat", "trading-kronos.service"], ["stop", "trading-kronos.service"]])
        self.assertFalse(self.unit.exists())
        self.assertEqual(len(list(self.stage_root.glob("source.*"))), 1)
        self.assertIn("failed (exit 23)", result.stdout)
        self.assertIn("Worker may remain stopped", result.stdout)

    def test_preflight_failure_never_stops_or_mutates_runtime(self):
        result = self.run_fixture(FIXTURE_EXISTING=1, FIXTURE_PREFLIGHT_FAIL=1)
        self.assertEqual(result.returncode, 21)
        self.assertEqual(self.system_actions(), [])
        self.assertFalse(self.runtime.exists())
        self.assertFalse(self.stage_root.exists())

    def test_unavailable_actual_status_is_failure_after_restart_not_success(self):
        result = self.run_fixture(FIXTURE_STATUS_FAIL=1)
        self.assertEqual(result.returncode, 1)
        self.assertIn('"status": "unavailable"', result.stdout)
        self.assertIn("fixture error", result.stdout)
        self.assertNotIn("installation command completed", result.stdout)

    def test_runtime_symlink_is_refused_before_setup(self):
        target = self.base / "unrelated"
        target.mkdir()
        self.runtime.symlink_to(target, target_is_directory=True)
        result = self.run_fixture()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing symlink", result.stdout)
        self.assertFalse(self.unit.exists())
        self.assertEqual(list(target.iterdir()), [])
        self.assertFalse(any(entry["name"] == "runuser" for entry in self.commands))


if __name__ == "__main__":
    unittest.main()
