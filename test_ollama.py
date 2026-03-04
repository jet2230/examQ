import requests, json, sys

def test():
    prompt = f"Identify ALL question and sub-question IDs (e.g. 1, 1(a), 1(b)(i), 2, 3(c)) on this IGCSE page. Return a JSON list of strings only. TEXT:\n{sys.stdin.read()}"
    try:
        resp = requests.post('http://127.0.0.1:11434/api/generate', json={
            'model': 'llama3', 
            'prompt': prompt, 
            'stream': False, 
            'format': 'json'
        }, timeout=45)
        print(resp.json().get('response', 'NO_RESPONSE'))
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    test()
