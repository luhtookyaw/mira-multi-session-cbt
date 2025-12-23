# scripts/convert_raw_cactus.py
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple


# ---------------------------
# Helpers
# ---------------------------

def _clean(s: str) -> str:
    return re.sub(r"[ \t]+", " ", s.strip())


def _split_lines(s: str) -> List[str]:
    # Keep non-empty lines, stripped
    return [_clean(x) for x in s.splitlines() if _clean(x)]


def _parse_kv_pairs(lines: List[str]) -> Dict[str, str]:
    """
    Parses lines like:
        Name:
        Brooke Davis
        Age:
        41
    or sometimes:
        Name: Brooke Davis
    into a dict.
    """
    out: Dict[str, str] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        # "Key:" alone
        if line.endswith(":") and len(line) > 1:
            key = line[:-1].strip()
            val = ""
            if i + 1 < len(lines) and not lines[i + 1].endswith(":"):
                val = lines[i + 1].strip()
                i += 1
            out[key] = val
        # "Key: Value" same line
        elif ":" in line:
            key, val = line.split(":", 1)
            out[key.strip()] = val.strip()
        i += 1
    return out


def _coerce_age(v: str) -> Any:
    try:
        return int(v)
    except Exception:
        return v


def _parse_intake_form(text: str) -> Dict[str, Any]:
    """
    Turns the raw intake multi-section text into the target structure:
      client_info (dict)
      presenting_problem (list[str])
      reason_for_seeking_counseling (str)
      past_history (list[str])
      academic_occupational_functioning_level (list[str])
      social_support_system (str)
    """
    lines = _split_lines(text)

    # Split into numbered sections (2., 3., 4., 5., 6.)
    # Everything before "2." is treated as client info block.
    section_pat = re.compile(r"^(\d+)\.\s*(.+)$")
    sections: List[Tuple[int, str, List[str]]] = []

    cur_num = None
    cur_title = None
    cur_buf: List[str] = []
    preamble: List[str] = []

    i = 0
    while i < len(lines):
        m = section_pat.match(lines[i])
        if m:
            # flush previous
            if cur_num is not None:
                sections.append((cur_num, cur_title or "", cur_buf))
            else:
                preamble = preamble + cur_buf
            cur_num = int(m.group(1))
            cur_title = m.group(2)
            cur_buf = []
        else:
            if cur_num is None:
                preamble.append(lines[i])
            else:
                cur_buf.append(lines[i])
        i += 1

    if cur_num is not None:
        sections.append((cur_num, cur_title or "", cur_buf))

    # --- client_info from preamble
    kv = _parse_kv_pairs(preamble)
    client_info = {
        "name": kv.get("Name", kv.get("name", "")) or "",
        "age": _coerce_age(kv.get("Age", kv.get("age", "")) or ""),
        "gender": kv.get("Gender", kv.get("gender", "")) or "",
        "occupation": kv.get("Occupation", kv.get("occupation", "")) or "",
        "education": kv.get("Education", kv.get("education", "")) or "",
        "marital_status": kv.get("Marital Status", kv.get("marital_status", "")) or "",
        "family_details": kv.get("Family Details", kv.get("family_details", "")) or "",
    }

    # --- map other sections by section number (most consistent in your format)
    def collect_sentences(block_lines: List[str]) -> List[str]:
        # Treat each line as a bullet-like sentence (your raw data already has one sentence per line)
        return [x for x in block_lines if x]

    presenting_problem: List[str] = []
    reason_for_seeking = ""
    past_history: List[str] = []
    academic_occ: List[str] = []
    social_support = ""

    for num, _title, block in sections:
        if num == 2:
            presenting_problem = collect_sentences(block)
        elif num == 3:
            # usually single paragraph/line(s)
            reason_for_seeking = " ".join(block).strip()
        elif num == 4:
            past_history = collect_sentences(block)
        elif num == 5:
            academic_occ = collect_sentences(block)
        elif num == 6:
            social_support = " ".join(block).strip()

    return {
        "client_info": client_info,
        "presenting_problem": presenting_problem,
        "reason_for_seeking_counseling": reason_for_seeking,
        "past_history": past_history,
        "academic_occupational_functioning_level": academic_occ,
        "social_support_system": social_support,
    }


def _parse_cbt_plan(text: str) -> Dict[str, str]:
    """
    Input:
      "Decatastrophizing\n\nCounseling plan:\n1. ...\n2. ...\n..."
    Output:
      {"1": "...", "2": "...", ...}
    """
    lines = _split_lines(text)

    # Find numbered items like "1. ..."
    item_pat = re.compile(r"^(\d+)\.\s*(.+)$")

    out: Dict[str, str] = {}
    cur_key = None
    cur_val: List[str] = []

    for line in lines:
        m = item_pat.match(line)
        if m:
            if cur_key is not None:
                out[cur_key] = _clean(" ".join(cur_val))
            cur_key = m.group(1)
            cur_val = [m.group(2)]
        else:
            # Skip obvious headers
            low = line.lower()
            if low in {"counseling plan:", "counseling plan", "plan:", "counseling plan:"}:
                continue
            # If we haven't started items yet, ignore technique title lines
            if cur_key is None:
                continue
            cur_val.append(line)

    if cur_key is not None:
        out[cur_key] = _clean(" ".join(cur_val))

    return out


def _parse_dialogue(text: str) -> List[Dict[str, str]]:
    """
    Input:
      "Counselor: ...\nClient: ...\nCounselor: ..."
    Output:
      [{"role":"Counselor","content":"..."}, ...]
    """
    lines = _split_lines(text)
    out: List[Dict[str, str]] = []

    # Allow roles like Counselor/Client/Therapist/Patient etc.
    role_pat = re.compile(r"^([A-Za-z][A-Za-z \-_/]+):\s*(.*)$")

    cur_role = None
    cur_content: List[str] = []

    def flush():
        nonlocal cur_role, cur_content
        if cur_role is not None and cur_content:
            out.append({"role": cur_role, "content": _clean(" ".join(cur_content))})
        cur_role = None
        cur_content = []

    for line in lines:
        m = role_pat.match(line)
        if m:
            flush()
            cur_role = m.group(1).strip()
            first = m.group(2).strip()
            cur_content = [first] if first else []
        else:
            # continuation line
            if cur_role is None:
                # if malformed, treat as narrator/unknown
                cur_role = "Unknown"
            cur_content.append(line)

    flush()
    return out


def transform_sample(raw: Dict[str, Any]) -> Dict[str, Any]:
    intake_raw = raw.get("intake_form", "") or ""
    plan_raw = raw.get("cbt_plan", "") or ""
    dialogue_raw = raw.get("dialogue", "") or ""

    return {
        "thought": raw.get("thought", ""),
        "patterns": raw.get("patterns", []),
        "intake_form": _parse_intake_form(intake_raw) if isinstance(intake_raw, str) else intake_raw,
        "cbt_technique": raw.get("cbt_technique", ""),
        "cbt_plan": _parse_cbt_plan(plan_raw) if isinstance(plan_raw, str) else plan_raw,
        "attitude": raw.get("attitude", ""),
        "dialogue": _parse_dialogue(dialogue_raw) if isinstance(dialogue_raw, str) else dialogue_raw,
    }


# ---------------------------
# CLI
# ---------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/raw_cactus.jsonl", help="Path to raw_cactus.jsonl")
    ap.add_argument("--output_dir", default="data/cases", help="Directory to write case_XXXXX.json")
    ap.add_argument("--start_index", type=int, default=1, help="First case number (default 1)")
    ap.add_argument("--zero_pad", type=int, default=5, help="Zero padding digits (default 5 => 00001)")
    args = ap.parse_args()

    in_path = Path(args.input)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    n = 0
    with in_path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as e:
                raise SystemExit(f"[ERROR] JSON decode error at line {line_no}: {e}") from e

            case = transform_sample(raw)
            case_id = args.start_index + n
            fname = f"case_{case_id:0{args.zero_pad}d}.json"
            (out_dir / fname).write_text(json.dumps(case, ensure_ascii=False, indent=4), encoding="utf-8")
            n += 1

    print(f"Done. Wrote {n} cases to: {out_dir.resolve()}")


if __name__ == "__main__":
    main()
