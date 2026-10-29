# -*- coding: utf-8 -*-
import urllib.request, json, asyncpg, asyncio
from datetime import timedelta
from app.core.config import settings
from app.core.security import create_access_token

async def test_endpoint():
    conn = await asyncpg.connect(settings.DATABASE_URL)
    user = await conn.fetchrow("SELECT id FROM users LIMIT 1")
    await conn.close()
    token = create_access_token(str(user["id"]), timedelta(minutes=60))
    
    with open("C:/Users/Simplon-CI/.gemini/antigravity-ide/scratch/french_test.wav", "rb") as f:
        audio_data = f.read()
        
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    header_bytes = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="french_test.wav"\r\n'
        f"Content-Type: audio/wav\r\n\r\n"
    ).encode("latin1")
    footer_bytes = f"\r\n--{boundary}--\r\n".encode("latin1")
    body = header_bytes + audio_data + footer_bytes
    
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/chat/transcribe",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        d = json.loads(resp.read().decode("utf-8"))
        print("HTTP Status:", resp.status)
        print("API Transcribed Text:", repr(d.get("text")))
        assert d.get("text") == "J'ai récolté 500 kg de cacao ce matin à Soubré.", f"Mismatch: {d.get('text')}"
        print("API VERIFICATION 100% SUCCESSFUL!")

if __name__ == "__main__":
    asyncio.run(test_endpoint())
