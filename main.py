import subprocess
import sys
import os
import threading
from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return "ACE Bot is running successfully!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    # Render အတွက် Web Server ကို Background တွင် စတင်ခြင်း
    web_thread = threading.Thread(target=run_web)
    web_thread.daemon = True
    web_thread.start()

    # Userbot နှင့် Main Bot ကို Process နှစ်ခုခွဲ၍ ပြိုင်တူ run ခြင်း
    p1 = subprocess.Popen([sys.executable, "userbot.py"])
    p2 = subprocess.Popen([sys.executable, "bot.py"])

    # Process များ မရပ်သွားစေရန် စောင့်ကြည့်ခြင်း
    p1.wait()
    p2.wait()
