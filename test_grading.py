import requests
import json

prompt = """You are an expert IGCSE Edexcel Examiner. 
Mark this student's answer.

QUESTION: 6(a)
OFFICIAL MARK SCHEME: Correct Answer: C (mackerel).
STUDENT'S ANSWER: C

Return a JSON object with:
{
  "marks_awarded": 1,
  "max_marks": 1,
  "feedback": "Correct."
}
"""

payload = {
    'model': 'llama3.2-vision:latest',
    'prompt': prompt,
    'stream': False,
    'temperature': 0.0
}

print("Sending request to Ollama (no JSON format forced)...")
response = requests.post('http://localhost:11434/api/generate', json=payload)
print(f"Status Code: {response.status_code}")
print("Raw Response:")
print(response.json().get('response'))
