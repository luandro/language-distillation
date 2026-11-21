"""Marúbo (mzr) NLLB-200 600M + LoRA Inference Engine.

Loads facebook/nllb-200-distilled-600M and attaches the fine-tuned LoRA adapter
luandro/marubo-nllb-600m-lora with Panoan weight transplantation.
Supports bidirectional translation:
- Portuguese (por_Latn / pt) <-> Marúbo (mzr_Latn / mzr)
"""
import os
import re
from typing import Optional

import torch
from peft import PeftModel
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

BASE_MODEL = "facebook/nllb-200-distilled-600M"
ADAPTER_REPO = "luandro/marubo-nllb-600m-lora"
MZR_LANG = "mzr_Latn"
PT_LANG = "por_Latn"
PANO_SEED_LANG = "shp_Latn"

LANG_MAP = {
    "mzr": MZR_LANG,
    "mzr_latn": MZR_LANG,
    "marubo": MZR_LANG,
    "por": PT_LANG,
    "por_latn": PT_LANG,
    "pt": PT_LANG,
    "portuguese": PT_LANG,
    "português": PT_LANG,
}


def normalize_lang_code(code: str) -> str:
    cleaned = code.strip().lower()
    if cleaned in LANG_MAP:
        return LANG_MAP[cleaned]
    if cleaned.endswith("_latn"):
        return code.strip()
    return f"{cleaned}_Latn"


class MaruboTranslator:
    def __init__(
        self,
        base_model_name: str = BASE_MODEL,
        adapter_repo_id: str = ADAPTER_REPO,
        token: Optional[str] = None,
        device: Optional[str] = None,
    ):
        self.base_model_name = base_model_name
        self.adapter_repo_id = adapter_repo_id
        self.token = token or os.environ.get("HF_TOKEN")
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = None
        self.model = None

    def load(self):
        """Load tokenizer, base model, Panoan transfer embeddings, and LoRA adapter."""
        if self.model is not None:
            return

        print(f"Loading tokenizer from {self.adapter_repo_id}...")
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.adapter_repo_id,
                token=self.token,
            )
        except Exception as e:
            print(f"Fallback to base tokenizer due to: {e}")
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.base_model_name,
                token=self.token,
            )

        # Ensure mzr_Latn token exists
        if self.tokenizer.convert_tokens_to_ids(MZR_LANG) == self.tokenizer.unk_token_id:
            self.tokenizer.add_special_tokens({"additional_special_tokens": [MZR_LANG]})

        mzr_token_id = self.tokenizer.convert_tokens_to_ids(MZR_LANG)
        pt_token_id = self.tokenizer.convert_tokens_to_ids(PT_LANG)
        shp_token_id = self.tokenizer.convert_tokens_to_ids(PANO_SEED_LANG)
        print(f"Token IDs: mzr={mzr_token_id}, por={pt_token_id}, shp={shp_token_id}, vocab_len={len(self.tokenizer)}")

        dtype = (
            torch.bfloat16
            if (torch.cuda.is_available() and torch.cuda.is_bf16_supported())
            else torch.float16
            if torch.cuda.is_available()
            else torch.float32
        )
        print(f"Loading base model in {dtype} on {self.device}...")
        base_model = AutoModelForSeq2SeqLM.from_pretrained(
            self.base_model_name,
            dtype=dtype,
            token=self.token,
        )
        base_model.resize_token_embeddings(len(self.tokenizer))

        # Panoan phylogenetic weight transplantation: 0.75 * shp + 0.25 * por -> mzr
        with torch.no_grad():
            input_emb = base_model.get_input_embeddings().weight
            output_emb = base_model.get_output_embeddings().weight

            seed_shp_in = input_emb[shp_token_id]
            seed_por_in = input_emb[pt_token_id]
            input_emb[mzr_token_id].copy_(0.75 * seed_shp_in + 0.25 * seed_por_in)

            if output_emb.data_ptr() != input_emb.data_ptr():
                seed_shp_out = output_emb[shp_token_id]
                seed_por_out = output_emb[pt_token_id]
                output_emb[mzr_token_id].copy_(0.75 * seed_shp_out + 0.25 * seed_por_out)

        base_model.config.use_cache = True

        # Transformers 5.x compatibility shim
        if not hasattr(base_model, "_prepare_encoder_decoder_kwargs_for_generation"):
            base_model._prepare_encoder_decoder_kwargs_for_generation = getattr(
                base_model, "_prepare_text_encoder_decoder_kwargs_for_generation", None
            )

        print(f"Loading LoRA adapter from {self.adapter_repo_id}...")
        self.model = PeftModel.from_pretrained(
            base_model,
            self.adapter_repo_id,
            token=self.token,
        )
        self.model.to(self.device)
        self.model.eval()
        print("✓ Marúbo NMT Engine loaded successfully and ready for inference.")

    @torch.inference_mode()
    def translate(
        self,
        text: str,
        source_lang: str = "por_Latn",
        target_lang: str = "mzr_Latn",
        max_length: int = 256,
        max_new_tokens: int = 128,
        num_beams: int = 4,
    ) -> str:
        """Translate a single sentence between Portuguese and Marúbo."""
        if not text or not text.strip():
            return ""

        self.load()

        src = normalize_lang_code(source_lang)
        tgt = normalize_lang_code(target_lang)

        self.tokenizer.src_lang = src
        self.tokenizer.tgt_lang = tgt
        forced_bos = self.tokenizer.convert_tokens_to_ids(tgt)
        print(f"[Translate] '{text.strip()}' | {src} -> {tgt} | forced_bos={forced_bos}")

        enc = self.tokenizer(
            [text.strip()],
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=max_length,
        ).to(self.device)

        out = self.model.generate(
            **enc,
            forced_bos_token_id=forced_bos,
            max_new_tokens=max_new_tokens,
            num_beams=num_beams,
            no_repeat_ngram_size=4,
        )
        print("Generated token IDs:", out[0].tolist()[:15])

        pred = self.tokenizer.decode(out[0], skip_special_tokens=True).strip()

        # Clean music note repeat artifact if present
        if "♪" in pred:
            pred = re.sub(r"[♪\s]+", "", pred).strip()

        return pred

    @torch.inference_mode()
    def translate_batch(
        self,
        texts: list[str],
        source_lang: str = "por_Latn",
        target_lang: str = "mzr_Latn",
        batch_size: int = 8,
        num_beams: int = 4,
    ) -> list[str]:
        """Translate a batch of sentences."""
        if not texts:
            return []

        self.load()

        src = normalize_lang_code(source_lang)
        tgt = normalize_lang_code(target_lang)

        self.tokenizer.src_lang = src
        forced_bos = self.tokenizer.convert_tokens_to_ids(tgt)

        results = []
        for i in range(0, len(texts), batch_size):
            batch = [t.strip() for t in texts[i : i + batch_size]]
            enc = self.tokenizer(
                batch,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=256,
            ).to(self.device)

            out = self.model.generate(
                **enc,
                forced_bos_token_id=forced_bos,
                max_new_tokens=128,
                num_beams=num_beams,
                no_repeat_ngram_size=4,
            )
            decoded = self.tokenizer.batch_decode(out, skip_special_tokens=True)
            for d in decoded:
                cleaned = re.sub(r"[♪\s]+", "", d).strip() if "♪" in d else d.strip()
                results.append(cleaned)

        return results
