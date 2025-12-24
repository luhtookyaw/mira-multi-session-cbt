### Convert Raw Cactus to Json

```python
python scripts/convert_raw_cactus.py \
  --input data/raw_cactus.jsonl \
  --output_dir data/cases
```

### Run Simplest Dialogue Generation

```python
python3 -m scripts.generate_six_sessions
```