import re
import dotenv
import os
from pathlib import Path
import time

dotenv.load_dotenv(dotenv.find_dotenv())

# basic logging for debugging
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, File, UploadFile, Form, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

# Utilities
from utils.pdf_parser import extract_text_from_pdf
from utils.preprocessing import clean_text
from utils.llm_client import LLMClient
from storage.db import Database
import hashlib
import hmac
import base64
import bcrypt

# Agents
from agents.cardiologist_agent import CardiologistAgent
from agents.psychologist_agent import PsychologistAgent
from agents.pulmonologist_agent import PulmonologistAgent
from agents.aggregator_agent import AggregatorAgent
import importlib

def _dynamic_agent_class(module_name: str, class_name: str):
    try:
        m = importlib.import_module(module_name)
        return getattr(m, class_name, None)
    except Exception:
        return None

DermatologistAgent = _dynamic_agent_class('agents.dermatologist_agent', 'DermatologistAgent')
EndocrinologistAgent = _dynamic_agent_class('agents.endocrinologist_agent', 'EndocrinologistAgent')
GastroenterologistAgent = _dynamic_agent_class('agents.gastroenterologist_agent', 'GastroenterologistAgent')
GeneralPhysicianAgent = _dynamic_agent_class('agents.general_physician_agent', 'GeneralPhysicianAgent')
HematologistAgent = _dynamic_agent_class('agents.hematologist_agent', 'HematologistAgent')
NephrologistAgent = _dynamic_agent_class('agents.nephrologist_agent', 'NephrologistAgent')
RadiologistAgent = _dynamic_agent_class('agents.radiologist_agent', 'RadiologistAgent')
# Symptom Chatbot
from .symptom_chatbot import router as symptom_chatbot_router

# ---------- App Setup ----------

app = FastAPI(title="Healthscope API")
app.include_router(symptom_chatbot_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For local dev; change in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Initialize Components ----------
db = Database("healthscope.db")
llm = LLMClient()  # uses OPENAI_API_KEY and LLM_MODEL from .env

cardio_agent = CardiologistAgent()
psych_agent = PsychologistAgent()
pulmo_agent = PulmonologistAgent()
derm_agent = DermatologistAgent() if DermatologistAgent else None
endo_agent = EndocrinologistAgent() if EndocrinologistAgent else None
gastro_agent = GastroenterologistAgent() if GastroenterologistAgent else None
gp_agent = GeneralPhysicianAgent() if GeneralPhysicianAgent else None
hema_agent = HematologistAgent() if HematologistAgent else None
neph_agent = NephrologistAgent() if NephrologistAgent else None
radi_agent = RadiologistAgent() if RadiologistAgent else None
aggregator = AggregatorAgent()

# ---------- Routes ----------
@app.get("/health")
async def health():
    return {"status": "ok", "service": "Healthscope"}


@app.post('/doctor/summary')
async def doctor_summary(payload: dict):
    """Accepts JSON { cases: [text1, text2, ...] } and returns an aggregated AI summary."""
    try:
        cases = payload.get('cases') if isinstance(payload, dict) else None
        if not cases or not isinstance(cases, list):
            return JSONResponse(status_code=400, content={'error': 'Provide cases: [str] in JSON body'})
        # allow optional language preference in payload: 'en' (default), 'hi', 'gu'
        req_lang = (payload.get('lang') or 'en') if isinstance(payload, dict) else 'en'
        combined = "\n\n".join([c for c in cases if c])
        prompt = f"You are a senior clinician. Given the following patient summaries, produce a concise combined executive summary and highlight key common recommendations and patterns.\n\n{combined}\n\nRespond JSON with keys: summary, highlights"
        if req_lang and req_lang != 'en':
            lang_name = 'Hindi' if req_lang == 'hi' else 'Gujarati' if req_lang == 'gu' else None
            if lang_name:
                prompt = prompt + f"\n\nPlease respond in {lang_name}. Return the JSON fields ('summary' and 'highlights') in {lang_name} as well."
        try:
            result = str(llm.chat(prompt=prompt) or "")
            # Try to extract JSON if the model wrapped the reply in ```json ... ``` fences
            import json as _json
            import re as _re
            parsed = None

            # Helper: safely extract the first balanced JSON object from text by scanning
            def _extract_json_substring(s: str):
                if not s or '{' not in s:
                    return None
                start = s.find('{')
                while start != -1:
                    depth = 0
                    in_string = False
                    escape = False
                    for i in range(start, len(s)):
                        ch = s[i]
                        if escape:
                            escape = False
                            continue
                        if ch == '\\':
                            escape = True
                            continue
                        if ch == '"':
                            in_string = not in_string
                            continue
                        if in_string:
                            continue
                        if ch == '{':
                            depth += 1
                        elif ch == '}':
                            depth -= 1
                            if depth == 0:
                                return s[start:i+1]
                    # try next opening brace
                    start = s.find('{', start + 1)
                return None

            try:
                # First attempt: parse direct JSON
                parsed = _json.loads(result)
            except Exception:
                # Try to extract fenced JSON block first
                m = _re.search(r"```json\s*(\{.*?\})\s*```", result, _re.S)
                if m:
                    try:
                        parsed = _json.loads(m.group(1))
                    except Exception:
                        parsed = None
                if not parsed:
                    # Use safe balanced-brace scanner to find a JSON object substring
                    js = _extract_json_substring(result)
                    if js:
                        try:
                            parsed = _json.loads(js)
                        except Exception:
                            parsed = None
            # If parsing failed, return cleaned text summary
            if not parsed:
                # Remove markdown fences and excess whitespace to return a clean paragraph
                cleaned = _re.sub(r"```.*?```", "", result, flags=_re.S)
                cleaned = cleaned.replace('\n\n', '\n').strip()
                parsed = {'summary': cleaned}
        except Exception as e:
            parsed = {'summary': f'LLM error: {e}'}
        return parsed
    except Exception as e:
        return JSONResponse(status_code=500, content={'error': str(e)})


# --------- Authentication endpoints (basic) ---------
@app.post('/auth/signup')
async def auth_signup(data: dict):
    try:
        username = data.get('username')
        password = data.get('password')
        if not username or not password:
            return JSONResponse(status_code=400, content={'error': 'username and password required'})
        # Hash password using bcrypt
        ph = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        ok = db.create_user(username, ph.decode('utf-8'))
        if not ok:
            return JSONResponse(status_code=400, content={'error': 'username already exists'})
        return {'ok': True}
    except Exception as e:
        return JSONResponse(status_code=500, content={'error': str(e)})


@app.post('/auth/login')
async def auth_login(data: dict):
    try:
        username = data.get('username')
        password = data.get('password')
        if not username or not password:
            return JSONResponse(status_code=400, content={'error': 'username and password required'})
        # fetch stored hash
        import sqlite3
        cur = db.conn.cursor()
        cur.execute('SELECT password_hash FROM users WHERE username=?', (username,))
        row = cur.fetchone()
        if not row:
            return JSONResponse(status_code=401, content={'error': 'invalid credentials'})
        stored = row[0]
        try:
            ok = bcrypt.checkpw(password.encode('utf-8'), stored.encode('utf-8'))
        except Exception:
            ok = False
        if not ok:
            return JSONResponse(status_code=401, content={'error': 'invalid credentials'})
        # Return a simple session token (insecure demo): base64(username)
        token = base64.b64encode(username.encode('utf-8')).decode('utf-8')
        return {'ok': True, 'token': token, 'username': username}
    except Exception as e:
        return JSONResponse(status_code=500, content={'error': str(e)})


# OTP endpoints (send/verify) - demo implementation (no SMS gateway)
@app.post('/auth/send_otp')
async def auth_send_otp(data: dict):
    try:
        phone = data.get('phone')
        if not phone:
            return JSONResponse(status_code=400, content={'error': 'phone required'})
        import random, datetime, os
        code = str(random.randint(100000, 999999))
        expires = (datetime.datetime.utcnow() + datetime.timedelta(minutes=5)).isoformat()
        db.save_otp(phone, code, expires)
        # Try to send via Twilio if configured
        tw_sid = os.getenv('TWILIO_ACCOUNT_SID')
        tw_token = os.getenv('TWILIO_AUTH_TOKEN')
        tw_from = os.getenv('TWILIO_FROM')
        if tw_sid and tw_token and tw_from:
            try:
                from twilio.rest import Client
                client = Client(tw_sid, tw_token)
                client.messages.create(body=f'Your Healthscope OTP is: {code}', from_=tw_from, to=phone)
                return {'ok': True}
            except Exception as e:
                # fallback to returning OTP in response for demo
                return {'ok': True, 'otp': code, 'warning': f'twilio send failed: {e}'}
        # No SMS provider configured — return OTP in response for demo/testing
        return {'ok': True, 'otp': code, 'demo': True}
    except Exception as e:
        return JSONResponse(status_code=500, content={'error': str(e)})


@app.post('/auth/verify_otp')
async def auth_verify_otp(data: dict):
    try:
        phone = data.get('phone'); code = data.get('code')
        if not phone or not code:
            return JSONResponse(status_code=400, content={'error': 'phone and code required'})
        ok = db.verify_otp(phone, code)
        if not ok:
            return JSONResponse(status_code=400, content={'error': 'invalid otp'})
        # mark verified (for demo, return success) — frontend should call /auth/set_password next
        return {'ok': True, 'phone': phone}
    except Exception as e:
        return JSONResponse(status_code=500, content={'error': str(e)})


@app.post('/auth/set_password')
async def auth_set_password(data: dict):
    try:
        phone = data.get('phone'); password = data.get('password'); username = data.get('username')
        if not phone or not password:
            return JSONResponse(status_code=400, content={'error': 'phone and password required'})
        # Hash and create user (if exists, return error)
        ph = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        created = db.create_user_with_phone(phone, ph, username or phone)
        if not created:
            return JSONResponse(status_code=400, content={'error': 'could not create user; maybe phone exists'})
        token = base64.b64encode(phone.encode('utf-8')).decode('utf-8')
        return {'ok': True, 'token': token, 'phone': phone}
    except Exception as e:
        return JSONResponse(status_code=500, content={'error': str(e)})


# Doctor case endpoints (server-side persistence)
@app.post('/doctor/case')
async def create_doctor_case(payload: dict):
    try:
        token = payload.get('token')
        doctor_id = None
        if token:
            try:
                doctor_id = base64.b64decode(token.encode('utf-8')).decode('utf-8')
            except Exception:
                doctor_id = None
        report_id = payload.get('report_id')
        notes = payload.get('notes') or ''
        if not doctor_id or not report_id:
            return JSONResponse(status_code=400, content={'error':'doctor token and report_id required'})
        # find doctor numeric id
        cur = db.conn.cursor(); cur.execute('SELECT id FROM users WHERE phone=? OR username=?', (doctor_id, doctor_id)); row = cur.fetchone();
        if not row: return JSONResponse(status_code=400, content={'error':'doctor not found'})
        did = row[0]
        cid = db.create_doctor_case(did, int(report_id), notes)
        return {'ok': True, 'case_id': cid}
    except Exception as e:
        return JSONResponse(status_code=500, content={'error': str(e)})


@app.post('/doctor/verify')
async def doctor_verify(name: str = Form(None), phone: str = Form(None), proof: UploadFile = File(None)):
    """Accepts multipart form: name, phone, proof(file). Saves proof under healthscope/doctor_profiles and upserts verified user (demo).
    """
    try:
        if not phone or not name:
            return JSONResponse(status_code=400, content={'error': 'name and phone required'})

        # save proof file if provided (sanitize filename)
        ROOT = Path(__file__).resolve().parent.parent
        profiles_dir = ROOT / 'doctor_profiles'
        profiles_dir.mkdir(parents=True, exist_ok=True)
        saved_proof_path = None
        if proof:
            try:
                orig_name = Path(proof.filename or 'proof').name
            except Exception:
                orig_name = 'proof'
            # allow only safe characters in filename
            import re as _re
            safe_orig = _re.sub(r'[^A-Za-z0-9_.-]', '_', orig_name)[:180]
            safe_name = f"{int(time.time())}_{safe_orig}"
            saved_proof_path = profiles_dir / safe_name
            content = await proof.read()
            with open(saved_proof_path, 'wb') as fh:
                fh.write(content)

        # Upsert user safely: if phone exists, update username and set verified=1; else insert new verified user.
        # Handle UNIQUE constraint on username by retrying with phone as username if needed.
        import sqlite3
        cur = db.conn.cursor()
        cur.execute('SELECT id FROM users WHERE phone=?', (phone,))
        row = cur.fetchone()
        try:
            if row:
                cur.execute('UPDATE users SET username=?, verified=1 WHERE phone=?', (name, phone))
            else:
                try:
                    cur.execute('INSERT INTO users (username, phone, password_hash, verified) VALUES (?,?,?,1)', (name, phone, None))
                except sqlite3.IntegrityError as ie:
                    # likely username already taken; fallback to using phone as username and retry
                    cur.execute('INSERT OR IGNORE INTO users (username, phone, password_hash, verified) VALUES (?,?,?,1)', (phone, phone, None))
        except Exception as e:
            db.conn.rollback()
            return JSONResponse(status_code=500, content={'error': f'database error: {str(e)}'})
        db.conn.commit()

        # save profile metadata (overwrite or create)
        meta_path = profiles_dir / f"{phone}_profile.json"
        import json as _json
        with open(meta_path, 'w', encoding='utf-8') as f:
            _json.dump({'name': name, 'phone': phone, 'proof_file': str(saved_proof_path) if saved_proof_path else None}, f)

        token = base64.b64encode(phone.encode('utf-8')).decode('utf-8')
        return {'ok': True, 'token': token, 'phone': phone}
    except Exception as e:
        return JSONResponse(status_code=500, content={'error': str(e)})


@app.get('/doctor/cases')
async def list_doctor_cases(token: Optional[str] = None):
    try:
        if not token: return JSONResponse(status_code=400, content={'error':'token required'})
        try:
            doctor_id = base64.b64decode(token.encode('utf-8')).decode('utf-8')
        except Exception:
            return JSONResponse(status_code=400, content={'error':'invalid token'})
        cur = db.conn.cursor(); cur.execute('SELECT id FROM users WHERE phone=? OR username=?', (doctor_id, doctor_id)); row = cur.fetchone();
        if not row: return {'cases': []}
        did = row[0]
        cases = db.list_doctor_cases(did)
        return {'cases': cases}
    except Exception as e:
        return JSONResponse(status_code=500, content={'error': str(e)})


@app.delete('/doctor/case/{case_id}')
async def delete_doctor_case(case_id: int):
    try:
        ok = db.delete_doctor_case(case_id)
        return {'ok': ok}
    except Exception as e:
        return JSONResponse(status_code=500, content={'error': str(e)})

@app.post("/analyze")
async def analyze(
    text: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    report: Optional[UploadFile] = File(None),
    lang: Optional[str] = Query(None),
    specialist: Optional[str] = Query(None),
    aggregate: Optional[bool] = Query(False),
    # Run all specialist agents by default when a report is uploaded without a specific specialist.
    # Set ?run_all=false on the request to avoid running every agent.
    run_all: Optional[bool] = Query(True),
):
    # language preference for output (provided as ?lang=hi or ?lang=gu)
    req_lang = (lang or 'en')
    # 1️⃣ Validate input
    if not text and not file and not report:
        return JSONResponse(
            status_code=400,
            content={"error": "Provide `text` or upload a `file` (PDF or TXT)."}
        )

    # 2️⃣ Extract text from file or use direct input
    content = ""
    extracted_text_debug = ""
    # support both 'file' and 'report' form field names (some clients send 'report')
    uploaded_file = file or report
    if uploaded_file:
        raw = await uploaded_file.read()
        fname = (uploaded_file.filename or '').lower()
        # Support PDF text extraction and image OCR (png/jpg/jpeg)
        if fname.endswith(".pdf"):
            try:
                # Try PyPDF2 first
                content = extract_text_from_pdf(raw)
                extracted_text_debug = content
                # If text is too short, try pdfplumber as fallback
                if len(content.strip()) < 50:
                    try:
                        import pdfplumber
                        from io import BytesIO
                        with pdfplumber.open(BytesIO(raw)) as pdf:
                            content = "\n".join(page.extract_text() or "" for page in pdf.pages)
                            extracted_text_debug = content
                    except Exception as e:
                        extracted_text_debug += f"\n[pdfplumber fallback failed: {e}]"
            except Exception as e:
                content = raw.decode("utf-8", errors="ignore")
                extracted_text_debug = content + f"\n[PyPDF2 failed: {e}]"
        elif fname.endswith(('.png', '.jpg', '.jpeg')) or (uploaded_file.content_type and uploaded_file.content_type.startswith('image/')):
            # Try OCR using Pillow + pytesseract if available
            try:
                from PIL import Image
                import io
                try:
                    import pytesseract  # type: ignore
                except Exception:
                    pytesseract = None
                if pytesseract is None:
                    # fallback: decode bytes as text (rare) or raise
                    content = "[OCR not available: install pytesseract and tesseract]"
                    extracted_text_debug = content
                else:
                    img = Image.open(io.BytesIO(raw)).convert('RGB')
                    text = pytesseract.image_to_string(img)
                    content = text
                    extracted_text_debug = content
            except Exception as e:
                content = ""
                extracted_text_debug = f"[image ocr failed: {e}]"
        else:
            try:
                content = raw.decode("utf-8", errors="ignore")
                extracted_text_debug = content
            except Exception:
                content = ''
                extracted_text_debug = ''
    else:
        content = text
        extracted_text_debug = text


    # 3️⃣ Preprocess text
    cleaned_text = clean_text(content or "")

    # Detect if this looks like a blood/lab report by scanning for common test names and lab markers
    blood_keywords = [r"\bHB\b", r"\bHgb\b", r"\bHemoglobin\b", r"\bWBC\b", r"\bRBC\b", r"\bPlatelet\b", r"\bPlatelets\b", r"\bMCV\b", r"\bMCH\b", r"\bESR\b", r"\bCRP\b", r"\bBilirubin\b"]
    is_blood_report = False
    try:
        low = cleaned_text.upper()
        for kw in blood_keywords:
            # simple substring check for most; regex for word forms
            if kw.isalpha():
                if kw.upper() in low:
                    is_blood_report = True; break
            else:
                import re as _re
                if _re.search(kw, cleaned_text, _re.I):
                    is_blood_report = True; break
    except Exception:
        is_blood_report = False

    # Check if the extracted text looks like a valid healthcare report
    # (very basic: must mention 'patient', 'diagnosis', or 'medical' etc.)
    if not any(keyword in cleaned_text.lower() for keyword in ["patient", "diagnosis", "medical", "doctor", "hospital", "report"]):
        return JSONResponse(
            status_code=400,
            content={"error": "Upload a valid healthcare report. The uploaded file does not appear to be a medical report."}
        )

    # 4️⃣ Save raw report
    report_id = db.save_report(cleaned_text)

    # 5️⃣ Run agents according to requested mode
    # If `specialist` is provided, run only that specialist agent and return its output.
    cardio_result = psych_result = pulmo_result = derm_result = endo_result = gastro_result = gp_result = hema_result = neph_result = radi_result = None
    final_report = None

    def _safe_call(agent, text, role_name):
        if not agent:
            return None
        try:
            res = agent.analyze(text, llm)
            # If hematology returned a raw table-like string or missing structured keys, use deterministic parser
            def _looks_like_raw_cbc(x):
                try:
                    if isinstance(x, str) and ('hemoglobin' in x.lower() or 'hb' in x.lower() and 'rbc' in x.lower()):
                        return True
                    if isinstance(x, dict):
                        # if dict but has no findings/abnormal_values, consider fallback
                        if not x.get('findings') and not x.get('abnormal_values') and ('hemoglobin' in str(x) or 'hb' in str(x).lower()):
                            return True
                except Exception:
                    return False
                return False

            def parse_cbc_report(s: str):
                """Deterministic CBC parser: extract common CBC values and produce structured interpretation.

                This is a conservative heuristic fallback when the LLM is unavailable or returns raw table text.
                """
                import re
                out = {
                    'summary': '',
                    'abnormal_values': {},
                    'findings': [],
                    'major_problem': '',
                    'condition': '',
                    'severity': 'low',
                    'likely_conditions': [],
                    'recommended_tests': [],
                    'recommended_treatments': [],
                    'recommendations': [],
                    'next_steps': [],
                    'patient_actions': [],
                    'confidence': 'low',
                }
                text = s or ''
                # normalize spacing
                t = re.sub(r"\s+", " ", text)
                # Try to detect age and sex from header lines (e.g., 'Age/Sex : 19 years/Male')
                age = None
                sex = None
                try:
                    m = re.search(r"age\s*[:\-]?\s*([0-9]{1,3})", t, re.I)
                    if m:
                        age = int(m.group(1))
                except Exception:
                    age = None
                try:
                    m2 = re.search(r"sex\s*[:\-]?\s*(male|female|m|f)", t, re.I)
                    if m2:
                        sraw = m2.group(1).lower()
                        sex = 'male' if sraw.startswith('m') else 'female'
                except Exception:
                    sex = None
                # regex helpers
                def find_num(key_patterns):
                    for pat in key_patterns:
                        m = re.search(pat + r"\s*[:\-]?\s*([0-9]+\.?[0-9]*)", t, re.I)
                        if m:
                            return float(m.group(1))
                    return None

                hb = find_num([r"hemoglobin\s*\(hb\)", r"hb\b", r"hemoglobin", r"hb\s*:\s*"]) or find_num([r"hemoglobin\s*[:\-]?\s*([0-9]+\.?[0-9]*)"]) if False else find_num([r"hemoglobin","hb"]) 
                # fallback patterns for percentages and counts
                m = re.search(r"mcv\s*[:\-]?\s*([0-9]+\.?[0-9]*)", t, re.I)
                mcv = float(m.group(1)) if m else None
                m = re.search(r"mch\s*[:\-]?\s*([0-9]+\.?[0-9]*)", t, re.I)
                mch = float(m.group(1)) if m else None
                m = re.search(r"mchc\s*[:\-]?\s*([0-9]+\.?[0-9]*)", t, re.I)
                mchc = float(m.group(1)) if m else None
                m = re.search(r"wbc\s*[:\-]?\s*([0-9]+\,?[0-9]*)", t, re.I)
                wbc = None
                if m:
                    wbc = float(m.group(1).replace(',',''))
                m = re.search(r"platelet[s]?\s*[:\-]?\s*([0-9]+\,?[0-9]*)", t, re.I)
                plate = None
                if m:
                    plate = float(m.group(1).replace(',',''))

                # Try to extract Hb more robustly (numbers with units)
                hb_match = re.search(r"hb\s*[:\-]?\s*([0-9]+\.?[0-9]*)\s*(g/dl|gm/dl)?", t, re.I)
                if hb_match:
                    try:
                        hb = float(hb_match.group(1))
                    except Exception:
                        hb = None

                # Populate abnormal_values
                if hb is not None:
                    note = ''
                    # sex-aware thresholds when possible; fall back to conservative adult limits
                    male_hb_low = 13.0
                    female_hb_low = 12.0
                    if sex == 'male':
                        if hb < 10:
                            note = 'low (moderate to severe)'
                            out['severity'] = 'high'
                        elif hb < male_hb_low:
                            note = 'low (mild)'
                            out['severity'] = 'medium' if out['severity'] != 'high' else out['severity']
                        else:
                            note = 'normal'
                    elif sex == 'female':
                        if hb < 9:
                            note = 'low (moderate to severe)'
                            out['severity'] = 'high'
                        elif hb < female_hb_low:
                            note = 'low (mild)'
                            out['severity'] = 'medium' if out['severity'] != 'high' else out['severity']
                        else:
                            note = 'normal'
                    else:
                        # unknown sex: conservative thresholds
                        if hb < 10:
                            note = 'low (moderate to severe)'
                            out['severity'] = 'high'
                        elif hb < 12:
                            note = 'low (mild)'
                            out['severity'] = 'medium' if out['severity'] != 'high' else out['severity']
                        else:
                            note = 'normal'
                    out['abnormal_values']['Hb'] = f"{hb} g/dL ({note})"
                if mcv is not None:
                    note = 'normal'
                    if mcv < 80:
                        note = 'low (microcytosis)'
                    elif mcv > 100:
                        note = 'high (macrocytosis)'
                    out['abnormal_values']['MCV'] = f"{mcv} fL ({note})"
                if mch is not None:
                    out['abnormal_values']['MCH'] = f"{mch} pg"
                if mchc is not None:
                    out['abnormal_values']['MCHC'] = f"{mchc} g/dL"
                if wbc is not None:
                    out['abnormal_values']['WBC'] = f"{wbc} /uL"
                    if wbc < 4000:
                        out['findings'].append('Leukopenia')
                    elif wbc > 11000:
                        out['findings'].append('Leukocytosis')
                if plate is not None:
                    out['abnormal_values']['Platelets'] = f"{plate} /uL"
                    if plate < 150:
                        out['findings'].append('Thrombocytopenia')
                    elif plate > 450:
                        out['findings'].append('Thrombocytosis')

                # Heuristics for likely conditions
                if hb is not None and hb < 12:
                    out['findings'].append('Anemia')
                    out['likely_conditions'].append('Iron deficiency anemia')
                    out['recommended_tests'].extend(['Serum ferritin','Serum iron & TIBC','Peripheral smear'])
                    out['recommended_treatments'].append('Consider oral iron supplementation if iron deficiency confirmed')
                    out['patient_actions'].append('Start iron-rich diet and take prescribed iron as directed')
                    out['next_steps'].append('Repeat CBC and iron studies in 2-4 weeks')
                # Build summary
                summary_parts = []
                if out['findings']:
                    summary_parts.append('Findings: ' + ', '.join(out['findings']))
                if out['abnormal_values']:
                    summary_parts.append('Key abnormal labs: ' + ', '.join([f"{k} {v}" for k,v in out['abnormal_values'].items()]))
                if out['likely_conditions']:
                    summary_parts.append('Most likely: ' + ', '.join(out['likely_conditions']))
                out['summary'] = '. '.join(summary_parts) if summary_parts else 'No major hematologic abnormalities detected.'
                out['confidence'] = 'low'
                return out
            # If the agent returned a non-dict or incomplete dict, attempt strict JSON retry
            if not isinstance(res, dict) and hasattr(agent, 'analyze_strict'):
                try:
                    strict = agent.analyze_strict(text, llm)
                    if isinstance(strict, dict):
                        res = strict
                except Exception:
                    pass
            # If hematology returned raw table-like text or lacked structured fields, run deterministic parser
            if role_name and role_name.lower().startswith('hema'):
                try:
                    if _looks_like_raw_cbc(res):
                        # if res is dict, try to extract raw string
                        raw_text = None
                        if isinstance(res, str):
                            raw_text = res
                        elif isinstance(res, dict):
                            # check if raw table included in some key
                            for k in ('raw','text','report','table'):
                                if k in res and isinstance(res[k], str):
                                    raw_text = res[k]; break
                        if not raw_text:
                            raw_text = text
                        parsed = parse_cbc_report(raw_text)
                        # merge role/metadata
                        parsed['role'] = role_name
                        res = parsed
                except Exception:
                    pass
            # At this point, prefer a dict; if not dict, construct a normalized placeholder
            if isinstance(res, dict):
                # ensure it has at least a summary or findings
                if not res.get('summary') and not res.get('findings'):
                    logger.info("Agent %s returned empty content; filling fallback", role_name)
                    res['summary'] = f'No specific {role_name} findings detected in the report.'
                return res
            # non-dict fallback
            logger.warning("Agent %s returned non-dict result: %s", role_name, type(res))
            return {
                'summary': str(res) if res else f'No {role_name} findings.',
                'findings': [],
                'major_problem': '',
                'condition': '',
                'severity': 'medium',
                'likely_conditions': [],
                'recommended_tests': [],
                'recommended_treatments': [],
                'recommendations': [],
                'next_steps': [],
                'confidence': 'medium',
                'role': role_name,
            }
        except Exception as e:
            logger.exception("Agent %s raised exception: %s", role_name, e)
            return {
                'summary': f'{role_name.capitalize()} agent error: {str(e)}',
                'findings': [],
                'major_problem': '',
                'condition': '',
                'severity': 'low',
                'likely_conditions': [],
                'recommended_tests': [],
                'recommended_treatments': [],
                'recommendations': [],
                'next_steps': [],
                'confidence': 'low',
                'role': role_name,
            }

    def ensure_dict(x, role_name: str):
        # Ensure the result is a dict with the richer schema; if agent provided a dict, prefer it but fill missing keys
        schema_keys = [
            'summary','findings','major_problem','condition','severity','likely_conditions',
            'recommended_tests','recommended_treatments','recommendations','next_steps','confidence','role',
            'abnormal_values','patient_actions'
        ]
        out = {}
        if isinstance(x, dict):
            for k in schema_keys:
                v = x.get(k)
                if v is None:
                    # defaults
                    if k in ('findings','likely_conditions','recommended_tests','recommended_treatments','recommendations','next_steps'):
                        out[k] = []
                    elif k == 'abnormal_values':
                        out[k] = {}
                    elif k == 'patient_actions':
                        out[k] = []
                    elif k in ('summary','major_problem','condition','role'):
                        out[k] = ''
                    elif k in ('severity','confidence'):
                        out[k] = 'medium'
                else:
                    out[k] = v
            # ensure role is set
            out['role'] = out.get('role') or role_name
            return out
        # Not a dict: create default structured object
        return {
            'summary': str(x) if x else '',
            'findings': [],
            'major_problem': '',
            'condition': '',
            'severity': 'medium',
            'likely_conditions': [],
            'recommended_tests': [],
            'recommended_treatments': [],
            'recommendations': [],
            'next_steps': [],
            'confidence': 'medium',
            'role': role_name,
        }

    if specialist:
        s = specialist.lower().strip()
        # Map many possible select values to agents
        if s in ('cardiology', 'cardio', 'cardiologist'):
            cardio_result = _safe_call(cardio_agent, cleaned_text, 'cardiology')
            db.save_analysis(report_id, "cardiology", ensure_dict(cardio_result, 'cardiology'))
        elif s in ('psychology', 'psych', 'psychologist'):
            psych_result = _safe_call(psych_agent, cleaned_text, 'psychology')
            db.save_analysis(report_id, "psychology", ensure_dict(psych_result, 'psychology'))
        elif s in ('pulmonology', 'pulmo', 'pulmonologist'):
            pulmo_result = _safe_call(pulmo_agent, cleaned_text, 'pulmonology')
            db.save_analysis(report_id, "pulmonology", ensure_dict(pulmo_result, 'pulmonology'))
        elif s in ('dermatology','dermatologist','derm'):
            derm_result = _safe_call(derm_agent, cleaned_text, 'dermatology')
            db.save_analysis(report_id, "dermatology", ensure_dict(derm_result, 'dermatology'))
        elif s in ('endocrinology','endocrinologist','endo'):
            endo_result = _safe_call(endo_agent, cleaned_text, 'endocrinology')
            db.save_analysis(report_id, "endocrinology", ensure_dict(endo_result, 'endocrinology'))
        elif s in ('gastroenterology','gastroenterologist','gastro'):
            gastro_result = _safe_call(gastro_agent, cleaned_text, 'gastroenterology')
            db.save_analysis(report_id, "gastroenterology", ensure_dict(gastro_result, 'gastroenterology'))
        elif s in ('general','general_physician','gp','general physician'):
            gp_result = _safe_call(gp_agent, cleaned_text, 'general_physician')
            db.save_analysis(report_id, "general_physician", ensure_dict(gp_result, 'general_physician'))
        elif s in ('hematology','hematologist','hema'):
            hema_result = _safe_call(hema_agent, cleaned_text, 'hematology')
            db.save_analysis(report_id, "hematology", ensure_dict(hema_result, 'hematology'))
        elif s in ('nephrology','nephrologist','neph'):
            neph_result = _safe_call(neph_agent, cleaned_text, 'nephrology')
            db.save_analysis(report_id, "nephrology", ensure_dict(neph_result, 'nephrology'))
        elif s in ('radiology','radiologist','radi'):
            radi_result = _safe_call(radi_agent, cleaned_text, 'radiology')
            db.save_analysis(report_id, "radiology", ensure_dict(radi_result, 'radiology'))
        else:
            return JSONResponse(status_code=400, content={'error': f'Unknown specialist: {specialist}'})

        # when specialist-only, do not run aggregator unless explicitly requested by aggregate=True
        if aggregate:
            # Gather whichever agent outputs exist and pass to aggregator
            parts = [p for p in (cardio_result, psych_result, pulmo_result) if p]
            final_report = aggregator.aggregate(parts, llm_client=llm)
            db.save_final(report_id, final_report)

        # Prepare structured response (only include keys produced)
        resp: dict = {"report_id": report_id}
        if cardio_result is not None:
            resp['cardiology'] = ensure_dict(cardio_result, 'cardiology')
        if psych_result is not None:
            resp['psychology'] = ensure_dict(psych_result, 'psychology')
        if pulmo_result is not None:
            resp['pulmonology'] = ensure_dict(pulmo_result, 'pulmonology')
        if derm_result is not None:
            resp['dermatology'] = ensure_dict(derm_result, 'dermatology')
        if endo_result is not None:
            resp['endocrinology'] = ensure_dict(endo_result, 'endocrinology')
        if gastro_result is not None:
            resp['gastroenterology'] = ensure_dict(gastro_result, 'gastroenterology')
        if gp_result is not None:
            resp['general_physician'] = ensure_dict(gp_result, 'general_physician')
        if hema_result is not None:
            resp['hematology'] = ensure_dict(hema_result, 'hematology')
        if neph_result is not None:
            resp['nephrology'] = ensure_dict(neph_result, 'nephrology')
        if radi_result is not None:
            resp['radiology'] = ensure_dict(radi_result, 'radiology')
        if final_report is not None:
            resp['final_report'] = final_report
        resp['extracted_text_debug'] = extracted_text_debug
        resp['disclaimer'] = "This is not a medical diagnosis. Please consult a doctor."
        return resp

    # If run_all flag is set, run every specialist agent and save their outputs
    if run_all:
        try:
            cardio_result = _safe_call(cardio_agent, cleaned_text, 'cardiology')
            psych_result = _safe_call(psych_agent, cleaned_text, 'psychology')
            pulmo_result = _safe_call(pulmo_agent, cleaned_text, 'pulmonology')
            derm_result = _safe_call(derm_agent, cleaned_text, 'dermatology')
            endo_result = _safe_call(endo_agent, cleaned_text, 'endocrinology')
            gastro_result = _safe_call(gastro_agent, cleaned_text, 'gastroenterology')
            gp_result = _safe_call(gp_agent, cleaned_text, 'general_physician')
            hema_result = _safe_call(hema_agent, cleaned_text, 'hematology')
            neph_result = _safe_call(neph_agent, cleaned_text, 'nephrology')
            radi_result = _safe_call(radi_agent, cleaned_text, 'radiology')
        except Exception:
            pass

        # Save each analysis
        try:
            db.save_analysis(report_id, "cardiology", ensure_dict(cardio_result, 'cardiology'))
            db.save_analysis(report_id, "psychology", ensure_dict(psych_result, 'psychology'))
            db.save_analysis(report_id, "pulmonology", ensure_dict(pulmo_result, 'pulmonology'))
            db.save_analysis(report_id, "dermatology", ensure_dict(derm_result, 'dermatology'))
            db.save_analysis(report_id, "endocrinology", ensure_dict(endo_result, 'endocrinology'))
            db.save_analysis(report_id, "gastroenterology", ensure_dict(gastro_result, 'gastroenterology'))
            db.save_analysis(report_id, "general_physician", ensure_dict(gp_result, 'general_physician'))
            db.save_analysis(report_id, "hematology", ensure_dict(hema_result, 'hematology'))
            db.save_analysis(report_id, "nephrology", ensure_dict(neph_result, 'nephrology'))
            db.save_analysis(report_id, "radiology", ensure_dict(radi_result, 'radiology'))
        except Exception:
            pass

        # Aggregate based on specialist summaries (cardio/psych/pulmo) as before
        try:
            final_report = aggregator.aggregate([
                ensure_dict(cardio_result, 'cardiology'),
                ensure_dict(psych_result, 'psychology'),
                ensure_dict(pulmo_result, 'pulmonology')],
                llm_client=llm)
        except Exception:
            final_report = {'executive_summary': 'Aggregator failed to produce a summary.'}

        try:
            db.save_final(report_id, final_report if isinstance(final_report, dict) else {'executive_summary': str(final_report)})
        except Exception:
            pass

        resp = {
            "report_id": report_id,
            "cardiology": ensure_dict(cardio_result, 'cardiology'),
            "psychology": ensure_dict(psych_result, 'psychology'),
            "pulmonology": ensure_dict(pulmo_result, 'pulmonology'),
            "dermatology": ensure_dict(derm_result, 'dermatology'),
            "endocrinology": ensure_dict(endo_result, 'endocrinology'),
            "gastroenterology": ensure_dict(gastro_result, 'gastroenterology'),
            "general_physician": ensure_dict(gp_result, 'general_physician'),
            "hematology": ensure_dict(hema_result, 'hematology'),
            "nephrology": ensure_dict(neph_result, 'nephrology'),
            "radiology": ensure_dict(radi_result, 'radiology'),
            "final_report": final_report,
            "extracted_text_debug": extracted_text_debug,
            "is_blood_report": is_blood_report,
        }
        return resp

    # 9️⃣ Save extracted text to a file for debugging inside extracted_reports folder
    # If the client requested aggregate=true but we haven't produced a final_report yet,
    # run the aggregator on the extracted text (quick aggregator-only path).
    try:
        if aggregate and final_report is None:
            try:
                # aggregator expects a list of summaries or results; pass the cleaned text
                final_report = aggregator.aggregate([cleaned_text], llm_client=llm)
            except Exception as e:
                logger.exception("Aggregator failed: %s", e)
                final_report = {'executive_summary': 'Aggregator failed to produce a summary.'}
            try:
                db.save_final(report_id, final_report if isinstance(final_report, dict) else {'executive_summary': str(final_report)})
            except Exception:
                pass
    except Exception:
        # non-fatal
        pass
    try:
        ROOT = Path(__file__).resolve().parent.parent
        extracted_dir = ROOT / 'extracted_reports'
        extracted_dir.mkdir(parents=True, exist_ok=True)
        extracted_path = extracted_dir / f"extracted_report_{report_id}.txt"
        with open(extracted_path, "w", encoding="utf-8") as f:
            f.write(extracted_text_debug or "")
    except Exception:
        # fallback to current directory
        with open(f"extracted_report_{report_id}.txt", "w", encoding="utf-8") as f:
            f.write(extracted_text_debug or "")

    # 10️⃣ Return structured JSON
    # If language requested is Hindi, translate outputs using LLM while preserving JSON structure keys
    if req_lang and req_lang == 'hi':
        try:
            # Helper to translate a structured object (dict) by asking LLM to return same keys with values translated
            import json as _json

            def translate_structured(obj, role_name=''):
                # If it's a simple string, translate normally
                if obj is None:
                    return obj
                if isinstance(obj, str):
                    try:
                        return llm.chat(prompt=f"Translate the following {role_name} text into Hindi in clear, patient-friendly language:\n\n{obj}\n\nTranslated:")
                    except Exception:
                        return obj
                # If it's a dict-like structure, ask the model to return JSON with same keys and values translated
                try:
                    s = _json.dumps(obj, ensure_ascii=False)
                except Exception:
                    try:
                        s = str(obj)
                    except Exception:
                        s = ''
                prompt = (
                    "You are a clinical translator. Translate only the VALUES in the provided JSON object into Hindi. "
                    "Do NOT change the keys; return ONLY valid JSON (no surrounding text).\n\n"
                    f"Input JSON:\n{s}\n\nReturn JSON with the same keys and Hindi-translated values."
                )
                try:
                    translated = str(llm.chat(prompt=prompt) or "")
                    # Try parsing the returned JSON
                    try:
                        parsed = _json.loads(translated)
                        return parsed
                    except Exception:
                        # fallback: translate as plain text
                        return translated
                except Exception:
                    return obj

            final_report = translate_structured(final_report, 'final report')
            cardio_result = translate_structured(cardio_result, 'cardiology findings')
            psych_result = translate_structured(psych_result, 'psychology findings')
            pulmo_result = translate_structured(pulmo_result, 'pulmonology findings')
        except Exception:
            pass

    resp = {
        "report_id": report_id,
        "cardiology": ensure_dict(cardio_result, 'cardiology'),
        "psychology": ensure_dict(psych_result, 'psychology'),
        "pulmonology": ensure_dict(pulmo_result, 'pulmonology'),
        "dermatology": ensure_dict(derm_result, 'dermatology'),
        "endocrinology": ensure_dict(endo_result, 'endocrinology'),
        "gastroenterology": ensure_dict(gastro_result, 'gastroenterology'),
        "general_physician": ensure_dict(gp_result, 'general_physician'),
        "hematology": ensure_dict(hema_result, 'hematology'),
        "nephrology": ensure_dict(neph_result, 'nephrology'),
        "radiology": ensure_dict(radi_result, 'radiology'),
        "final_report": final_report,
        "extracted_text_debug": extracted_text_debug,  # For debugging only
        "is_blood_report": is_blood_report,
        # disclaimer removed from API-level response as UI no longer shows it
    }

    # If it looks like a blood report and hematology agent exists but wasn't run earlier, run it now and attach
    try:
        if is_blood_report and hema_agent and not resp.get('hematology'):
            hema_res = _safe_call(hema_agent, cleaned_text, 'hematology')
            resp['hematology'] = hema_res
            try:
                db.save_analysis(report_id, 'hematology', ensure_dict(hema_res, 'hematology'))
            except Exception:
                pass
    except Exception:
        pass

    return resp

# ---------- Run Server ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
