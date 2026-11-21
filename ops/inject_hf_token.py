"""Inject HF_TOKEN into a live colab kernel's environment without exposing it in argv.

Usage: python ops/inject_hf_token.py [session-name] [repo-root]

Reads HF_TOKEN from <repo-root>/.env (default: repo root; values may be quoted),
writes a throwaway setenv notebook to /tmp (chmod 600), runs it via `colab exec` so
the kernel process gets os.environ["HF_TOKEN"], verifies persistence with a second
exec, and deletes the temp notebook. The token never appears in shell argv, in the
training notebook, or in any committed file.
"""
import json, os, re, subprocess, sys

name = sys.argv[1] if len(sys.argv) > 1 else "mzr-finetune"
repo = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

raw = open(os.path.join(repo, ".env")).read()
m = re.search(r'HF_TOKEN\s*=\s*["\']?(hf_[A-Za-z0-9]+)', raw)
if not m:
    sys.exit("HF_TOKEN not found in .env")
tok = m.group(1)
if len(tok) != 37:
    sys.exit(f"unexpected token length {len(tok)}")

def make_nb(src, path):
    nb = {"cells": [{"cell_type": "code", "execution_count": None, "metadata": {},
                     "outputs": [], "source": src.splitlines(keepends=True)}],
          "metadata": {"colab": {"provenance": []},
                       "kernelspec": {"name": "python3", "display_name": "Python 3"},
                       "language_info": {"name": "python"}},
          "nbformat": 4, "nbformat_minor": 0}
    with open(path, "w") as f:
        json.dump(nb, f, indent=2)
    os.chmod(path, 0o600)

setenv_path = f"/tmp/setenv_token_{name}.ipynb"
verify_path = f"/tmp/verify_env_{name}.ipynb"
make_nb(f'import os\nos.environ["HF_TOKEN"] = "{tok}"\n'
        f'print("setenv ok:", len(os.environ["HF_TOKEN"]))\n', setenv_path)
make_nb('import os\nt = os.environ.get("HF_TOKEN")\n'
        'print("verify: HF_TOKEN visible:", t is not None, "len:", len(t) if t else 0)\n',
        verify_path)
try:
    r1 = subprocess.run(["colab", "exec", "-s", name, "-f", setenv_path],
                        capture_output=True, text=True, timeout=120)
    print(next((l for l in r1.stdout.splitlines() if "setenv" in l), r1.stdout[-300:]))
    r2 = subprocess.run(["colab", "exec", "-s", name, "-f", verify_path],
                        capture_output=True, text=True, timeout=120)
    print(next((l for l in r2.stdout.splitlines() if "verify" in l), r2.stdout[-300:]))
    if "HF_TOKEN visible: True" not in r2.stdout:
        sys.exit("token did not persist across exec calls")
    print("HF token injected into kernel env.")
finally:
    for p in (setenv_path, verify_path):
        if os.path.exists(p):
            os.remove(p)
