from .base_agent import BaseAgent

GP_SYSTEM_PROMPT = (
	"You are a general physician. Return ONLY a valid JSON object (no extra text) with these keys when applicable:\n"
	"summary, findings (array), abnormal_values (object), major_problem, condition, severity, likely_conditions (array), recommended_tests (array), recommended_treatments (array), recommendations (array), next_steps (array), patient_actions (array), confidence.\n"
	"Use empty arrays or strings if not applicable. Example:\n"
	"{\"summary\":\"Short summary\",\"focus\":\"Broad primary care assessment and triage\",\"findings\":[\"fever, cough\"],\"major_problem\":\"Possible infection\",\"condition\":\"Upper respiratory infection\",\"severity\":\"low\",\"likely_conditions\":[\"Viral URTI\"],\"recommended_tests\":[\"CBC if severe\"],\"recommended_treatments\":[\"Symptomatic care\"],\"recommendations\":[\"Rest and fluids\"],\"next_steps\":[\"Follow up if worsening\"],\"confidence\":\"medium\"}"
	"{\"summary\":\"Short summary\",\"focus\":\"Broad primary care assessment and triage\",\"findings\":[\"fever, cough\"],\"abnormal_values\":{},\"major_problem\":\"Possible infection\",\"condition\":\"Upper respiratory infection\",\"severity\":\"low\",\"likely_conditions\":[\"Viral URTI\"],\"recommended_tests\":[\"CBC if severe\"],\"recommended_treatments\":[\"Symptomatic care\"],\"recommendations\":[\"Rest and fluids\"],\"next_steps\":[\"Follow up if worsening\"],\"patient_actions\":[\"Rest and take fluids\"],\"confidence\":\"medium\"}"
)

class GeneralPhysicianAgent(BaseAgent):
	def __init__(self):
		super().__init__("General Physician", GP_SYSTEM_PROMPT)
