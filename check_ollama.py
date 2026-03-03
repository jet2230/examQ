import os
import subprocess

def check_ollama():
    print("Checking Ollama configuration...")
    # Check if OLLAMA_HOST is set in environment
    ollama_host = os.environ.get('OLLAMA_HOST')
    print(f"OLLAMA_HOST env var: {ollama_host}")
    
    # Check what ports are listening
    try:
        output = subprocess.check_output(['netstat', '-tulpn'], stderr=subprocess.STDOUT).decode()
        for line in output.split('
'):
            if '11434' in line:
                print(f"Listening: {line}")
    except:
        print("Could not run netstat. Try ss instead.")
        try:
            output = subprocess.check_output(['ss', '-tulpn'], stderr=subprocess.STDOUT).decode()
            for line in output.split('
'):
                if '11434' in line:
                    print(f"Listening: {line}")
        except:
            print("Could not check listening ports.")

if __name__ == "__main__":
    check_ollama()
