# warmup_models.py
from faster_whisper import WhisperModel
from speechbrain.inference import EncoderClassifier

print("Downloading faster-whisper tiny.en…")
WhisperModel("tiny.en", device="cpu", compute_type="int8")
print("Downloading speechbrain ECAPA…")
EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
                               run_opts={"device": "cpu"})
print("Done. Cached.")
