# Runbook — Marúbo NLLB-200 600M Fine-Tuning on Google Colab

Complete operational guide for launching, authenticating, training, and monitoring `marubo-nllb-600m-lora` via the `colab` CLI.

---

## 1. Preflight Checklist & System Status

- **Colab CLI**: Installed at `/home/luandro/.local/bin/colab`.
- **Colab Balance**: >300 compute units available (`colab usage`).
- **Hugging Face Token**: Write token present in `.env` (`HF_TOKEN="hf_..."`).
- **Target Hub Repository**: `luandro/marubo-nllb-600m-lora` (private).
- **Dataset Manifest**: 5,518 unique pairs (10,988 bidirectional instances):
  - Train: 4,725 pairs (4,701 human-attested + 24 Clef synthetic) -> 9,402 bidirectional pairs.
  - Val: 543 pairs (100% human gold truth: 25 Cesarino oral + 518 ScriptureEarth) -> 1,086 bidirectional pairs.
  - Test: 250 pairs (100% human gold truth: 50 Cesarino oral + 200 ScriptureEarth) -> 500 bidirectional pairs.
  - Cryptographic verification: SHA-256 verified in `exports/mzr/datasets/manifest.json`.

---

## 2. Step-by-Step Launch Sequence

### Step 1: Provision Colab GPU Session
```bash
colab new -s mzr-finetune --gpu T4
```

### Step 2: Mount Google Drive Headlessly
Run the Drive mount script with the Colab CLI venv python:
```bash
~/.local/share/uv/tools/google-colab-cli/bin/python -u ops/drive_mount.py mzr-finetune
```
*Note: A consent URL will be printed and written to `/tmp/drive_auth_url_mzr-finetune.txt`. Click "Allow" in your browser.*

### Step 3: Check Drive Training State
Verify Drive storage is mounted and clean:
```bash
python3 ops/check_drive_state.py mzr-finetune
```

### Step 4: Inject HF_TOKEN into Kernel Environment
Inject the write token into the kernel without exposing it in shell arguments or committed files:
```bash
python3 ops/inject_hf_token.py mzr-finetune
```

### Step 5: Stage Verified Datasets & Model Card
Upload dataset partitions directly to the session VM:
```bash
python3 ops/stage_data.py mzr-finetune
```

### Step 6: Launch Background Training Execution
Launch notebook execution in the background with persistent logging:
```bash
nohup colab exec -s mzr-finetune \
  -f notebooks/Marubo_NLLB_600M_Finetune.ipynb \
  --timeout 68400 > /tmp/mzr_finetune.log 2>&1 & echo $! > /tmp/mzr_finetune.pid
```

---

## 3. Monitoring & Polling Strategy (Every 30 Minutes)

Monitor training progress headlessly using log inspection (handling carriage returns from `tqdm`):

```bash
tr '\r' '\n' < /tmp/mzr_finetune.log | grep -aE "Executing cell|Loss|Saving|chrF|BLEU|MATCH|Uploaded|Traceback" | tail -n 25
```

### Heartbeat Checks:
1. **Log Activity Check**:
   ```bash
   stat -c %y /tmp/mzr_finetune.log
   ```
   If timestamp has updated within the last 5 minutes, training is active.
2. **Session Liveness**:
   ```bash
   colab sessions
   ```
3. **Drive Checkpoint Verification**:
   ```bash
   python3 ops/check_drive_state.py mzr-finetune
   ```

---

## 4. Post-Training Hub Verification & Teardown

1. Verify published repository on Hugging Face:
   - URL: `https://huggingface.co/luandro/marubo-nllb-600m-lora`
   - Files: `adapter_model.safetensors`, `adapter_config.json`, `tokenizer.json`, `README.md`, `evaluation_predictions.jsonl`, `evaluation_results.json`, `hub_publish.json`.
2. Stop the Colab session to avoid billing idle compute units:
   ```bash
   colab stop -s mzr-finetune
   ```
