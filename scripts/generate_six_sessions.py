import json
from pathlib import Path
from typing import Any, Dict, List

from scripts.llm import call_llm


# Default location for the system prompt markdown
DEFAULT_SYSTEM_PROMPT_PATH = Path("prompts/system_prompt.md")


STAGES = [
    {
        "session_id": "S1",
        "stage": "Build Trust & Assessment",
        "objective": "Build rapport, clarify goals, assess the problem, and agree on a simple tracking task.",
        "artifact_type": "Trigger/Thought Log",
        "artifact_requirements": (
            "Provide a simple log template and include exactly 2 example entries based on this case."
        ),
    },
    {
        "session_id": "S2",
        "stage": "Identifying Negative Cognitions",
        "objective": "Review the log and map situation→thought→emotion→body→behavior to identify automatic thoughts.",
        "artifact_type": "CBT Map",
        "artifact_requirements": (
            "Provide one worked CBT map example: situation, automatic thought, emotions (0-10), body sensations, behaviors."
        ),
    },
    {
        "session_id": "S3",
        "stage": "Challenging False Beliefs",
        "objective": "Reality-test distorted thoughts and generate a more balanced alternative thought.",
        "artifact_type": "Reality Test Table",
        "artifact_requirements": (
            "Provide a table-like text with: Thought, Evidence For, Evidence Against, Balanced Thought."
        ),
    },
    {
        "session_id": "S4",
        "stage": "Restructuring Cognitive Patterns",
        "objective": "Create adaptive replacement scripts and an If–Then plan for predictable triggers.",
        "artifact_type": "Replacement Script + If–Then Plan",
        "artifact_requirements": (
            "Provide a compassionate replacement script (3–5 sentences) and 2 If–Then plans tailored to this case."
        ),
    },
    {
        "session_id": "S5",
        "stage": "Behavioral Skill Building",
        "objective": "Practice coping skills and design a concrete plan for high-risk moments.",
        "artifact_type": "Skills Plan + Crisis Plan",
        "artifact_requirements": (
            "List 3 coping skills with when/how to use them, and a 3-step crisis plan."
        ),
    },
    {
        "session_id": "S6",
        "stage": "Consolidation & Termination",
        "objective": "Review gains and formalize a long-term maintenance plan and setback prevention.",
        "artifact_type": "Maintenance + Setback Prevention Plan",
        "artifact_requirements": (
            "Provide a maintenance plan (weekly goals for next 2–4 weeks) and a setback prevention checklist."
        ),
    },
]


def read_text(path: Path) -> str:
    """
    Read UTF-8 text from a file with a clear error message.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Missing prompt file: {path}\n"
            f"Create it (recommended): {DEFAULT_SYSTEM_PROMPT_PATH}"
        )
    return path.read_text(encoding="utf-8").strip()


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def safe_json_loads(text: str) -> Dict[str, Any]:
    """
    The model should output JSON only. This handles minor formatting issues safely.
    """
    text = text.strip()

    # If the model accidentally wraps JSON in code fences, strip them.
    if text.startswith("```"):
        # Remove leading/trailing fences
        lines = text.splitlines()

        # Drop first fence line (``` or ```json)
        if lines:
            lines = lines[1:]

        # Drop last fence line if present
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]

        # If first remaining line is 'json', drop it
        if lines and lines[0].strip().lower() == "json":
            lines = lines[1:]

        text = "\n".join(lines).strip()

    return json.loads(text)


def render_dialogue(dialogue: List[Dict[str, str]]) -> str:
    """
    Compact text form to pass into next session context.
    """
    out = []
    for turn in dialogue:
        role = turn["role"]
        content = turn["content"].replace("\n", " ").strip()
        out.append(f"{role}: {content}")
    return "\n".join(out)


def build_user_prompt(
    case: Dict[str, Any],
    s0_text: str,
    prior_sessions: List[Dict[str, Any]],
    stage_cfg: Dict[str, str],
) -> str:
    client_info = case.get("intake_form", {}).get("client_info", {})
    presenting_problem = case.get("intake_form", {}).get("presenting_problem", [])
    cbt_technique = case.get("cbt_technique", "")
    patterns = case.get("patterns", [])
    thought = case.get("thought", "")

    # Provide short summaries of prior generated sessions (if any)
    prior_summaries = []
    for s in prior_sessions:
        prior_summaries.append(
            {
                "session_id": s.get("session_id"),
                "stage": s.get("stage"),
                "artifact_type": (s.get("artifact") or {}).get("type"),
                "artifact_content": (s.get("artifact") or {}).get("content"),
            }
        )

    return f"""You will generate {stage_cfg["session_id"]}.

TARGET STAGE:
- session_id: {stage_cfg["session_id"]}
- stage: {stage_cfg["stage"]}
- stage_objective: {stage_cfg["objective"]}
- required_artifact_type: {stage_cfg["artifact_type"]}
- artifact_requirements: {stage_cfg["artifact_requirements"]}

CASE (CACTUS) CONTEXT:
- client_info: {json.dumps(client_info, ensure_ascii=False)}
- core_thought: {thought}
- cognitive_distortion_patterns: {json.dumps(patterns, ensure_ascii=False)}
- presenting_problem_bullets: {json.dumps(presenting_problem, ensure_ascii=False)}
- cbt_technique: {cbt_technique}
- attitude: {case.get("attitude", "")}
- original_cbt_plan: {json.dumps(case.get("cbt_plan", {}), ensure_ascii=False)}

SESSION 0 (S0) TRANSCRIPT (given, do not rewrite; use as history):
{s0_text}

PRIOR GENERATED SESSIONS (if any):
{json.dumps(prior_summaries, ensure_ascii=False, indent=2)}

INSTRUCTIONS:
- Continue the therapy naturally from S0 and prior sessions.
- Ensure the dialogue meets the formatting + turn constraints.
- End the session with the Counselor summarizing and clearly stating the artifact content.
- Output JSON ONLY matching the required schema.
"""


def generate_six_sessions(
    case_path: Path,
    out_dir: Path,
    system_prompt_path: Path = DEFAULT_SYSTEM_PROMPT_PATH,
    model: str = "gpt-4o-mini",
) -> Path:
    system_prompt = read_text(system_prompt_path)
    case = load_json(case_path)

    # Convert S0 dialogue list to text
    s0_dialogue = case.get("dialogue", [])
    s0_text = render_dialogue(s0_dialogue)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{case_path.stem}_sessions_1_6.json"

    prior_sessions: List[Dict[str, Any]] = []
    for stage_cfg in STAGES:
        user_prompt = build_user_prompt(case, s0_text, prior_sessions, stage_cfg)
        print(user_prompt)

        raw = call_llm(system_prompt, user_prompt, model=model)

        session_obj = safe_json_loads(raw)
        # print(session_obj)

        # Minimal validation
        assert session_obj["session_id"] == stage_cfg["session_id"]
        assert "dialogue" in session_obj and isinstance(session_obj["dialogue"], list)
        assert session_obj["dialogue"][0]["role"] == "Counselor"
        assert session_obj["dialogue"][-1]["role"] == "Counselor"

        prior_sessions.append(session_obj)

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "case_id": case_path.stem,
                "system_prompt_path": str(system_prompt_path),
                "s0_dialogue": s0_dialogue,
                "sessions": prior_sessions,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    return out_path

def main():
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--case-json",
        type=str,
        default="data/cases/case_00001.json",
        help="Path to a CACTUS case JSON (single-session).",
    )

    parser.add_argument(
        "--out-dir",
        type=str,
        default="data/sessions",
        help="Output directory.",
    )

    parser.add_argument(
        "--model",
        type=str,
        default="gpt-4o-mini",
    )

    parser.add_argument(
        "--system-prompt",
        type=str,
        default=str(DEFAULT_SYSTEM_PROMPT_PATH),
        help="Path to system prompt markdown file.",
    )

    args = parser.parse_args()

    out_path = generate_six_sessions(
        case_path=Path(args.case_json),
        out_dir=Path(args.out_dir),
        system_prompt_path=Path(args.system_prompt),
        model=args.model,
    )

    print(f"Wrote: {out_path}")

if __name__ == "__main__":
    main()
