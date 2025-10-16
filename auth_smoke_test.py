import requests
import time

for i in range(6):
    try:
        r = requests.get('http://127.0.0.1:8501')
        print('frontend up', r.status_code)
        break
    except Exception as e:
        print('waiting for frontend', i)
        time.sleep(0.8)

phone = '+15550009999'
print('send_otp ->', requests.post('http://127.0.0.1:8501/auth/send_otp', json={'phone': phone}).text)
resp = requests.post('http://127.0.0.1:8501/auth/send_otp', json={'phone': phone})
print('send2', resp.status_code, resp.text)
if resp.ok:
    try:
        otp = resp.json().get('otp')
    except Exception:
        otp = None
    if otp:
        print('verify ->', requests.post('http://127.0.0.1:8501/auth/verify_otp', json={'phone': phone, 'code': otp}).text)
        print('set_password ->', requests.post('http://127.0.0.1:8501/auth/set_password', json={'phone': phone, 'password':'Secret123'}).text)
        print('login ->', requests.post('http://127.0.0.1:8501/auth/login', json={'username': phone, 'password':'Secret123'}).text)
else:
    print('send_otp failed')
