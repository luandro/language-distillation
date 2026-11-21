"""Modal deployment for Marúbo (mzr) Neural Machine Translation API.

Deploys facebook/nllb-200-distilled-600M + luandro/marubo-nllb-600m-lora
on a T4 GPU instance, exposing a fast, public FastAPI endpoint with CORS.
"""
import os
import modal

DEPLOY_DIR = os.path.dirname(os.path.abspath(__file__))

app = modal.App("marubo-translation")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "torch",
        "transformers>=4.45.0",
        "peft>=0.12.0",
        "sentencepiece>=0.2",
        "torchao>=0.16.0",
        "accelerate>=0.29.0",
        "huggingface_hub>=0.23.0",
        "safetensors",
        "fastapi[standard]>=0.115.0",
        "pydantic",
    )
    .add_local_file(
        os.path.join(DEPLOY_DIR, "marubo_nllb.py"),
        "/root/marubo_nllb.py",
    )
)


@app.cls(
    image=image,
    gpu="T4",
    secrets=[modal.Secret.from_name("marubo-secrets")],
    timeout=120,
    scaledown_window=300,
)
class MaruboTranslatorService:
    @modal.enter()
    def setup(self):
        import marubo_nllb
        self.engine = marubo_nllb.MaruboTranslator(
            token=os.environ.get("HF_TOKEN"),
            device="cuda",
        )
        self.engine.load()

    @modal.method()
    def translate(self, text: str, source: str = "por", target: str = "mzr") -> str:
        return self.engine.translate(text=text, source_lang=source, target_lang=target)

    @modal.asgi_app()
    def web(self):
        from fastapi import FastAPI, HTTPException
        from fastapi.middleware.cors import CORSMiddleware
        from pydantic import BaseModel, Field

        web_app = FastAPI(
            title="Marúbo NMT API",
            description="Fine-tuned NLLB-200 600M LoRA Translation API between Portuguese (por) and Marúbo (mzr)",
            version="1.0.0",
        )

        web_app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        class TranslationRequest(BaseModel):
            text: str = Field(..., description="Text to translate", example="O menino vê o peixe no rio.")
            source: str = Field(default="por", description="Source language ('por', 'pt', 'mzr')")
            target: str = Field(default="mzr", description="Target language ('mzr', 'por', 'pt')")
            num_beams: int = Field(default=4, ge=1, le=5, description="Beam search width")

        class TranslationResponse(BaseModel):
            source: str
            target: str
            input_text: str
            translation: str
            model: str

        @web_app.get("/")
        @web_app.get("/health")
        def health():
            return {
                "status": "healthy",
                "model": "luandro/marubo-nllb-600m-lora",
                "base_model": "facebook/nllb-200-distilled-600M",
                "supported_directions": ["por_Latn -> mzr_Latn", "mzr_Latn -> por_Latn"],
                "provider": "Modal",
            }

        @web_app.post("/translate", response_model=TranslationResponse)
        def translate_endpoint(req: TranslationRequest):
            if not req.text or not req.text.strip():
                raise HTTPException(status_code=400, detail="Empty text provided.")

            pred = self.engine.translate(
                text=req.text,
                source_lang=req.source,
                target_lang=req.target,
                num_beams=req.num_beams,
            )
            return TranslationResponse(
                source=req.source,
                target=req.target,
                input_text=req.text,
                translation=pred,
                model="luandro/marubo-nllb-600m-lora",
            )

        return web_app


@app.local_entrypoint()
def main(text: str = "O menino vê o peixe no rio.", source: str = "por", target: str = "mzr"):
    service = MaruboTranslatorService()
    result = service.translate.remote(text, source=source, target=target)
    print(f"\n[Test Result] ({source} -> {target}):\n  Input:       {text}\n  Translation: {result}\n")
