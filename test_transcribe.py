# -*- coding: utf-8 -*-
import asyncio, io, wave, struct, json, asyncpg
from datetime import timedelta
from app.core.config import settings
from app.core.security import create_access_token
import urllib.request

async def run_test():
    conn = await asyncpg.connect(settings.DATABASE_URL)
    try:
        user = await conn.fetchrow('SELECT id, phone_number FROM users LIMIT 1')
        token = create_access_token(str(user['id']), timedelta(minutes=60))
        print('Created test token for user:', user['phone_number'])
        
        # Create small test wav
        wav_io = io.BytesIO()
        with wave.open(wav_io, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            for i in range(16000):
                val = int(32767.0 * 0.05 * (i % 40 == 0))
                wf.writeframes(struct.pack('<h', val))
        audio_data = wav_io.getvalue()
        
        # Test HTTP multipart request
        boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
        header_bytes = (
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="file"; filename="test.wav"\r\n'
            f'Content-Type: audio/wav\r\n\r\n'
        ).encode('latin1')
        footer_bytes = f'\r\n--{boundary}--\r\n'.encode('latin1')
        body = header_bytes + audio_data + footer_bytes
        
        req = urllib.request.Request(
            'http://127.0.0.1:8000/api/v1/chat/transcribe',
            data=body,
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': f'multipart/form-data; boundary={boundary}',
            },
            method='POST'
        )
        with urllib.request.urlopen(req) as resp:
            print('HTTP status:', resp.status)
            body_resp = resp.read().decode('utf-8')
            print('Response body:', body_resp)
            data = json.loads(body_resp)
            assert data.get('success') is True
            print('ENDPOINT /api/v1/chat/transcribe 100% OPERATIONAL!')
    finally:
        await conn.close()

if __name__ == '__main__':
    asyncio.run(run_test())
