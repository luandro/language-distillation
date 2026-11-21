"""Inspect training state on Drive from a live colab session.

Usage: python ops/check_drive_state.py [session-name]

Runs a one-shot exec that prints OUTPUT_DIR entries, per-checkpoint validity
(trainer_state global_step, adapter size), manifest presence, and GPU name.
Used for preflight (must be clean/fresh or known valid checkpoint) and after VM reclamations.
"""
import json, subprocess, sys

name = sys.argv[1] if len(sys.argv) > 1 else "mzr-finetune"
src = '''import os, glob, json
d = "/content/drive/MyDrive/marubo-nllb-600m-lora"
print("drive mounted:", os.path.ismount("/content/drive"))
print("target exists:", os.path.isdir(d))
if os.path.isdir(d):
    print("entries:", sorted(os.listdir(d)))
    for c in sorted(glob.glob(d + "/checkpoint-*"), key=lambda p: int(p.rsplit("-", 1)[1])):
        st = os.path.join(c, "trainer_state.json")
        gs = json.load(open(st)).get("global_step") if os.path.exists(st) else None
        ap = os.path.join(c, "adapter_model.safetensors")
        ok = os.path.exists(ap) and os.path.getsize(ap) > 1e6
        print(os.path.basename(c), "state_step:", gs, "adapter_ok:", ok)
    print("manifest:", os.path.exists(os.path.join(d, "run_manifest.json")))
import torch
print("device:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "NO GPU")
'''
path = f"/tmp/check_drive_state_{name}.ipynb"
nb = {"cells": [{"cell_type": "code", "execution_count": None, "metadata": {},
                 "outputs": [], "source": src.splitlines(keepends=True)}],
      "metadata": {"colab": {"provenance": []},
                   "kernelspec": {"name": "python3", "display_name": "Python 3"},
                   "language_info": {"name": "python"}},
      "nbformat": 4, "nbformat_minor": 0}
with open(path, "w") as f:
    json.dump(nb, f, indent=2)
r = subprocess.run(["colab", "exec", "-s", name, "-f", path],
                   capture_output=True, text=True, timeout=300)
for line in r.stdout.splitlines():
    if not line.startswith("[colab]"):
        print(line)
