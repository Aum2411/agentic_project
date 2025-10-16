from flask import Flask, render_template, request
import requests
import os
from typing import Any, Dict

app = Flask(__name__)

# Use environment variable if set, fallback to localhost
API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")

@app.route("/", methods=["GET", "POST"])
def index():
    report_text = None
    error_msg = None
    agent_outputs = None
    patient_name = None

    if request.method == "POST":
        file = request.files.get("report")
        if not file:
            error_msg = "No file selected!"
        else:
            try:
                # Send file to FastAPI backend
                files: Dict[str, Any] = {"file": (file.filename, file.stream, file.content_type)}  # type: ignore[arg-type]
                # forward language selection if present (and any other query params)
                lang = request.form.get('lang') or request.args.get('lang') or 'en'
                params = dict(request.args)
                params.setdefault('lang', lang)
                response = requests.post(f"{API_URL}/analyze", params=params, files=files)  # type: ignore[arg-type]
                if response.status_code == 200:
                    data = response.json()
                    report_text = data.get("final_report")
                    agent_outputs = {
                        "cardiology": data.get("cardiology"),
                        "psychology": data.get("psychology"),
                        "pulmonology": data.get("pulmonology")
                    }
                    patient_name = data.get("patient_name")
                else:
                    # Try to show backend error message if present
                    try:
                        err_data = response.json()
                        error_msg = err_data.get("error") or f"Error analyzing report. Status code: {response.status_code}"
                    except Exception:
                        error_msg = f"Error analyzing report. Status code: {response.status_code}"
            except Exception as e:
                report_text = f"Error: {str(e)}"

    return render_template("index.html", report=report_text, agent_outputs=agent_outputs, patient_name=patient_name, error=error_msg)

@app.route("/symptom_chat_api", methods=["POST"])
def symptom_chat_api():
    data = request.get_json() or {}
    session_id = data.get("session_id")
    message = data.get("message")

    if not message:
        return {"error": "message required"}, 400

    try:
        # If there's no session_id, create one by calling the backend start endpoint
        if not session_id:
            # determine lang from JSON payload or form
            if request.is_json:
                lang = (request.get_json() or {}).get('lang', 'en')
            else:
                lang = request.form.get('lang') or 'en'
            start_resp = requests.post(f"{API_URL}/chatbot/start", json={"lang": lang})
            if start_resp.ok:
                start_json = start_resp.json()
                session_id = start_json.get("session_id")
            else:
                return {"error": "Failed to create session"}, 500

        # determine lang for message
        if request.is_json:
            lang = (request.get_json() or {}).get('lang', 'en')
        else:
            lang = request.form.get('lang') or 'en'

        response = requests.post(f"{API_URL}/chatbot/message", json={"session_id": session_id, "message": message, "lang": lang})
        try:
            backend_json = response.json()
        except Exception:
            return {"error": "Invalid response from backend"}, 502

        # Normalize reply key for the frontend JS which expects `reply`.
        reply_text = backend_json.get("response") or backend_json.get("error") or str(backend_json)
        return {"reply": reply_text, "session_id": session_id}, response.status_code
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/symptom_summary_api", methods=["POST"])
def symptom_summary_api():
    data = request.get_json() or {}
    session_id = data.get("session_id")
    if not session_id:
        return {"error": "session_id required"}, 400
    try:
        lang = data.get('lang') or 'en'
        resp = requests.post(f"{API_URL}/chatbot/summary", json={"session_id": session_id, "lang": lang})
        try:
            j = resp.json()
        except Exception:
            return {"error": "Invalid response from backend"}, 502
        # backend returns {'structured_history': summary}
        summary = j.get("structured_history") if isinstance(j, dict) else str(j)
        return {"summary": summary}, resp.status_code
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/symptom_clear_api", methods=["POST"])
def symptom_clear_api():
    # Frontend uses this to clear UI state. There is no server-side deletion of conversations in this demo.
    return {"ok": True}


@app.route('/api/analyze', methods=['POST'])
def api_analyze():
    # New AJAX-friendly endpoint: accepts form multipart file 'report' and forwards to backend /analyze
    file = request.files.get('report')
    if not file:
        return ({"error": "No file selected"}, 400)
    try:
        # forward language and any query params such as 'specialist' or 'aggregate'
        lang = request.form.get('lang') or request.args.get('lang') or 'en'
        params = dict(request.args)
        # ensure lang param is present
        params.setdefault('lang', lang)
        files: Dict[str, Any] = {"file": (file.filename, file.stream, file.content_type)}  # type: ignore[arg-type]
        r = requests.post(f"{API_URL}/analyze", params=params, files=files)  # type: ignore[arg-type]
        # return backend response as-is
        return (r.text, r.status_code, {'Content-Type': 'application/json'})
    except Exception as e:
        return ({"error": str(e)}, 500)


@app.route('/chat_sessions', methods=['GET'])
def proxy_list_sessions():
    try:
        r = requests.get(f"{API_URL}/chatbot/sessions")
        return (r.text, r.status_code, {'Content-Type': 'application/json'})
    except Exception as e:
        return ({"sessions": []}, 500)


@app.route('/chat_sessions/<session_id>', methods=['GET','DELETE'])
def proxy_session(session_id):
    try:
        if request.method == 'GET':
            r = requests.get(f"{API_URL}/chatbot/sessions/{session_id}")
            return (r.text, r.status_code, {'Content-Type': 'application/json'})
        else:
            r = requests.delete(f"{API_URL}/chatbot/sessions/{session_id}")
            return (r.text, r.status_code, {'Content-Type': 'application/json'})
    except Exception as e:
        return ({"error": str(e)}, 500)


@app.route('/chat_sessions/<session_id>/export', methods=['GET'])
def proxy_export(session_id):
    try:
        r = requests.get(f"{API_URL}/chatbot/sessions/{session_id}/export")
        return (r.text, r.status_code, {'Content-Type': 'application/json'})
    except Exception as e:
        return ({"error": str(e)}, 500)


@app.route('/doctor/summary', methods=['POST'])
def proxy_doctor_summary():
    try:
        data = request.get_json() or {}
        r = requests.post(f"{API_URL}/doctor/summary", json=data)
        return (r.text, r.status_code, {'Content-Type': 'application/json'})
    except Exception as e:
        return ({"error": str(e)}, 500)


@app.route('/auth/signup', methods=['POST'])
def proxy_signup():
    try:
        data = request.get_json() or {}
        r = requests.post(f"{API_URL}/auth/signup", json=data)
        return (r.text, r.status_code, {'Content-Type': 'application/json'})
    except Exception as e:
        return ({"error": str(e)}, 500)


@app.route('/auth/login', methods=['POST'])
def proxy_login():
    try:
        data = request.get_json() or {}
        r = requests.post(f"{API_URL}/auth/login", json=data)
        return (r.text, r.status_code, {'Content-Type': 'application/json'})
    except Exception as e:
        return ({"error": str(e)}, 500)


@app.route('/auth/send_otp', methods=['POST'])
def proxy_send_otp():
    try:
        data = request.get_json() or {}
        r = requests.post(f"{API_URL}/auth/send_otp", json=data)
        return (r.text, r.status_code, {'Content-Type': 'application/json'})
    except Exception as e:
        return ({"error": str(e)}, 500)


@app.route('/auth/verify_otp', methods=['POST'])
def proxy_verify_otp():
    try:
        data = request.get_json() or {}
        r = requests.post(f"{API_URL}/auth/verify_otp", json=data)
        return (r.text, r.status_code, {'Content-Type': 'application/json'})
    except Exception as e:
        return ({"error": str(e)}, 500)


@app.route('/auth/set_password', methods=['POST'])
def proxy_set_password():
    try:
        data = request.get_json() or {}
        r = requests.post(f"{API_URL}/auth/set_password", json=data)
        return (r.text, r.status_code, {'Content-Type': 'application/json'})
    except Exception as e:
        return ({"error": str(e)}, 500)


@app.route('/doctor/verify', methods=['POST'])
def proxy_doctor_verify():
    try:
        # forward multipart/form-data or JSON
        if request.files:
            files = {}
            for k, f in request.files.items():
                files[k] = (f.filename, f.stream, f.content_type)
            data = request.form.to_dict()
            r = requests.post(f"{API_URL}/doctor/verify", files=files, data=data)
        else:
            data = request.get_json() or {}
            r = requests.post(f"{API_URL}/doctor/verify", json=data)
        return (r.text, r.status_code, {'Content-Type': 'application/json'})
    except Exception as e:
        return ({"error": str(e)}, 500)


@app.route('/doctor/case', methods=['POST'])
def proxy_create_case():
    try:
        data = request.get_json() or {}
        r = requests.post(f"{API_URL}/doctor/case", json=data)
        return (r.text, r.status_code, {'Content-Type': 'application/json'})
    except Exception as e:
        return ({"error": str(e)}, 500)


@app.route('/doctor/cases', methods=['GET'])
def proxy_list_cases():
    try:
        token = request.args.get('token')
        r = requests.get(f"{API_URL}/doctor/cases", params={'token': token})
        return (r.text, r.status_code, {'Content-Type': 'application/json'})
    except Exception as e:
        return ({"error": str(e)}, 500)


@app.route('/doctor/case/<case_id>', methods=['DELETE'])
def proxy_delete_case(case_id):
    try:
        r = requests.delete(f"{API_URL}/doctor/case/{case_id}")
        return (r.text, r.status_code, {'Content-Type': 'application/json'})
    except Exception as e:
        return ({"error": str(e)}, 500)


@app.route('/chat_sessions/new', methods=['POST'])
def proxy_new_session():
    try:
        r = requests.post(f"{API_URL}/chatbot/start", json={})
        return (r.text, r.status_code, {'Content-Type': 'application/json'})
    except Exception as e:
        return ({"error": str(e)}, 500)


@app.route('/chat_sessions/<session_id>/title', methods=['PUT'])
def proxy_update_title(session_id):
    try:
        data = request.get_json() or {}
        r = requests.put(f"{API_URL}/chatbot/sessions/{session_id}/title", json=data)
        return (r.text, r.status_code, {'Content-Type': 'application/json'})
    except Exception as e:
        return ({"error": str(e)}, 500)

if __name__ == "__main__":
    app.run(port=8501, debug=True)
