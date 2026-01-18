import json
from scripts.llm import call_llm

CCD_SYSTEM_PROMPT = """
You are an expert CBT case formulator.
Extract a DiaCBT-style Cognitive Conceptualization Diagram (CCD) with EXACTLY 6 keys:
- Situation (string)
- Automatic_Thoughts (list of strings)
- Emotions (list of strings)
- Behaviors (list of strings)
- Intermediate_Beliefs (list of strings; "if...then...", "must/should..." rules)
- Core_Beliefs (list of strings; deep global beliefs about self/others/world)

Rules:
- Use only information supported by the provided case. If uncertain, infer conservatively.
- Output VALID JSON ONLY. No markdown. No extra keys. No comments.
""".strip()


def extract_ccd(case_dict: dict, model: str = "gpt-4o-mini") -> dict:
    user_prompt = (
        "Convert this CACTUS case into a DiaCBT-style CCD.\n\n"
        f"CACTUS_CASE_JSON:\n{json.dumps(case_dict, ensure_ascii=False)}"
    )

    raw = call_llm(
        system_prompt=CCD_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model=model,
    )

    # Parse JSON strictly
    try:
        ccd = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Model did not return valid JSON.\nRaw output:\n{raw}") from e

    # Validate keys
    required = {
        "Situation",
        "Automatic_Thoughts",
        "Emotions",
        "Behaviors",
        "Intermediate_Beliefs",
        "Core_Beliefs",
    }
    if set(ccd.keys()) != required:
        raise ValueError(f"CCD keys mismatch.\nGot keys: {set(ccd.keys())}\nCCD:\n{ccd}")

    return ccd


if __name__ == "__main__":
    # Example: load your case from a file
    # Put your CACTUS case JSON into cactus_case.json
    with open("data/cases/case_00001.json", "r", encoding="utf-8") as f:
        case = json.load(f)

    ccd = extract_ccd(case)
    print(json.dumps(ccd, ensure_ascii=False, indent=2))
