import urllib.request
import json

token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxYTE1ODBiZS04ZWQwLTRlNzctYjM1OS05MWYwNzYzZDI0ZDEiLCJleHAiOjIxMDgwNDI0MzUsImlhdCI6MTc5MjY4MjQzNX0.ulIjV3N8uIlEyNoeE9f57UFNMTlSzsTMW68WAGpUXRQ'
req = urllib.request.Request('http://127.0.0.1:8000/api/v1/cooperative/predictions/churn', headers={'Authorization': 'Bearer ' + token})

try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
        print('SUCCESS 200 OK!')
        print('Coop:', data.get('cooperative_name'))
        print('Metrics:', data.get('metrics'))
        print('Confusion Matrix:', data.get('confusion_matrix'))
        print(f"Total members: {data.get('total_members')}, Critical: {data.get('critical_count')}")
        for p in data.get('planters', []):
            name = p.get('nom_complet')
            village = p.get('village')
            culture = p.get('culture')
            score = p.get('risk_score')
            level = p.get('risk_level')
            factors = p.get('factors')
            print(f"  - {name:<20} ({village}, {culture}) -> Score: {score}%, Niveau: {level}")
        print('Summary:', data.get('summary_text'))
except urllib.error.HTTPError as e:
    print('HTTP ERROR:', e.code, e.read().decode())
except Exception as e:
    print('ERROR:', e)
