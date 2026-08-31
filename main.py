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
    # Threading ထဲမှာ Run တဲ့အတွက် use_reloader=False ထည့်ပေးရပါမယ်
    app.run(host="0.0.0.0", port=port, use_reloader=False)

def keep_alive_process(script_name):
    while True:
        print(f"[SYSTEM] Starting {script_name}...")
        try:
            # stdout=sys.stdout ကိုသုံးမှ Render Dashboard မှာ Error လာပြပါမယ်
            process = subprocess.Popen(
                [sys.executable, script_name],
                stdout=sys.stdout,
                stderr=sys.stderr
            )
            process.wait()  # Process ပြီးဆုံး/ရပ်တန့်သွားသည်အထိ စောင့်မည်
            print(f"[SYSTEM] ⚠️ {script_name} crashed or stopped! Restarting in 5 seconds...")
        except Exception as e:
            print(f"[SYSTEM] ❌ Error running {script_name}: {e}")
        
        # Crash ဖြစ်သွားပါက 5 စက္ကန့်နားပြီးမှ ပြန်စမည် (Auto-healing)
        time.sleep(5)

if __name__ == "__main__":
    # 1. Render အတွက် Flask Web Server ကို Background Thread ဖြင့် စတင်ခြင်း
    web_thread = threading.Thread(target=run_web)
    web_thread.daemon = True
    web_thread.start()

    # 2. Userbot နှင့် Main Bot ကို Auto-Restart စနစ်ဖြင့် Thread များခွဲ၍ ပြိုင်တူ Run ခြင်း
    t1 = threading.Thread(target=keep_alive_process, args=("userbot.py",))
    t2 = threading.Thread(target=keep_alive_process, args=("bot.py",))

    t1.start()
    t2.start()

    # Main Thread မရပ်သွားစေရန် စောင့်ကြည့်ခြင်း
    t1.join()
    t2.join()
