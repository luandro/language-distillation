"""Upload exported datasets and model card to live Colab VM.

Usage: python ops/stage_data.py [session-name]
"""
import os, subprocess, sys

name = sys.argv[1] if len(sys.argv) > 1 else "mzr-finetune"
repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

files = [
    ("exports/mzr/datasets/train.hf.jsonl", "/content/exports/mzr/datasets/train.hf.jsonl"),
    ("exports/mzr/datasets/val.hf.jsonl", "/content/exports/mzr/datasets/val.hf.jsonl"),
    ("exports/mzr/datasets/test.hf.jsonl", "/content/exports/mzr/datasets/test.hf.jsonl"),
    ("exports/mzr/datasets/manifest.json", "/content/exports/mzr/datasets/manifest.json"),
    ("exports/mzr/MODEL_CARD.md", "/content/exports/mzr/MODEL_CARD.md"),
]

# Ensure remote directories exist first via a one-shot exec
setup_src = "import os\nos.makedirs('/content/exports/mzr/datasets', exist_ok=True)\nprint('Remote dirs created.')"
import json
setup_path = f"/tmp/setup_dirs_{name}.ipynb"
nb = {"cells": [{"cell_type": "code", "execution_count": None, "metadata": {},
                 "outputs": [], "source": setup_src.splitlines(keepends=True)}],
      "metadata": {"colab": {"provenance": []},
                   "kernelspec": {"name": "python3", "display_name": "Python 3"},
                   "language_info": {"name": "python"}},
      "nbformat": 4, "nbformat_minor": 0}
with open(setup_path, "w") as f:
    json.dump(nb, f, indent=2)

print("Preparing remote directories...")
r = subprocess.run(["colab", "exec", "-s", name, "-f", setup_path], capture_output=True, text=True, timeout=120)
print(r.stdout.strip())
if os.path.exists(setup_path):
    os.remove(setup_path)

for local_rel, remote_abs in files:
    local_abs = os.path.join(repo, local_rel)
    if not os.path.exists(local_abs):
        print(f"Warning: {local_abs} not found locally.")
        continue
    size_mb = os.path.getsize(local_abs) / (1024 * 1024)
    print(f"Uploading {local_rel} ({size_mb:.2f} MB) -> {remote_abs} ...")
    cmd = ["colab", "upload", "-s", name, local_abs, remote_abs]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        print(f"Upload failed for {local_rel}: {r.stderr}")
    else:
        print(f"✓ Uploaded {local_rel}")

print("\nAll data files staged successfully.")
