"""Explicit optional setup: isolated venv, pinned official source and weights.

Does not run third-party model code, start services, or touch existing trading
units/state. Run this script deliberately; the panel never invokes an installer.
"""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from urllib.request import Request, build_opener, ProxyHandler
import venv

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src/trading-panel"))
from kronos_client import CODE_REVISION, MODEL, MODEL_REVISION, TOKENIZER, TOKENIZER_REVISION

WEIGHTS = {
    "model": (MODEL, MODEL_REVISION, "a7d5f37e2e9fbd9891f7d7d4f72574512dd1f704fee14223e0a8cd0fbf54197c"),
    "tokenizer": (TOKENIZER, TOKENIZER_REVISION, "b97ec46b3b72160509e289183eaf7bdf5f0dac5bb9b49522f6d46638a99a8717"),
}


def download(url, path, *, expected=None, limit=64 * 1024 * 1024):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".download")
    digest, size = hashlib.sha256(), 0
    # Only fixed public URLs; credentials are never sent. HTTPS handles the
    # official Hugging Face signed CDN redirects for .safetensors downloads.
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(Request(url, headers={"User-Agent": "trading-lab-kronos-setup/1"}), timeout=60) as stream, temp.open("wb") as out:
            if not stream.geturl().startswith("https://"):
                raise ValueError("Download left HTTPS")
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(block)
                if size > limit:
                    raise ValueError("Oversized official download")
                digest.update(block)
                out.write(block)
        if expected and digest.hexdigest() != expected:
            raise ValueError("Official weight SHA256 does not match")
        os.replace(temp, path)
        return digest.hexdigest()
    finally:
        if temp.exists():
            temp.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    args = parser.parse_args()
    if not (3, 10) <= sys.version_info[:2] <= (3, 12):
        raise SystemExit("Use Python 3.10-3.12 for this pinned CPU runtime")
    runtime = args.runtime.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    # Never replace a credential silently; repeated setup keeps the local token.
    token = runtime / "token"
    if not token.exists():
        fd = os.open(token, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write(secrets.token_urlsafe(32))
    if os.name == "nt":
        # Windows ignores POSIX file modes. Restrict this credential explicitly
        # to its installing account and SYSTEM; never print its value.
        subprocess.run(["icacls", str(token), "/inheritance:r", "/grant:r",
                        getpass.getuser() + ":F", "*S-1-5-18:F"], check=True, stdout=subprocess.DEVNULL)
    else:
        os.chmod(token, 0o600)
    venv_dir = runtime / ".venv"
    if not venv_dir.exists():
        venv.EnvBuilder(with_pip=True).create(venv_dir)
    python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "--only-binary=:all:",
                    "--index-url", "https://download.pytorch.org/whl/cpu", "torch==2.8.0"], check=True)
    subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "--only-binary=:all:",
                    "--index-url", "https://pypi.org/simple", "-r", str(HERE / "requirements.txt")], check=True)
    files = {}
    for name in ("model/__init__.py", "model/kronos.py", "model/module.py", "LICENSE"):
        relative = "vendor/" + name
        files[relative] = download("https://raw.githubusercontent.com/shiyu-coder/Kronos/" + CODE_REVISION + "/" + name,
                                   runtime / relative, limit=128 * 1024)
    for kind, (repo, revision, digest) in WEIGHTS.items():
        for name in ("config.json", "model.safetensors"):
            relative = "weights/" + kind + "/" + name
            files[relative] = download("https://huggingface.co/" + repo + "/resolve/" + revision + "/" + name,
                        runtime / relative, expected=digest if name.endswith(".safetensors") else None,
                        limit=64 * 1024 if name == "config.json" else 32 * 1024 * 1024)
    app = runtime / "app"
    app.mkdir(exist_ok=True)
    for name in ("worker.py", "infer.py", "smoke.py"):
        shutil.copyfile(HERE / name, app / name)
    shutil.copyfile(HERE.parents[1] / "src/trading-panel/kronos_client.py", app / "kronos_client.py")
    manifest = dict(code_revision=CODE_REVISION, model=MODEL, model_revision=MODEL_REVISION,
                    tokenizer=TOKENIZER, tokenizer_revision=TOKENIZER_REVISION, files=files,
                    python=sys.version, torch="2.8.0 CPU", dependencies=(HERE / "requirements.txt").read_text())
    (runtime / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Installed optional CPU runtime:", runtime)
    print("No services started. Start:", python, "-u", app / "worker.py", "--runtime", runtime)


if __name__ == "__main__":
    main()
