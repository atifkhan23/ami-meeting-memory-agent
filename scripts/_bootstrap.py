"""Make the repo root importable when running scripts directly and set up logging."""
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
(ROOT / "logs").mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    handlers=[logging.StreamHandler(), logging.FileHandler(ROOT / "logs" / "run.log", encoding="utf-8")])
for noisy in ("httpx", "httpx2", "huggingface_hub", "urllib3", "chromadb", "sentence_transformers", "transformers"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
