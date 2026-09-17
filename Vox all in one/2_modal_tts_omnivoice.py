import modal
import io
import base64
from typing import Dict, Any

# Định nghĩa Docker Image cho OmniVoice TTS với Pre-download Model Weights
tts_image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("git", "ffmpeg")
    .pip_install(
        "torch",
        "torchaudio",
        "soundfile",
        "numpy",
        "fastapi",
        "pydantic",
        "git+https://github.com/k2-fsa/OmniVoice.git"
    )
    .run_commands(
        "python3 -c 'from omnivoice.models.omnivoice import OmniVoice; OmniVoice.from_pretrained(\"k2-fsa/OmniVoice\", load_asr=True, asr_model_name=\"openai/whisper-large-v3-turbo\")'"
    )
)

app = modal.App("vox-tts-omnivoice")
model_volume = modal.Volume.from_name("vox-tts-cache", create_if_missing=True)

@app.cls(
    gpu="L4",
    image=tts_image,
    volumes={"/cache": model_volume},
    scaledown_window=3600,
    max_containers=5  # Tự động mở tới 5 GPU Containers gánh 5 luồng song song!
)
class VoxTTSGenerator:
    @modal.enter()
    def load_omnivoice(self):
        import os
        import torch
        from omnivoice.models.omnivoice import OmniVoice

        os.environ["HF_HOME"] = "/cache"
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[*] Đang khởi tạo mô hình OmniVoice TTS trên thiết bị: {self.device.upper()}...")
        
        self.model = OmniVoice.from_pretrained(
            "k2-fsa/OmniVoice",
            device_map=self.device,
            dtype=torch.float16 if self.device == "cuda" else torch.float32,
            load_asr=True,
            asr_model_name="openai/whisper-large-v3-turbo"
        )
        print("[*] Nạp mô hình OmniVoice TTS thành công!")

    @modal.fastapi_endpoint(method="POST")
    def generate_tts(self, data: Dict[str, Any]):
        """
        API Endpoint sinh âm thanh TTS từ văn bản (Hỗ trợ cả Web App HTH Voice Vip & Tool GUI)
        """
        from fastapi import Response, HTTPException

        text = (data.get("text") or data.get("prompt") or "").strip()
        language = data.get("language") or data.get("lang")
        speed = float(data.get("speed", 1.0))
        num_step = int(data.get("num_step") or data.get("steps") or 48)
        ref_text = data.get("ref_text") or data.get("prompt_text")

        # Lấy Base64 từ tất cả các trường khả dĩ
        raw_b64 = (
            data.get("ref_audio_b64") or 
            data.get("ref_audio") or 
            data.get("ref_audio_base64") or 
            data.get("prompt_speech") or 
            data.get("prompt_audio") or 
            data.get("audio_prompt")
        )

        if not text:
            text = "Xin chào"

        temp_ref_path = None
        if raw_b64 and isinstance(raw_b64, str) and len(raw_b64) > 50:
            import tempfile
            try:
                # Bóc tách tiền tố Data URI nếu có (vd: data:audio/wav;base64,...)
                clean_b64 = raw_b64
                if "," in clean_b64:
                    clean_b64 = clean_b64.split(",", 1)[1]
                
                clean_b64 = clean_b64.strip().replace("\n", "").replace("\r", "")
                raw_bytes = base64.b64decode(clean_b64)

                fd, temp_ref_path = tempfile.mkstemp(suffix=".wav")
                with open(temp_ref_path, "wb") as f:
                    f.write(raw_bytes)
            except Exception as b64_err:
                print(f"[!] Warning: Không thể decode Base64 ref_audio: {b64_err}")
                temp_ref_path = None

        import time
        t_start = time.time()
        client_type = "GUI Studio (JSON)" if data.get("return_json") is True else "Web App (Binary WAV)"
        print(f"\n=======================================================")
        print(f"[VOX-TTS-MODAL] 🚀 Yêu cầu mới từ {client_type}:")
        print(f" -> Text ({len(text)} chars): \"{text[:45]}...\"")
        print(f" -> Voice: {data.get('voice_name', 'Mặc định')} | Speed: {speed}")
        print(f" -> Dynamic Base64 Audio Ref: {'Có (Đã decode)' if temp_ref_path else 'Không'}")
        print(f"-------------------------------------------------------")

        try:
            lang_val = language if language and language != "Auto" else None
            gen_kwargs = {
                "text": text,
                "language": lang_val,
                "ref_audio": temp_ref_path,
                "ref_text": ref_text if ref_text and str(ref_text).strip() else None,
                "speed": speed,
                "num_step": num_step
            }

            audio_data = self.model.generate(**gen_kwargs)

            import soundfile as sf
            # Ghi ra Buffer WAV
            buffer = io.BytesIO()
            sf.write(buffer, audio_data[0], self.model.sampling_rate, format='WAV')
            wav_bytes = buffer.getvalue()
            
            elapsed = time.time() - t_start
            audio_duration = len(audio_data[0]) / self.model.sampling_rate
            print(f"[VOX-TTS-MODAL] ✅ TẠO VOICE THÀNH CÔNG!")
            print(f" -> Thời gian GPU xử lý: {elapsed:.2f}s | Thời lượng voice: {audio_duration:.2f}s")
            print(f" -> Kích thước audio output: {len(wav_bytes)/1024:.1f} KB")
            print(f"=======================================================\n")

            # Nếu client yêu cầu JSON hoặc truyền flag return_json
            if data.get("return_json") is True:
                audio_b64 = base64.b64encode(wav_bytes).decode('utf-8')
                return {
                    "status": "success",
                    "sample_rate": self.model.sampling_rate,
                    "audio_b64": audio_b64,
                    "duration_sec": audio_duration
                }

            # Mặc định trả về Binary Stream Audio/WAV cho Web App (hth-voicevip.vercel.app)
            return Response(
                content=wav_bytes, 
                media_type="audio/wav",
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
                    "Access-Control-Allow-Headers": "*"
                }
            )

        except Exception as e:
            print(f"[VOX-TTS-MODAL] ❌ LỖI TRONG QUÁ TRÌNH TẠO TTS: {str(e)}")
            print(f"=======================================================\n")
            raise HTTPException(status_code=400, detail=f"Lỗi TTS GPU: {str(e)}")
