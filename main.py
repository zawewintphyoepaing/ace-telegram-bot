import subprocess
import sys

if __name__ == "__main__":
    # Userbot နှင့် Main Bot ကို Process နှစ်ခုခွဲ၍ ပြိုင်တူ run ခြင်း
    p1 = subprocess.Popen([sys.executable, "userbot.py"])
    p2 = subprocess.Popen([sys.executable, "bot.py"])

    # Process များ မရပ်သွားစေရန် စောင့်ကြည့်ခြင်း
    p1.wait()
    p2.wait()