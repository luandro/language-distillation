"""Generate baseline translations for the frozen mzr benchmark v2 (standalone; GPU/Colab or CPU).

Needs torch, transformers, peft, sentencepiece. Does NOT import langpipe, so it runs on a bare
Colab VM. Scoring is done elsewhere (`scripts/eval_baselines_v2.py report`).

Systems
- ``zero_shot``: facebook/nllb-200-distilled-600M, mzr_Latn added as an additional special token
  and its embedding initialised exactly as scripts/train_nllb_lora.py and deploy/marubo_nllb.py do:
  input row = 0.75 * shp_Latn + 0.25 * por_Latn; output row copied likewise only if the output
  matrix is not tied to the input one. No adapter.
- ``old_adapter``: the same base + init, then the published LoRA adapter
  luandro/marubo-nllb-600m-lora loaded as deploy/marubo_nllb.py does (tokenizer from the adapter
  repo, fallback to base; HF_TOKEN from the environment, never printed).

Input: JSON list of {"id", "mzr", "por"} (`eval_baselines_v2.py prepare` writes it).
Output: JSON {"system", "meta", "predictions": {"por->mzr": {id: hyp}, "mzr->por": {id: hyp}}}.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

BASE_MODEL = "facebook/nllb-200-distilled-600M"
ADAPTER_REPO = "luandro/marubo-nllb-600m-lora"
MZR, POR, SHP = "mzr_Latn", "por_Latn", "shp_Latn"
DIRS = {"por->mzr": (POR, MZR, "por"), "mzr->por": (MZR, POR, "mzr")}


def load_model(system: str, device: str) -> tuple[Any, Any, dict[str, Any]]:
    import torch
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    token = os.environ.get("HF_TOKEN") or None
    tok = None
    if system == "old_adapter":
        try:
            tok = AutoTokenizer.from_pretrained(ADAPTER_REPO, token=token)
        except Exception as exc:  # same fallback as deploy/marubo_nllb.py
            print(f"adapter tokenizer unavailable, using base: {type(exc).__name__}")
    if tok is None:
        tok = AutoTokenizer.from_pretrained(BASE_MODEL, token=token)
    if tok.convert_tokens_to_ids(MZR) == tok.unk_token_id:
        tok.add_special_tokens({"additional_special_tokens": [MZR]})
    mzr_id, por_id, shp_id = (tok.convert_tokens_to_ids(t) for t in (MZR, POR, SHP))
    dtype = torch.float16 if device == "cuda" else torch.float32
    model = AutoModelForSeq2SeqLM.from_pretrained(BASE_MODEL, torch_dtype=dtype, token=token)
    model.resize_token_embeddings(len(tok))
    tied = True
    with torch.no_grad():
        inp = model.get_input_embeddings().weight
        out = model.get_output_embeddings().weight
        inp[mzr_id].copy_(0.75 * inp[shp_id] + 0.25 * inp[por_id])
        if out.data_ptr() != inp.data_ptr():
            tied = False
            out[mzr_id].copy_(0.75 * out[shp_id] + 0.25 * out[por_id])
    if system == "old_adapter":
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, ADAPTER_REPO, token=token)
    model.to(device).eval()
    meta = {
        "base_model": BASE_MODEL,
        "adapter": ADAPTER_REPO if system == "old_adapter" else None,
        "mzr_token_id": mzr_id,
        "por_token_id": por_id,
        "shp_token_id": shp_id,
        "vocab_len": len(tok),
        "mzr_init": "0.75*shp_Latn + 0.25*por_Latn (input row; output row too if untied)",
        "output_embedding_tied": tied,
        "dtype": str(dtype),
        "device": device,
    }
    return tok, model, meta


def generate(
    tok: Any, model: Any, rows: list[dict[str, str]], direction: str, beams: int, bs: int
) -> dict[str, str]:
    import torch

    src_lang, tgt_lang, side = DIRS[direction]
    forced = tok.convert_tokens_to_ids(tgt_lang)
    order = sorted(range(len(rows)), key=lambda i: len(rows[i][side]))
    preds: dict[str, str] = {}
    with torch.inference_mode():
        for start in range(0, len(order), bs):
            batch = [rows[i] for i in order[start : start + bs]]
            tok.src_lang = src_lang
            enc = tok(
                [r[side] for r in batch],
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=256,
            ).to(model.device)
            out = model.generate(
                **enc, forced_bos_token_id=forced, max_new_tokens=128, num_beams=beams
            )
            for r, h in zip(batch, tok.batch_decode(out, skip_special_tokens=True), strict=True):
                preds[r["id"]] = h
            print(f"  {direction}: {len(preds)}/{len(rows)}", flush=True)
    return preds


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--system", required=True, choices=["zero_shot", "old_adapter"])
    ap.add_argument("--inputs", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--beams", type=int, default=4)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0, help="first N rows only (timing probe)")
    ap.add_argument("--directions", nargs="+", default=list(DIRS), choices=list(DIRS))
    args = ap.parse_args()

    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    rows = json.loads(args.inputs.read_text(encoding="utf-8"))
    if args.limit:
        rows = rows[: args.limit]
    t0 = time.time()
    tok, model, meta = load_model(args.system, device)
    meta.update(
        num_beams=args.beams, max_new_tokens=128, batch_size=args.batch_size, n_rows=len(rows)
    )
    meta["load_seconds"] = round(time.time() - t0, 1)
    preds: dict[str, dict[str, str]] = {}
    for d in args.directions:
        t1 = time.time()
        preds[d] = generate(tok, model, rows, d, args.beams, args.batch_size)
        meta[f"seconds_{d}"] = round(time.time() - t1, 1)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"system": args.system, "meta": meta, "predictions": preds}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
