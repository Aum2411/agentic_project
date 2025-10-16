from utils.llm_client import LLMClient

class AggregatorAgent:
    def __init__(self):
        pass

    def aggregate(self, results: list, llm_client: LLMClient):
        """
        Combine multiple agent outputs (dicts) into a patient-friendly report.
        """
        # Extract summaries for aggregation
        summaries = []
        all_conditions = []
        all_recommendations = []
        for r in results:
            if isinstance(r, dict):
                summaries.append(r.get("summary", str(r)))
                all_conditions.extend(r.get("likely_conditions", []))
                all_recommendations.extend(r.get("recommendations", []))
            else:
                summaries.append(str(r))

        combined_text = "\n".join(summaries)
        try:
            summary = llm_client.summarize(combined_text)
        except Exception as e:
            summary = f"LLM error or not configured: {str(e)}"

        # Build consensus_findings as readable strings and deduplicate while preserving order
        consensus_list = []
        seen_consensus = set()
        for r in results:
            if isinstance(r, dict):
                s = r.get('summary') or r.get('executive_summary') or str(r)
            else:
                s = str(r)
            s_norm = (s or '').strip()
            key = s_norm.lower()
            if key and key not in seen_consensus:
                seen_consensus.add(key)
                consensus_list.append(s_norm)

        report = {
            "executive_summary": summary or "No summary available.",
            "consensus_findings": consensus_list or ["No consensus findings."],
            # Preserve order of conditions and recommendations while removing duplicates
            "all_conditions": (lambda lst: (lambda o, s=set(): [x for x in lst if not (x_lower:= (str(x).strip().lower())) or (x_lower in s or s.add(x_lower) and False)][::-1])([*lst]))(all_conditions) if all_conditions else [],
            "recommendations": (lambda lst: (lambda o, s=set(): [x for x in lst if not (x_lower:= (str(x).strip().lower())) or (x_lower in s or s.add(x_lower) and False)][::-1])([*lst]))(all_recommendations) if all_recommendations else [],
            "next_steps": [
                "Review the recommendations with relevant specialists.",
                "Order indicated tests (ECG, Echo, CXR, spirometry) if not already done."
            ],
            # Suggested specialists based on conditions detected in agent outputs
            "specialist_suggestions": [],
            "specialist_explanations": {},
            "disclaimer": "This is not a medical diagnosis. Please consult a doctor."
        }
        # Simple rule-based mapping from condition keywords to specialist roles
        mapping = {
            'hypertension': 'Cardiologist',
            'chest': 'Cardiologist',
            'ecg': 'Cardiologist',
            'anxiety': 'Psychologist / Neurologist',
            'depression': 'Psychologist / Neurologist',
            'cough': 'Pulmonologist',
            'breath': 'Pulmonologist',
            'thyroid': 'Endocrinologist',
            'diabetes': 'Endocrinologist',
            'blood': 'Hematologist / Pathologist',
            'liver': 'Gastroenterologist',
            'stomach': 'Gastroenterologist',
            'kidney': 'Nephrologist',
            'skin': 'Dermatologist',
            'rash': 'Dermatologist',
            'xray': 'Radiologist',
            'ct': 'Radiologist',
            'mri': 'Radiologist'
        }
        # Build a combined searchable string that includes summaries, detected conditions and recommendations
        extra_parts = []
        if isinstance(report.get('all_conditions'), list):
            extra_parts.extend([str(x) for x in report.get('all_conditions')])
        if isinstance(report.get('recommendations'), list):
            extra_parts.extend([str(x) for x in report.get('recommendations')])
        search_text = (combined_text + '\n' + '\n'.join(extra_parts)).lower()

        import re
        suggested = []
        explanations = {}
        for kw, specialist in mapping.items():
            # use word-boundary matching to avoid accidental substring matches
            try:
                if re.search(r"\b" + re.escape(kw) + r"\b", search_text, flags=re.I):
                    if specialist not in suggested:
                        suggested.append(specialist)
                        explanations[specialist] = f"Because the report mentions '{kw}', a {specialist} may provide deeper evaluation and targeted recommendations."
            except Exception:
                # fallback to simple substring
                if kw in search_text and specialist not in suggested:
                    suggested.append(specialist)
                    explanations[specialist] = f"Because the report mentions '{kw}', a {specialist} may provide deeper evaluation and targeted recommendations."

        if suggested:
            report['specialist_suggestions'] = suggested
            report['specialist_explanations'] = explanations
            # Append a short recommendation sentence to the executive summary
            try:
                sug_text = ', '.join(suggested)
                report['executive_summary'] = (report.get('executive_summary') or summary or '').strip() + f"\n\nSuggested specialist opinions: Consider getting an opinion from: {sug_text}."
            except Exception:
                pass

        return report
