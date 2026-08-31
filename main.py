import subprocess
import sys
import os
import threading
import time
from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return "ACE Bot is running successfully!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, use_reloader=False)

def keep_alive_process(script_name):
    while True:
        print(f"[SYSTEM] Starting {script_name}...", flush=True)
        try:
            # Log များကို Buffer မလုပ်ဘဲ တိုက်ရိုက်ပြစေရန် PYTHONUNBUFFERED=1 သတ်မှတ်ခြင်း
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"

            process = subprocess.Popen(
                [sys.executable, script_name],
                stdout=sys.stdout,
                stderr=sys.stderr,
                env=env
            )
            process.wait()
            print(f"[SYSTEM] ⚠️ {script_name} stopped! Restarting in 5 seconds...", flush=True)
        except Exception as e:
            print(f"[SYSTEM] ❌ Error running {script_name}: {e}", flush=True)
        
        time.sleep(5)

if __name__ == "__main__":
    web_thread = threading.Thread(target=run_web, daemon=True)
    web_thread.start()

    t1 = threading.Thread(target=keep_alive_process, args=("userbot.py",), daemon=True)
    t2 = threading.Thread(target=keep_alive_process, args=("bot.py",), daemon=True)

    t1.start()
    t2.start()

    # Main Process မရပ်သွားစေရန်
    while True:
        time.sleep(3600)
