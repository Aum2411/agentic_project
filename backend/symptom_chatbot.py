from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from typing import List, Dict
import os
import uuid
from utils.llm_client import LLMClient
from collections import deque

# In-memory conversation store (for demo; use Redis/db for prod)
conversations: Dict[str, deque] = {}
session_titles: Dict[str, str] = {}
session_meta: Dict[str, Dict] = {}
MAX_HISTORY = 10  # Number of turns to keep in memory

router = APIRouter()
llm = LLMClient()

@router.post("/chatbot/start")
async def start_chat(request: Request):
    data = {}
    try:
        data = await request.json()
    except Exception:
        data = {}
    session_id = str(uuid.uuid4())
    conversations[session_id] = deque(maxlen=MAX_HISTORY)
    session_titles[session_id] = "New chat"
    session_meta[session_id] = {}
    lang = data.get('lang') if isinstance(data, dict) else None
    if lang:
        session_meta[session_id]['lang'] = lang
    return {"session_id": session_id, "message": "Hello! Please describe your symptoms."}

@router.post("/chatbot/message")
async def chat_message(request: Request):
    data = await request.json()
    session_id = data.get("session_id")
    user_message = data.get("message")
    # language preference: request overrides stored session preference
    lang = (data.get('lang') or session_meta.get(session_id, {}).get('lang') or 'en') if session_id else (data.get('lang') or 'en')
    if not session_id or session_id not in conversations:
        return JSONResponse(status_code=400, content={"error": "Invalid session."})
    if not user_message:
        return JSONResponse(status_code=400, content={"error": "Message required."})
    # small-talk and name extraction
    um_lower = user_message.lower().strip()
    import re
    # greetings
    if re.search(r'\b(hi|hello|hey|good morning|good afternoon|good evening)\b', um_lower):
        name = session_meta.get(session_id, {}).get('name')
        if name:
            resp_en = f"Hello {name}! How can I help you with your health today?"
        else:
            resp_en = "Hello! I'm here to help with health questions — tell me about your symptoms."
        # translate if needed
        resp = resp_en if lang == 'en' else translate_with_llm(resp_en, lang)
        conversations[session_id].append({"role": "ai", "content": resp})
        return {"response": resp, "session_id": session_id}
    # how are you
    if re.search(r'\bhow are you\b', um_lower):
        name = session_meta.get(session_id, {}).get('name')
        resp_en = f"I'm doing well, thanks for asking{(' ' + name) if name else ''}! How are you feeling today?"
        resp = resp_en if lang == 'en' else translate_with_llm(resp_en, lang)
        conversations[session_id].append({"role": "ai", "content": resp})
        return {"response": resp, "session_id": session_id}
    # name extraction: "my name is X", "i am X", "i'm X"
    m = re.search(r"\b(?:my name is|i am|i'm|im)\s+([A-Za-z\-\' ]{1,40})", user_message, re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        # store name in session meta
        session_meta.setdefault(session_id, {})['name'] = name
        resp_en = f"Nice to meet you, {name}! How can I assist with your health today?"
        resp = resp_en if lang == 'en' else translate_with_llm(resp_en, lang)
        conversations[session_id].append({"role": "ai", "content": resp})
        return {"response": resp, "session_id": session_id}
    # Simple health-related keyword check (if none found, politely guide user)
    health_keywords = ["pain", "fever", "cough", "symptom", "doctor", "medicine", "health", "sick", "illness", "diagnosis", "treatment", "hospital", "injury", "infection", "disease", "medical", "chest", "headache", "vomit", "nausea", "diarrhea", "cold", "flu", "allergy", "asthma", "breath", "heart", "blood", "pressure", "diabetes", "cancer", "fracture", "wound", "rash", "swelling", "burn", "anxiety", "depression", "mental", "fatigue", "weakness", "dizzy", "appetite", "weight", "sleep", "throat", "ear", "eye", "nose", "stomach", "abdomen", "back", "joint", "muscle", "bone", "skin"]
    if not any(word in user_message.lower() for word in health_keywords):
        # let LLM handle clarifying if needed, but if clearly small-talk, we've handled earlier; otherwise guide
        guide = "I can help with medical symptoms and concerns. Could you describe any symptoms, duration, or severity?"
        conversations[session_id].append({"role": "ai", "content": guide})
        return {"response": guide, "session_id": session_id}
    # Add user message to history
    conversations[session_id].append({"role": "user", "content": user_message})
    # If session has default title, create a short title from the first user message
    if session_titles.get(session_id) in (None, "New chat"):
        # take first 6 words
        words = user_message.strip().split()
        short = " ".join(words[:6])
        if len(short) > 40:
            short = short[:37] + "..."
        session_titles[session_id] = short or "Chat"
    # Compose prompt for LLM
    history = list(conversations[session_id])
    prompt = []
    for turn in history:
        prompt.append(f"{turn['role'].capitalize()}: {turn['content']}")
    prompt.append("AI: (Ask clarifying questions about symptoms, or summarize when ready.)")
    llm_response = llm.chat(prompt="\n".join(prompt))
    # Translate LLM response if requested language isn't English
    final_response = llm_response
    if lang and lang != 'en':
        try:
            final_response = translate_with_llm(llm_response, lang)
        except Exception:
            # fallback to original
            final_response = llm_response
    conversations[session_id].append({"role": "ai", "content": final_response})
    return {"response": final_response, "session_id": session_id}

@router.post("/chatbot/summary")
async def get_summary(request: Request):
    data = await request.json()
    session_id = data.get("session_id")
    lang = data.get('lang') or session_meta.get(session_id, {}).get('lang') or 'en'
    if not session_id or session_id not in conversations:
        return JSONResponse(status_code=400, content={"error": "Invalid session."})
    # Compose summary prompt
    history = list(conversations[session_id])
    prompt = []
    for turn in history:
        prompt.append(f"{turn['role'].capitalize()}: {turn['content']}")
    prompt.append("AI: Summarize the patient's symptoms and medical history in structured form for specialist agents.")
    summary = llm.chat(prompt="\n".join(prompt))
    if lang and lang != 'en':
        try:
            summary = translate_with_llm(summary, lang)
        except Exception:
            pass
    return {"structured_history": summary}


def translate_with_llm(text: str, target_lang: str) -> str:
    # Use the LLM to translate into Hindi or Gujarati when requested.
    if not text:
        return ''
    if target_lang == 'en' or not target_lang:
        return text
    lang_name = 'Hindi' if target_lang == 'hi' else 'Gujarati' if target_lang == 'gu' else None
    if not lang_name:
        return text
    prompt = f"Translate the following text to {lang_name} in natural, patient-friendly language:\n\n{text}\n\nTranslated:" 
    res = llm.chat(prompt=prompt)
    return str(res) if res is not None else ''


# Session management endpoints (demo in-memory)
@router.get("/chatbot/sessions")
def list_sessions():
    # Return a small summary for each session
    out = []
    for sid, dq in conversations.items():
        last = dq[-1]['content'] if dq else ''
        out.append({"session_id": sid, "last_message": last, "length": len(dq), "title": session_titles.get(sid, "New chat")})
    return {"sessions": out}


@router.get("/chatbot/sessions/{session_id}")
def get_session(session_id: str):
    if session_id not in conversations:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    return {"session_id": session_id, "history": list(conversations[session_id]), "title": session_titles.get(session_id)}


@router.delete("/chatbot/sessions/{session_id}")
def delete_session(session_id: str):
    if session_id in conversations:
        del conversations[session_id]
        if session_id in session_titles:
            del session_titles[session_id]
        return {"ok": True}
    return JSONResponse(status_code=404, content={"error": "Not found"})


@router.get("/chatbot/sessions/{session_id}/export")
def export_session(session_id: str):
    if session_id not in conversations:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    # Return a simple plain-text export
    lines = []
    for turn in conversations[session_id]:
        lines.append(f"{turn['role'].upper()}: {turn['content']}")
    return {"export": "\n".join(lines)}


@router.put("/chatbot/sessions/{session_id}/title")
def update_title(session_id: str, request: Request):
    data = request.json()
    new_title = data.get("title") if isinstance(data, dict) else None
    if not new_title:
        return JSONResponse(status_code=400, content={"error": "title required"})
    if session_id not in conversations:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    session_titles[session_id] = new_title
    return {"ok": True, "title": new_title}
