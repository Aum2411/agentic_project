# agents/base_agent.py
import json
import logging
from typing import Dict, List
from utils.preprocessing import clean_text  # not used but kept for reference

logger = logging.getLogger(__name__)

class BaseAgent:
    """Base class for agents. Each agent provides a system prompt and uses LLMClient.chat."""

    def __init__(self, name: str, system_prompt: str):
        self.name = name
        self.system_prompt = system_prompt

    def analyze(self, text: str, llm_client) -> Dict:
        """
        Run the agent on `text` using the provided LLM client.
        The LLM is asked to return JSON; if parsing fails we return the raw string under 'raw'.
        """
        user_prompt = (
            "Please analyze the patient report below and return a JSON object with keys:\n"
            "  - patient_name (string, if available, else 'Unknown')\n"
            "  - summary (short text)\n"
                "  - likely_conditions (array of short strings)\n"
                "  - recommendations (array of short strings)\n"
                "  - confidence (one of low/medium/high)\n"
                "  - focus (one-line description of what this specialist focuses on)\n\n"
            "Respond with JSON only.\n\nReport:\n"
            f"{text}"
        )
        try:
            raw = llm_client.chat(self.system_prompt, user_prompt)
            # Try to parse JSON if LLM adhered to instructions
            parsed = None
            try:
                parsed = json.loads(raw)
            except Exception:
                # Sometimes LLM wraps in text. Try to find first JSON substring:
                import re
                m = re.search(r"\{.*\}", raw, flags=re.DOTALL)
                if m:
                    try:
                        parsed = json.loads(m.group(0))
                    except Exception:
                        parsed = None

            if isinstance(parsed, dict):
                return self._normalize(parsed)
            else:
                # If the LLM returned a clarifying question or an unavailable message,
                # produce a deterministic structured fallback instead of returning the clarifier text.
                if isinstance(raw, str) and (raw.strip().startswith("(LLM unavailable)") or "Could you share" in raw or "clarify" in raw.lower()):
                    # Build a simple fallback structured response from the input text.
                    try:
                        from utils.preprocessing import clean_text as _clean
                        body = _clean(text)[:1000]
                    except Exception:
                        body = text[:1000]

                    # simple keyword-based likely conditions extraction
                    keywords = [
                        'fever','cough','chest pain','shortness of breath','dyspnea','palpitation',
                        'rash','itching','abdominal pain','diarrhea','constipation','headache',
                        'fatigue','weight loss','weight gain','polyuria','polydipsia','hematuria',
                        'anemia','elevated','low','high','creatinine','bilirubin','hb','wbc'
                    ]
                    low = (body or '').lower()
                    found = []
                    for kw in keywords:
                        if kw in low and kw not in found:
                            found.append(kw)

                    # Basic recommendations tailored by agent name
                    recs = []
                    name_lower = (self.name or '').lower()
                    if 'cardio' in name_lower:
                        recs = ['Obtain ECG', 'Consider echocardiography if cardiac cause suspected', 'Refer to cardiology for further evaluation']
                    elif 'pulmo' in name_lower or 'pulmon' in name_lower:
                        recs = ['Obtain chest X-ray', 'Consider spirometry', 'Refer to pulmonology if respiratory symptoms persist']
                    elif 'psych' in name_lower:
                        recs = ['Consider assessment for anxiety/depression', 'Refer to psychiatry for further evaluation']
                    elif 'derm' in name_lower:
                        recs = ['Consider dermatology consult', 'Photograph lesions and consider topical/systemic therapy based on severity']
                    elif 'hema' in name_lower or 'hemat' in name_lower:
                        recs = ['Repeat CBC with differential', 'Review peripheral smear and consider hematology referral if abnormalities persist']
                    elif 'neph' in name_lower:
                        recs = ['Check renal function (serum creatinine, electrolytes)', 'Urinalysis and urine protein quantification', 'Refer to nephrology if abnormal']
                    elif 'radio' in name_lower:
                        recs = ['Obtain relevant imaging and share imaging reports with radiology for formal read']
                    else:
                        recs = ['Obtain relevant investigations and refer to appropriate specialist as needed']

                    # Build a richer deterministic fallback with standard keys
                    # keep a generous summary length (avoid premature truncation)
                    return self._normalize({
                        'summary': (body or '').strip()[:2000],
                        'likely_conditions': found,
                        'recommendations': recs,
                        'confidence': 'low',
                        'focus': '',
                        'findings': [],
                        'major_problem': '',
                        'condition': '',
                        'severity': 'low',
                        'recommended_tests': [],
                        'recommended_treatments': [],
                        'next_steps': [],
                    })

                # fallback: return raw string in 'summary'
                # If model returned plain text (non-JSON), return it as summary but normalize schema
                return self._normalize({
                    "summary": raw,
                    "likely_conditions": [],
                    "recommendations": [],
                    "confidence": "medium",
                })
        except Exception as e:
            # LLM failed; return an informative fallback
            logger.exception("LLM error in agent %s: %s", self.name, e)
            return self._normalize({
                "summary": f"LLM error or not configured: {e}",
                "likely_conditions": [],
                "recommendations": [],
                "confidence": "low",
            })

    def _extract_json(self, raw: str):
        """Try to extract the first JSON object from raw LLM text."""
        import json as _json
        import re as _re
        parsed = None
        try:
            parsed = _json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        # fenced json
        m = _re.search(r"```json\s*(\{.*?\})\s*```", raw, _re.S)
        if m:
            try:
                parsed = _json.loads(m.group(1))
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
        # balanced braces
        if '{' in raw:
            try:
                start = raw.find('{')
                depth = 0
                in_str = False
                esc = False
                for i in range(start, len(raw)):
                    ch = raw[i]
                    if esc:
                        esc = False
                        continue
                    if ch == '\\':
                        esc = True
                        continue
                    if ch == '"':
                        in_str = not in_str
                        continue
                    if in_str:
                        continue
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            js = raw[start:i+1]
                            try:
                                parsed = _json.loads(js)
                                if isinstance(parsed, dict):
                                    return parsed
                            except Exception:
                                break
            except Exception:
                pass
        return None

    def analyze_strict(self, text: str, llm_client) -> object:
        """Ask the model a strict JSON-only prompt requesting detailed structured fields.

        Returns a dict when possible, or None.
        """
        import json as _json
        strict_prompt = (
            "Respond ONLY with valid JSON. Do not include any explanatory text. "
            "Return an object with these keys when possible: patient_name, focus (one-line), findings (array), severity (one of low/medium/high), "
            "summary, likely_conditions (array), recommended_tests (array), recommended_treatments (array), next_steps (array), confidence.\n\n"
            f"Report:\n{text}"
        )
        try:
            raw = llm_client.chat(system_prompt=None, user_prompt=strict_prompt)
        except Exception as e:
            logger.warning("Strict analyze failed for %s: %s", self.name, e)
            return None
        parsed = self._extract_json(raw)
        if isinstance(parsed, dict):
            return self._normalize(parsed)
        return parsed

    def _normalize(self, d: Dict) -> Dict:
        """Ensure the returned dict contains a consistent schema of fields.

        Expected keys:
          - findings (list)
          - major_problem (str)
          - condition (str)
          - severity (low/medium/high)
          - summary (str)
          - likely_conditions (list)
          - recommended_tests (list)
          - recommended_treatments (list)
          - recommendations (list)
          - next_steps (list)
          - confidence (low/medium/high)
          - role (agent name)
                    - focus (one-line description)
        """
        out = {}
        # strings
        out['summary'] = str(d.get('summary') or d.get('summary_text') or d.get('executive_summary') or '')
        out['major_problem'] = str(d.get('major_problem') or d.get('major_issue') or '')
        out['condition'] = str(d.get('condition') or d.get('diagnosis') or '')
        out['severity'] = str(d.get('severity') or d.get('risk') or 'medium')
        out['confidence'] = str(d.get('confidence') or 'medium')
        out['focus'] = str(d.get('focus') or '')

        # lists
        import re

        def _as_list(key):
            v = d.get(key)
            if v is None:
                return []
            if isinstance(v, list):
                return v
            if isinstance(v, str):
                # split by newline or semicolon or comma heuristically
                parts = [s.strip() for s in re.split(r"[\n;,]", v) if s.strip()]
                return parts
            return [v]

        out['findings'] = _as_list('findings')
        out['likely_conditions'] = _as_list('likely_conditions')
        out['recommended_tests'] = _as_list('recommended_tests')
        out['recommended_treatments'] = _as_list('recommended_treatments')
        out['recommendations'] = _as_list('recommendations')
        out['next_steps'] = _as_list('next_steps')

        # preserve optional richer fields
        out['explanation'] = str(d.get('explanation') or d.get('reasoning') or '')
        ev = d.get('evidence')
        if ev is None:
            out['evidence'] = []
        elif isinstance(ev, list):
            out['evidence'] = ev
        elif isinstance(ev, str):
            out['evidence'] = [ev]
        else:
            out['evidence'] = [str(ev)]

        # allow recommendations/tests/treatments to be objects with rationale; preserve if present
        def _preserve_objs(key):
            v = d.get(key)
            if v is None:
                return []
            return v

        out['recommended_tests_raw'] = _preserve_objs('recommended_tests_raw') if 'recommended_tests_raw' in d else None
        out['recommended_treatments_raw'] = _preserve_objs('recommended_treatments_raw') if 'recommended_treatments_raw' in d else None

        # abnormal_values: keep as object if provided, else empty dict
        ab = d.get('abnormal_values')
        if ab is None:
            out['abnormal_values'] = {}
        else:
            try:
                if isinstance(ab, dict):
                    out['abnormal_values'] = ab
                else:
                    # try to parse if string
                    import json as _json
                    out['abnormal_values'] = _json.loads(ab) if isinstance(ab, str) else { 'value': ab }
            except Exception:
                out['abnormal_values'] = { 'value': str(ab) }

        # patient_actions: short actionable bullets for patient
        out['patient_actions'] = _as_list('patient_actions')

        out['role'] = d.get('role') or self.name or ''
        return out
