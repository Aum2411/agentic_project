import requests, io, json

# 1) POST small text file to frontend /api/analyze
print('=== Running analyze test against http://127.0.0.1:8501/api/analyze ===')
files = {'report': ('sample.txt', io.BytesIO(b'Patient: John Doe\nDiagnosis: Sample test\nNotes: none'), 'text/plain')}
try:
    r = requests.post('http://127.0.0.1:8501/api/analyze', files=files, timeout=20)
    print('ANALYZE STATUS:', r.status_code)
    try:
        print('ANALYZE JSON:', json.dumps(r.json(), indent=2) )
    except Exception:
        print('ANALYZE TEXT:', r.text[:2000])
except Exception as e:
    print('ANALYZE REQ ERROR', e)

# 2) POST small cases array to backend /doctor/summary
print('\n=== Running summary test against http://127.0.0.1:8000/doctor/summary ===')
try:
    payload = {'cases': ['This patient has cough and fever. Recommended rest and paracetamol.', 'Second case: shortness of breath and wheeze.']}
    r2 = requests.post('http://127.0.0.1:8000/doctor/summary', json=payload, timeout=30)
    print('SUMMARY STATUS:', r2.status_code)
    try:
        print('SUMMARY JSON:', json.dumps(r2.json(), indent=2))
    except Exception:
        print('SUMMARY TEXT:', r2.text[:2000])
except Exception as e:
    print('SUMMARY REQ ERROR', e)
