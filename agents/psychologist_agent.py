# agents/psychologist_agent.py
from .base_agent import BaseAgent

PSYCH_SYSTEM_PROMPT = (
    "You are a clinical psychologist. Return ONLY a single valid JSON object (no extra text) with these keys when applicable:\n"
    "summary (short paragraph), findings (array), abnormal_values (object, may be empty), major_problem, condition, severity (low/medium/high), likely_conditions (array), recommended_tests (array), recommended_treatments (array), recommendations (array), next_steps (array), patient_actions (array), explanation (short paragraph), evidence (array), confidence (low/medium/high).\n"
    "Provide detail: for `abnormal_values` include measurement and brief interpretation if present. For recommended tests/treatments optionally include a short `rationale`. Include `explanation` and `evidence` (1-3 short excerpts). If a field does not apply, use empty arrays or strings. Return JSON only. Example:\n"
    "{\"summary\": \"Short summary\", \"findings\": [\"insomnia\"], \"abnormal_values\": {}, \"major_problem\": \"Possible depression\", \"condition\": \"Major depressive disorder (probable)\", \"severity\": \"medium\", \"likely_conditions\": [\"Depression\"], \"recommended_tests\": [\"PHQ-9\"], \"recommended_treatments\": [\"Begin CBT\"], \"recommendations\": [\"Consider antidepressant if severe\"], \"next_steps\": [\"Refer to mental health services\"], \"patient_actions\": [\"Seek safe, supportive help\"], \"explanation\": \"Screening scores and reported symptoms suggest possible major depression\", \"evidence\": [\"Patient reports 2 weeks of low mood\"], \"confidence\": \"medium\"}"
)


class PsychologistAgent(BaseAgent):
    def __init__(self):
        super().__init__("Psychologist", PSYCH_SYSTEM_PROMPT)
 
