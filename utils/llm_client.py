import os
import openai


class LLMClient:
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("LLM_MODEL", "gpt-3.5-turbo")
        # Provider selection logic:
        # - If LLM_PROVIDER is explicitly set, use that.
        # - Otherwise, prefer OpenAI when OPENAI_API_KEY exists, else use GROQ when GROQ_API_KEY exists.
        env_provider = os.getenv("LLM_PROVIDER")
        groq_key = os.getenv("GROQ_API_KEY")
        if env_provider:
            self.provider = env_provider.lower()
        else:
            if self.api_key:
                self.provider = "openai"
            elif groq_key:
                self.provider = "groq"
            else:
                # default to openai if nothing is available; methods will handle missing keys
                self.provider = "openai"

        self.groq_api_key = groq_key
        self.groq_base_url = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")

    def chat(self, system_prompt: str | None = None, user_prompt: str | None = None, prompt: str | None = None):
        """
        Sends a chat completion request to the LLM.

        Supports two calling styles used across the project:
        - chat(system_prompt, user_prompt)
        - chat(prompt="single combined prompt string")

        Returns the assistant text or an error string.
        """
        # Normalize input: allow single `prompt` kw used by symptom_chatbot
        if prompt is not None:
            user_prompt = prompt

        if not user_prompt and not system_prompt:
            return "No prompt provided to LLM."

        # Build messages list
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if user_prompt:
            messages.append({"role": "user", "content": user_prompt})
        # If no API keys are configured, provide a deterministic local fallback so chatbot still responds.
        if self.provider == "openai" and not self.api_key:
            # Fallback: extract last user sentence and ask a clarifying question
            last_user = messages[-1]["content"] if messages else ""
            short = last_user.strip()
            if not short:
                return "Hello — tell me your symptoms and I'll try to help."
            # Simple heuristic: look for duration/severity keywords
            clarifiers = ["How long have you had these symptoms?", "On a scale of 1-10, how severe is this?", "Have you seen a doctor about this?"]
            return f"I understand: {short[:240]}. {clarifiers[0]}"

        try:
            # If provider selected is openai but there is no OPENAI_API_KEY, try falling back to GROQ if available.
            if self.provider == "openai" and not self.api_key and self.groq_api_key:
                self.provider = "groq"

            if self.provider == "openai":
                client = openai.OpenAI(api_key=self.api_key)
                response = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.7,
                )
                # Response object shape may vary; try to extract robustly
                try:
                    return response.choices[0].message.content
                except Exception:
                    # Fallback to dict-style access
                    return response["choices"][0]["message"]["content"]
            elif self.provider == "groq":
                client = openai.OpenAI(api_key=self.groq_api_key, base_url=self.groq_base_url)
                response = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.7,
                )
                try:
                    return response.choices[0].message.content
                except Exception:
                    return response["choices"][0]["message"]["content"]
        except Exception as e:
            # On any LLM error, return a helpful fallback instead of failing silently.
            try:
                last_user = messages[-1]["content"] if messages else ""
                if last_user:
                    return f"(LLM unavailable) I saw: {last_user[:240]}. Could you share how long you've had these symptoms?"
            except Exception:
                pass
            return f"LLM error or not configured: {str(e)}"

    def summarize(self, text):
        if not text:
            return "No text provided to summarize."
        try:
            if self.provider == "openai":
                client = openai.OpenAI(api_key=self.api_key)
                response = client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": f"Summarize this text for a patient:\n{text}"}],
                    temperature=0.7
                )
                return response.choices[0].message.content
            elif self.provider == "groq":
                client = openai.OpenAI(api_key=self.groq_api_key, base_url=self.groq_base_url)
                response = client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": f"Summarize this text for a patient:\n{text}"}],
                    temperature=0.7
                )
                return response.choices[0].message.content
        except Exception as e:
            return f"LLM error: {str(e)}"
