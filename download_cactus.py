import json
import os
from datasets import load_dataset
from tqdm import tqdm

# ==============================
# CONFIG
# ==============================
DATASET_ID = "LangAGI-Lab/cactus"   # change if your paper uses a different repo
SPLIT = "train"
DATA_DIR = "data"
OUTPUT_PATH = os.path.join(DATA_DIR, "raw_cactus.jsonl")

# ==============================
# PREPARE OUTPUT DIR
# ==============================
os.makedirs(DATA_DIR, exist_ok=True)

# ==============================
# LOAD DATASET
# ==============================
print(f"Loading dataset: {DATASET_ID} ({SPLIT})")
dataset = load_dataset(DATASET_ID, split=SPLIT)

print(f"Total samples: {len(dataset)}")

# ==============================
# EXPORT TO JSONL
# ==============================
print(f"Exporting to {OUTPUT_PATH}")

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    for sample in tqdm(dataset):
        json.dump(sample, f, ensure_ascii=False)
        f.write("\n")

print("Export completed successfully.")
