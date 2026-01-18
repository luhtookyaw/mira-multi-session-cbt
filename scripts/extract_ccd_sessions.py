# extract_ccd_sessions.py
# Usage:
#   python extract_ccd_sessions.py \
#     --input data/sessions/case_00001_sessions_1_6.json \
#     --output outputs/case_00001_ccd_by_session.json \
#     --model gpt-4o-mini

import argparse
import json
import os
import time
from typing import Any, Dict, List, Optional

from scripts.llm import call_llm


REQUIRED_KEYS = {
    "Situation",
    "Automatic_Thoughts",
    "Emotions",
    "Behaviors",
    "Intermediate_Beliefs",
    "Core_Beliefs",
}

CCD_EXTRACTION_SYSTEM = """
You are an expert CBT case formulator.
Your task: Extract a DiaCBT-style Cognitive Conceptualization Diagram (CCD) from the CLIENT utterances only.

Return EXACTLY these 6 JSON keys (no extra keys, no markdown, no commentary):
- Situation: string
- Automatic_Thoughts: array of strings
- Emotions: array of strings
- Behaviors: array of strings
- Intermediate_Beliefs: array of strings (rules/assumptions: "if...then...", "must/should...")
- Core_Beliefs: array of strings (deep global beliefs about self/others/world)

Rules:
- Use only information supported by the provided client utterances.
- If uncertain, infer conservatively (avoid over-specific claims).
- Output MUST be valid JSON with exactly the 6 keys above.
""".strip()


def load_text_if_exists(path: Optional[str]) -> str:
    if not path:
        return ""
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""


def collect_client_utterances(dialogue: List[Dict[str, Any]]) -> List[str]:
    """Extract client-only messages from a dialogue list."""
    out = []
    for turn in dialogue:
        if (turn.get("role") or "").lower() == "client":
            content = (turn.get("content") or "").strip()
            if content:
                out.append(content)
    return out


def strict_parse_ccd(raw: str) -> Dict[str, Any]:
    """Parse JSON and validate exact CCD keys."""
    ccd = json.loads(raw)
    if not isinstance(ccd, dict):
        raise ValueError("CCD is not a JSON object.")
    if set(ccd.keys()) != REQUIRED_KEYS:
        raise ValueError(f"CCD keys mismatch. Got: {set(ccd.keys())}")
    return ccd


def extract_ccd_from_text(
    client_text: str,
    model: str,
    system_prompt_prefix: str = "",
    retries: int = 2,
    sleep_s: float = 0.8,
) -> Dict[str, Any]:
    """
    Call LLM and force valid CCD JSON. Retries with a repair instruction if needed.
    """
    system_prompt = (system_prompt_prefix + "\n\n" + CCD_EXTRACTION_SYSTEM).strip() if system_prompt_prefix else CCD_EXTRACTION_SYSTEM

    user_prompt = (
        "Extract the CCD from these CLIENT utterances.\n"
        "CLIENT_UTTERANCES:\n"
        f"{client_text}\n"
    )

    last_err = None
    for attempt in range(retries + 1):
        raw = call_llm(system_prompt=system_prompt, user_prompt=user_prompt, model=model)

        try:
            return strict_parse_ccd(raw)
        except Exception as e:
            last_err = e
            time.sleep(sleep_s * (attempt + 1))

            # Repair prompt
            user_prompt = (
                "Your previous output was invalid.\n"
                "Return ONLY valid JSON with EXACTLY these keys:\n"
                "Situation, Automatic_Thoughts, Emotions, Behaviors, Intermediate_Beliefs, Core_Beliefs.\n"
                "No extra keys. No markdown.\n\n"
                "CLIENT_UTTERANCES:\n"
                f"{client_text}\n"
            )

    raise RuntimeError(f"Failed to extract CCD after retries. Last error: {last_err}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to case JSON (e.g., data/sessions/case_00001_sessions_1_6.json)")
    parser.add_argument("--output", required=True, help="Path to output JSON file")
    parser.add_argument("--model", default="gpt-4o-mini", help="Model name (default: gpt-4o-mini)")
    parser.add_argument("--use_cumulative", action="store_true",
                        help="If set, each session CCD uses ALL prior client utterances up to that session (recommended). "
                             "If not set, uses only that session's client utterances.")
    parser.add_argument("--include_s0", action="store_true",
                        help="If set, include s0_dialogue client utterances as baseline evidence.")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        case = json.load(f)

    case_id = case.get("case_id", os.path.splitext(os.path.basename(args.input))[0])
    system_prompt_path = case.get("system_prompt_path")
    system_prompt_prefix = load_text_if_exists(system_prompt_path)

    # Baseline utterances (optional)
    s0_client = []
    if args.include_s0 and isinstance(case.get("s0_dialogue"), list):
        s0_client = collect_client_utterances(case["s0_dialogue"])

    results: Dict[str, Any] = {
        "case_id": case_id,
        "model": args.model,
        "system_prompt_path": system_prompt_path,
        "use_cumulative": bool(args.use_cumulative),
        "include_s0": bool(args.include_s0),
        "sessions": []
    }

    cumulative: List[str] = list(s0_client)

    sessions = case.get("sessions", [])
    if not isinstance(sessions, list):
        raise ValueError("Input JSON has no 'sessions' list.")

    for sess in sessions:
        session_id = sess.get("session_id", "UNKNOWN")
        dialogue = sess.get("dialogue", [])
        if not isinstance(dialogue, list):
            dialogue = []

        client_utts = collect_client_utterances(dialogue)

        if args.use_cumulative:
            evidence_list = cumulative + client_utts
        else:
            evidence_list = client_utts

        # Build a compact text evidence block
        client_text = "\n".join([f"- {u}" for u in evidence_list]) if evidence_list else "- (no client utterances found)"

        try:
            ccd = extract_ccd_from_text(
                client_text=client_text,
                model=args.model,
                system_prompt_prefix=system_prompt_prefix,
            )
            status = "ok"
            err = None
        except Exception as e:
            ccd = None
            status = "fail"
            err = str(e)

        results["sessions"].append({
            "session_id": session_id,
            "stage": sess.get("stage"),
            "stage_objective": sess.get("stage_objective"),
            "client_utterances_count": len(client_utts),
            "evidence_utterances_count": len(evidence_list),
            "ccd": ccd,
            "status": status,
            "error": err,
        })

        # Update cumulative AFTER extraction (so S1 includes s0 if enabled, etc.)
        cumulative.extend(client_utts)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
