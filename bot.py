import os
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
import io
import asyncio
import logging
import traceback
import httpx
import re
import time
import urllib.parse
import requests
import datetime
import edge_tts
import json

from gtts import gTTS
from PIL import Image, ImageOps
from io import BytesIO
from google import genai
from google.genai import types
from google.genai.errors import ClientError
from weasyprint import HTML


from telegram import InlineQueryResultCachedDocument, InlineQueryResultCachedVideo
from telegram import InlineQueryResultAudio, InlineQueryResultArticle, InputTextMessageContent
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.request import HTTPXRequest
from telegram.error import BadRequest
from dotenv import load_dotenv

HF_API_URL = "https://api-inference.huggingface.co/models/timbrooks/instruct-pix2pix"
now = datetime.datetime.now()
current_date_str = now.strftime("%Y-%m-%d") 
current_time_str = now.strftime("%H:%M:%S")


load_dotenv()

HF_TOKEN = os.getenv("HF_TOKEN")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_KEYS = [
    os.getenv("GEMINI_API_KEY_1"),
    os.getenv("GEMINI_API_KEY_2"),
    os.getenv("GEMINI_API_KEY_3"),
    os.getenv("GEMINI_API_KEY_4")
]

current_key_index = 0

def get_next_client():
    global current_key_index
    key = API_KEYS[current_key_index]
    current_key_index = (current_key_index + 1) % len(API_KEYS)
    
    # Official HttpOptions ဖြင့် timeout သတ်မှတ်ခြင်း (milliseconds ဖြင့် သတ်မှတ်သည်)
    client = genai.Client(
        api_key=key,
        http_options=types.HttpOptions(timeout=600000) # 600 seconds
    )
    return client

MODEL_CATEGORIES = {
    "flash_lite": {
        "title": "🍃 Flash-Lite Models",
        "models": {
            "lite_3.5": "gemini-3.5-flash-lite",
            "lite_3.1": "gemini-3.1-flash-lite"
        }
    },
    "flash": {
        "title": "⚡ Flash Models",
        "models": {
            "flash_3.5": "gemini-3.5-flash",
            "flash_3.6": "gemini-3.6-flash",
            "flash_3.7": "gemini-3.7-flash"
            
        }
    },
    "pro": {
        "title": "🧠 PRO Models",
        "models": {
            "pro_1.5": "gemini-1.5-pro",
            "pro_2.5": "gemini-2.5-pro",
            "pro_3.1": "gemini-3.1-pro-preview"
        }
    }
}

USER_SELECTED_MODELS = {}

USER_CHATS = {}        
USER_CLIENTS = {}     
USER_LAST_ACTIVE = {} 
TIMEOUT_LIMIT = 3600

def get_or_create_chat_session(chat_id, model_name, config):
    current_time = time.time()
    
    if chat_id in USER_LAST_ACTIVE:
        if current_time - USER_LAST_ACTIVE[chat_id] > TIMEOUT_LIMIT:
            if chat_id in USER_CHATS:
                del USER_CHATS[chat_id]
            if chat_id in USER_CLIENTS:       
                del USER_CLIENTS[chat_id]
            if chat_id in USER_LAST_ACTIVE:
                del USER_LAST_ACTIVE[chat_id]

    if chat_id not in USER_CHATS:
        client = get_next_client()
        USER_CLIENTS[chat_id] = client         
        USER_CHATS[chat_id] = client.chats.create(
            model=model_name,
            config=config
        )
    
   
    USER_LAST_ACTIVE[chat_id] = current_time
    return USER_CHATS[chat_id]
 
    
async def models_command(update, context):
    keyboard = [
        [InlineKeyboardButton("🍃 Flash-Lite Models", callback_data="cat_flash_lite")],
        [InlineKeyboardButton("⚡ Flash Models", callback_data="cat_flash")],
        [InlineKeyboardButton("🧠 PRO Models", callback_data="cat_pro")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text("🔧 ကျေးဇူးပြု၍ အသုံးပြုလိုသော Model အမျိုးအစား (Category) ကို ရွေးချယ်ပါ:", reply_markup=reply_markup)
    elif update.callback_query:
        query = update.callback_query
        await query.answer()
        try:
            await query.edit_message_text("🔧 ကျေးဇူးပြု၍ အသုံးပြုလိုသော Model အမျိုးအစား (Category) ကို ရွေးချယ်ပါ:", reply_markup=reply_markup)
        except BadRequest as e:
            if "Message is not modified" in str(e):
                pass
            else:
                raise e

async def handle_model_selection(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    if data == "back_to_main":
        await models_command(update, context)
        return

    if data.startswith("cat_"):
        cat_key = data.replace("cat_", "")
        category = MODEL_CATEGORIES.get(cat_key)
        
        if category:
            keyboard = []
            for m_key, m_name in category["models"].items():
                keyboard.append([InlineKeyboardButton(f"🔹 {m_name}", callback_data=f"set_{m_key}")])
            
            keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_main")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(f"📂 {category['title']} အောက်တွင် ရရှိနိုင်သော Model များ:", reply_markup=reply_markup)

    elif data.startswith("set_"):
        m_key = data.replace("set_", "")
        selected_model = None
        
        for cat in MODEL_CATEGORIES.values():
            if m_key in cat["models"]:
                selected_model = cat["models"][m_key]
                break
                
        if selected_model:
            USER_SELECTED_MODELS[chat_id] = selected_model
            
            # --- Memory မဖျက်ဘဲ Model ပဲ ပြောင်းမည့်အပိုင်း ---
            if chat_id in USER_CHATS:
                    # 1. Chat Session အဟောင်းထဲက ပြောထားသမျှ History ကို ယူမည်
                old_history = USER_CHATS[chat_id].get_history()
                
                    # 2. လက်ရှိ Client ကို ယူမည် (မရှိရင် အသစ်ယူမည်)
                client = USER_CLIENTS.get(chat_id) or get_next_client()
                USER_CLIENTS[chat_id] = client
                
                    # 3. Model အသစ် + History အဟောင်းနဲ့ Chat Session အသစ် ပြန်ဆောက်မည်
                USER_CHATS[chat_id] = client.chats.create(
                    model=selected_model,
                    history=old_history
                )
            # -----------------------------------------------
            
            await query.edit_message_text(f"✅ အောင်မြင်ပါသည်! Memory များကို ထိန်းသိမ်းလျက် အသုံးပြုမည့် Model အဖြစ် **{selected_model}** သို့ ပြောင်းလဲလိုက်ပါပြီ။")


   
async def about_ace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    about_text = (
        "About ACE\n\n"
        "Hi,I'm ACE!,  AI Assistant Developed for Academic Assistances. \n\n"
        "✨ ACE is Powerful in:\n\n"
        "  • Explaining Programming, Mathematics, Physics, English, and    Myanmar. \n\n"
        "  • Generating PDF Study Guides via Photos and Sheets.\n\n"
        "  • Answering General Questions with High Performance.\n\n"
        "  * If any problems about ACE occurs, contact @mg_zawe_wint( Developer of ACE ).\n\n"
    )

    await update.message.reply_text(about_text)
# --------------------------------------------------------

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


VISION_MODEL = 'gemini-3.6-flash'
DEFAULT_MODEL = 'gemini-3.6-flash'

USER_BUFFERS = {}
USER_JOBS = {}
USER_MODES = {}

PROMPTS = {
    'math': """You are an expert Mathematics Tutor. Analyze the image:
1. Solve all exercises and examples step-by-step with clean mathematical logic.
2. Highlight core formulas and rules in pastel callout boxes.
3. Write explanations in Burmese. Keep headings and math expressions in English. Use standard HTML tags (<sup>, <sub>, <span>) for math.
Return standard HTML <body> only.""",

    'physics': """You are an expert Physics Tutor. Analyze the image:
1. Explain physics concepts, principles, and laws clearly.
2. Solve all practice problems, exercises, and examples step-by-step showing given values, formulas, and units.
3. Write natural explanations in Burmese. Keep formulas, terms, and units in English.
Return standard HTML <body> only.""",

    'flashcard': """You are an Expert Study Assistant. Analyze the image:
1. Extract key concepts, definitions, terms, or formulas.
2. Create clear Flashcards in Q&A format (Question / Answer or Front / Back style) in English.
3. Keep explanations concise, clear, and easy to memorize.
Return standard HTML <body> only.""",

    'programming_language': """You are an Expert Software Engineer & Computer Science Instructor. Analyze the image or request:
1. Explain programming concepts, logic, functions, and algorithms clearly for any language (Python, C/C++, Java, JavaScript, etc.).
2. Provide full, working source code with clean syntax for any exercises or code examples shown.
3. Include clear code comments and step-by-step execution logic.
4. Find bugs, trace errors, and provide optimized solutions.
Return standard HTML <body> only.""",

    'quiz': """You are an Expert Quiz Master & Assessment Creator. Analyze the image or study material provided and generate a multiple-choice question (MCQ) quiz.
Strictly adhere to the JSON format specified below. Return ONLY valid JSON block without markdown backticks.

{
  "number_of_questions_to_generate": 5,
  "questions": [
    {
      "questionNumber": 1,
      "question": "Question text here.",
      "answerOptions": [
        {
          "text": "Correct answer choice.",
          "isCorrect": true,
          "rationale": "Explanation why this is correct."
        },
        {
          "text": "Incorrect answer choice.",
          "isCorrect": false,
          "rationale": "Explanation."
        }
      ],
      "hint": "Short hint.",
      "tags": ["tag"]
    }
  ]
}""",
  
    'english': """You are an English Language & Grammar Instructor. Analyze the image:
1. Match the grammar exercises with their corresponding answers with explanations.
2. Explain grammar rules, structures, and vocabulary clearly in Burmese.
3. Provide full answers and explanations for all exercises and quiz questions in the image.
4. Strictly DO NOT include any math or science formulas.
Return standard HTML <body> only.""",

    'burmese': """You are an expert Myanmar Literature Tutor. Analyze the textbook images strictly and generate a 20-mark high-scoring study guide format in clean HTML.
MAIN TITLE EXTRACTION RULE (CRITICAL):
- Locate the main title by identifying the LARGEST and BOLDEST font text across the images.
- Treat ALL provided images as ONE CONTINUOUS LESSON under this main title. DO NOT split them into multiple lessons per page.
- Strictly use the exact printed title text. DO NOT invent or alter titles.

Structure the HTML response strictly into:
1. နိဒါန်း (Introduction Paragraph):
   - စာအုပ်ပါ မူရင်း ခေါင်းစဉ် အတိအကျ
   - ရေးသူ/ကဗျာဆရာ ကောပြ/ကဗျာ အမျိုးအစား
   - ရေးသားရသည့် ရည်ရွယ်ချက်နှင့် အဓိက အသိအမြင်။

2. စာကိုယ် အဓိကအချက်များနှင့် အသိအမြင်များ (Main Body Content):
   - ပုံပါ စာသားများမှ အဓိက Main Points များကို စာရေးသူ၏ ရှုထောင့်၊
   - ရရှိသော အဓိက အတွေးအခေါ်/သင်ခန်းစာများကို Bullet Points ဖြင့် စနစ်တကျ ထုတ်နှုတ်ပေးရန်၊
   - ပါဝင်သော ရသနှင့် အချက်အလက်များ (ရှိပါက)။

3. နိဂုံး ခြုံငုံသုံးသပ်ချက် (Conclusion Paragraph):
   - စာအုပ်ပါ အကြောင်းအရာတစ်ခုလုံးကို ခြုံငုံသုံးသပ်ချက် အသိအမြင်များ။

Return ONLY standard HTML <body> structure in natural Burmese language based STRICTLY on the image.""",

    'general': """You are an Academic Tutor. Analyze the image:
1. Think deeply.
2. Summarize main concepts, key definitions, and notes clearly.
3. Solve any exercises or practice questions shown in the image.
4. Write explanations in Burmese with clean formatting.
Return standard HTML <body> only."""
}
# ဘာသာရပ်အလိုက် Temperature နှင့် System Instruction သတ်မှတ်ချက်များ
SUBJECT_CONFIGS = {
    'math': {
        'temperature': 0.1,
        'system_instruction': "STRICT INSTRUCTION: You are a Math Expert. DO NOT use LaTeX, MathJax, or dollar signs ($ or $$). You MUST write all formulas using standard HTML tags (e.g., <sup>, <sub>, <span>) and Unicode(like λ, R_H). Output plain HTML only without any markdown code blocks.",
    },
        'physics': {
        'temperature': 0.1,
        'system_instruction': "STRICT INSTRUCTION: You are a Physics Expert. DO NOT use LaTeX, MathJax, or dollar signs ($ or $$). You MUST write all formulas using standard HTML tags (e.g., <sup>, <sub>, <span>) and Unicode (like λ, R_H). Output plain HTML only without any markdown code blocks.",
    },
    'programming_language': {
        'temperature': 0.1,
        'system_instruction': "You are a Programming Language Expert. Provide precise code enclosed in <pre><code> tags.Find bug errors and Explain logically. Output plain HTML only without any markdown code blocks.",
    },
    'english': {
        'temperature': 0.3,
        'system_instruction': "You are an English Language Expert. Provide natural, clear, and grammatically correct explanations. Output plain HTML only.",
    },
    'burmese': {
        'temperature': 0.3,
        'system_instruction': "You are a Myanmar Literature Expert. Provide natural, grammatically correct Burmese text. Output plain HTML only.",
    },
    'flashcard': {
        'temperature': 0.3,
        'system_instruction': "You are a Flashcard generation expert. Output plain HTML only.",
    },
    'quiz': {
        'temperature': 0.3,
        'system_instruction': "You are an expert assessment generator. Output valid JSON only, exactly matching the requested quiz schema.",
    },
    'general': {
        'temperature': 0.3,
        'system_instruction': "You are a helpful academic assistant. Format your output securely in HTML without using Markdown or LaTeX.",
    }
}
# သင့် Private Channel ID အမှန်ကို ပြောင်းထည့်ရန် (ဥပမာ -1001234567890)
ARCHIVE_CHANNEL_ID = -1003943796781

async def movie_search_command(update, context):
    query = " ".join(context.args).strip().lower()
    
    if not query:
        await update.message.reply_text("ကျေးဇူးပြု၍ ရှာလိုသော ဇာတ်ကားနာမည် ရိုက်ထည့်ပါ (ဥပမာ - /search avatar)")
        return

    chat_id = update.effective_chat.id
    await update.message.reply_text(f"🔍 '{query}' ကို ရှာဖွေနေပါပြီ ခဏစောင့်ပါ...")

    # Userbot ဆီသို့ ဇာတ်ကားရှာခိုင်းရန် လှမ်းပို့မည်
    userbot_target = 8081029424  # သင့် userbot ရဲ့ ID အမှန်
    try:
        await context.bot.send_message(
            chat_id=userbot_target, 
            text=f"SEARCH_MOVIE:{query}:{chat_id}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ ရှာဖွေရာတွင် အမှားရှိနေပါသည်: {str(e)}")
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if not update.message.voice:
        await update.message.reply_text("ကျေးဇူးပြု၍ အသံဖိုင် (Voice message) ကို ပို့ပေးပါ။")
        return

    chosen_model = USER_SELECTED_MODELS.get(chat_id, DEFAULT_MODEL)
    client = USER_CLIENTS.get(chat_id) or get_next_client()
    USER_CLIENTS[chat_id] = client

    voice_path = f"user_voice_{chat_id}.ogg"
    output_voice_path = f"bot_reply_{chat_id}.ogg"

    try:
        # ၁။ Telegram အသံဖိုင်ကို ဒေါင်းလုပ်ဆွဲခြင်း
        voice_file = await update.message.voice.get_file()
        await voice_file.download_to_drive(voice_path)

        if os.path.getsize(voice_path) < 1000:
            await update.message.reply_text("အသံဖိုင် အချက်အလက် မပြည့်စုံပါ။ ကျေးဇူးပြု၍ အသံကို တစ်ချက်လောက် ထပ်ပို့ပေးပါ။")
            return

        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        # ၂။ Gemini API (Flash-Lite / Flash) ဖြင့် အသံဖိုင်ကို တိုက်ရိုက်ဖတ်၍ စာသားပြောင်းခြင်း (RAM လုံးဝမစားပါ)
        def transcribe_with_gemini():
            # mime_type ကို audio/ogg လို့ တိုက်ရိုက်သတ်မှတ်ပေးလိုက်ခြင်းဖြင့် error ကို ဖြေရှင်းနိုင်သည်
            audio_file = client.files.upload(
                file=voice_path,
				config={"mime_type": "audio/ogg"}
            )
            prompt = (
                "Listen to this audio file and transcribe what was said"
                " accurately into Burmese or the language spoken. Output only"
                " the transcript text."
            )
            response = client.models.generate_content(
                model=chosen_model, contents=[audio_file, prompt]
            )
            try:
                client.files.delete(name=audio_file.name)
            except:
                pass
            return response.text

        user_text = await asyncio.to_thread(transcribe_with_gemini)
        print(f"Gemini Audio Transcription: {user_text}")

        if not user_text or not user_text.strip():
            user_text = "မင်္ဂလာပါ"

        # ၃။ Text to Text (Gemini Chat Session ဖြင့် အဖြေရှာခြင်း)
        dynamic_system_instruction = (
            f"Today's current date is {current_date_str} and the current time is {current_time_str}. "
            "You are ACE, an intelligent AI academic assistant developed by @mg_zawe_wint. "
            "Always reply in the exact same language that the user uses."
        )

        chat_config = types.GenerateContentConfig(
            temperature=0.3,
            system_instruction=dynamic_system_instruction
        )
        chat_session = get_or_create_chat_session(chat_id, chosen_model, chat_config)

        response = await asyncio.to_thread(
            chat_session.send_message,
            user_text
        )
        
        reply_text = response.text or "တောင်းပန်ပါတယ်၊ အဖြေထုတ်လို့ မရပါဘူး။"
        clean_text = reply_text
        clean_text = clean_text.replace("<p>", "").replace("</p>", "\n")
        clean_text = clean_text.replace("<em>", "").replace("</em>", "\n")
        clean_text = clean_text.replace("<ul>", "").replace("</ul>", "\n")
        clean_text = clean_text.replace("<li>", "• ").replace("</li>", "\n")
        clean_text = clean_text.replace("<strong>", "").replace("</strong>", "")
        clean_text = clean_text.replace("<b>", "").replace("</b>", "")  
        clean_text = clean_text.replace("<i>", "").replace("</i>", "") 
        clean_text = clean_text.replace("<pre><code>", "```\n").replace("</code></pre>", "\n```\n")
        clean_text = clean_text.replace("&lt;", "<").replace("&gt;", ">")
        clean_text = clean_text.replace("<div>", "").replace("</div>", "")
        clean_text = clean_text.replace("<html>", "").replace("</html>", "")
        clean_text = clean_text.replace("<body>", "").replace("</body>", "")
        for tag in ["<p>", "</p>", "<em>", "</em>", "<ul>", "</ul>", "<strong>", "</strong>", "<b>", "</b>", "<i>", "</i>", "<div>", "</div>", "<html>", "</html>", "<body>", "</body>"]:
            clean_text = clean_text.replace(tag, "")
        clean_text = clean_text.replace("<li>", "• ").replace("</li>", "\n")

        # ၄။ Text to Voice (Edge-TTS ဖြင့် .ogg ဖော်မတ်ဖြင့် သိမ်းဆည်းခြင်း)
        try:
            import re
            myanmar_chars = re.findall(r'[\u1000-\u139F]', reply_text)
            if len(myanmar_chars) > 5:
                voice_name = "my-MM-NilarNeural" if "ရှင်" in reply_text else "my-MM-ThihaNeural"
            else:
                voice_name = "en-US-JennyNeural" if "female" in user_text.lower() else "en-US-ChristopherNeural"
                
            communicate = edge_tts.Communicate(clean_text, voice_name)
            await communicate.save(output_voice_path)
        except Exception as tts_err:
            print(f"Edge-TTS Error: {tts_err}")
            await update.message.reply_text(reply_text)
            return

        # ၅။ Telegram သို့ လှိုင်းတွန့်ပါသော Voice Note ပုံစံဖြင့် ပြန်လည်ပို့ဆောင်ခြင်း
        with open(output_voice_path, 'rb') as audio:
            await update.message.reply_voice(voice=audio)

    except Exception as e:
        print(f"General error in voice pipeline: {e}")
        await update.message.reply_text("တောင်းပန်ပါတယ်၊ အသံဖိုင် လုပ်ဆောင်ရာတွင် အမှားအယွင်း ရှိသွားပါသည်။")

    finally:
        if os.path.exists(voice_path):
            try: os.remove(voice_path)
            except: pass
        if os.path.exists(output_voice_path):
            try: os.remove(output_voice_path)
            except: pass 


       

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hi, I am ACE✨ ,")
async def set_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📚 Study Modes", callback_data='menu_study')],
        [InlineKeyboardButton("🎵 Entertainment Modes", callback_data='menu_entertainment')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📌 ကျေးဇူးပြု၍ Mode အမျိုးအစားကို ရွေးချယ်ပါ :", reply_markup=reply_markup)

async def run_code_api(language: str, source_code: str):
    url = "https://emkc.org/api/v2/piston/execute"
    
    lang_map = {
        'c': 'c',
        'cpp': 'cpp',
        'python': 'python',
        'py': 'python',
        'java': 'java',
        'javascript': 'javascript',
        'js': 'javascript'
    }
    
    piston_lang = lang_map.get(language.lower(), 'python')
    
    payload = {
        "language": piston_lang,
        "version": "*",
        "files": [{"content": source_code}]
    }
    
    def post_request():
        return requests.post(url, json=payload, timeout=10)

    try:
        response = await asyncio.to_thread(post_request)
        if response.status_code == 200:
            result = response.json()
            run_result = result.get("run", {})
            output = run_result.get("output", "No output returned.")
            return output
        else:
            return "❌ Code execution service error."
    except Exception as e:
        return f"❌ Connection error: {str(e)}"

async def run_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ပုံစံ: /run python print("Hello")
    if not context.args:
        await update.message.reply_text(
            "⚠️ အသုံးပြုပုံ: /run [language] [code]\n"
            "ဥပမာ: /run python print('Hello ACE')"
        )
        return

    lang = context.args[0]
    code = " ".join(context.args[1:])
    
    if not code:
        await update.message.reply_text("⚠️ Run မည့် Code ထည့်ရန် ကျန်ပါသေးသည်။")
        return

    await update.message.reply_text("⏳ Code ကို Compile လုပ်နေပါပြီ...")
    
    output = await run_code_api(lang, code)
    
    # Output ရှည်ရင် Markdown code block နဲ့ ပို့ပေးရန်
    formatted_output = f"💻 **Execution Output ({lang}):**\n<pre><code>{output}</code></pre>"
    await update.message.reply_text(formatted_output, parse_mode="HTML")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    # 1. Study Modes မီနူးသို့ သွားရန်
    if data == 'menu_study':
        keyboard = [
            [InlineKeyboardButton("📐 Mathematics", callback_data='math')],
            [InlineKeyboardButton("⚡ Physics", callback_data='physics')],
            [InlineKeyboardButton("💻 Programming", callback_data='programming_language')],
            [InlineKeyboardButton("📝 Quiz / MCQ", callback_data='quiz')],
            [InlineKeyboardButton("📚 English Grammar", callback_data='english')],
            [InlineKeyboardButton("🇲🇲 Myanmar Literature", callback_data='burmese')],
            [InlineKeyboardButton("📇 Flashcard", callback_data='flashcard')],
            [InlineKeyboardButton("🌐 General Study", callback_data='general')],
            [InlineKeyboardButton("🔙 Back to Main", callback_data='back_to_main')]
        ]
        await query.edit_message_text(text="📚 **Study Modes** များ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    # 2. Entertainment Modes မီနူးသို့ သွားရန်
    elif data == 'menu_entertainment':
        keyboard = [
            [InlineKeyboardButton("🎵 Music Finder (သီချင်းရှာရန်)", callback_data='ent_music')],
            [InlineKeyboardButton("🎬 Movie Search (ဇာတ်ကားရှာရန်)", callback_data='ent_movie')],
            [InlineKeyboardButton("🔄 Scan Movies (Movies များစစ်ရန်)", callback_data='ent_scan')],
            [InlineKeyboardButton("🔙 Back to Main", callback_data='back_to_main')]
        ]
        await query.edit_message_text(text="🎵 **Entertainment Modes** များ:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return
        
    elif data == 'ent_music':
        USER_MODES[chat_id] = 'ent_music'
        await query.edit_message_text(
            text="🎵 **Music Finder Mode**\n\nယခု Music Mode ထဲသို့ ရောက်ရှိနေပါပြီ။ ရှာလိုသော သီချင်းနာမည်ကို **စာသားဖြင့် တိုက်ရိုက်ရိုက်ပို့ပေးပါ** (ဥပမာ - `Faded` ဟု ရိုက်ပို့ပါ)"
        )
        return
        
    elif data == 'ent_movie':
        await query.edit_message_text(
            text="🎬 **Movie Search Mode**\n\nဇာတ်ကားရှာလိုပါက ကျေးဇူးပြု၍ အောက်ပါပုံစံအတိုင်း ရိုက်ထည့်ပါ:\n`/search [ဇာတ်ကားနာမည်]`\n\n(ဥပမာ - `/search avatar`)"
        )
    elif data == 'ent_scan':
        userbot_target = 8081029424  # သင့် userbot ရဲ့ ID
        await context.bot.send_message(
            chat_id=userbot_target,
            text="SCAN_CHANNELS_AUTO"
        )
        await query.edit_message_text(
            text="🔄 Movie Auto-Scan ဖတ်ရန် Assistant AI သို့ အမိန့်ပေးလိုက်ပါပြီ။ ခေတ္တစောင့်ဆိုင်းပေးပါခင်ဗျာ..."
        )
        return     
    # 3. ပုံမှန် Main Menu သို့ ပြန်သွားရန်
    elif data == 'back_to_main':
        keyboard = [
            [InlineKeyboardButton("📚 Study Modes", callback_data='menu_study')],
            [InlineKeyboardButton("🎵 Entertainment Modes", callback_data='menu_entertainment')]
        ]
        await query.edit_message_text(text="📌 ကျေးဇူးပြု၍ Mode အမျိုးအစားကို ရွေးချယ်ပါ :", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # 4. ရွေးချယ်လိုက်သော Mode ကို သိမ်းဆည်းရန်
    USER_MODES[chat_id] = data
    await query.edit_message_text(text=f"👉 Mode Updated: {data.upper()}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # update.message သို့မဟုတ် photo မပါလာပါက Error မတက်စေရန် ကြိုတင်စစ်ဆေးခြင်း
    if not update.message or not update.message.photo:
        return

    chat_id = update.effective_chat.id
    chosen_model = USER_SELECTED_MODELS.get(chat_id, DEFAULT_MODEL)
    
    photo = update.message.photo[-1]
    caption = update.message.caption  # ပုံနဲ့အတူ ပါလာတဲ့ စာသား 
    
    caption_lower = caption.lower() if caption else ""

    # wants_edit ကို စစ်ဆေးခြင်း
    wants_edit = any(kw in caption_lower for kw in ['ပြင်ပေး', 'ဖျောက်ပေး', 'တံဆိပ်တပ်', 'အောင်လုပ်ပေး', 'ပြောင်းပေး', 'edit', 'change', 'remove', 'add'])
    
    is_pdf_info_question = any(q in caption_lower for q in ['ဆိုတာ', 'ဘယ်လို', 'ဘာလဲ'])

    # PDF မေးခွန်း သီးသန့် ဖြစ်ပါက PDF မထုတ်ဘဲ Gemini ဖြင့် စာသားအဖြေသာ ပြန်ခိုင်းမည်
    if is_pdf_info_question:
        wants_pdf = False
    else:
        wants_pdf = any(kw in caption_lower for kw in ['pdf', 'generate pdf', 'make pdf', 'create pdf', 'pdfထုတ်', 'pdf ထုတ်', 'pdfလုပ်', 'pdf လုပ်', 'pdfပြောင်း'])
        
    photo_file = await context.bot.get_file(photo.file_id)
    image_bytes = await photo_file.download_as_bytearray()
    

    if caption and wants_edit:
        await context.bot.send_chat_action(chat_id=chat_id, action="upload_photo")
        await update.message.reply_text("🎨 ပုံကို ပြင်ဆင်ပြီး ပုံအသစ် ဖန်တီးပေးနေပါတယ်... ခေတ္တစောင့်ပေးပါခင်ဗျာ...")
    
        try:
            # Step 1: Gemini ဖြင့် မြန်မာ Instruction ကို InstructPix2Pix နိုင်သော English Command ပြောင်းခြင်း
            client = get_next_client()
            translator_prompt = (
                f"Translate this image edit instruction into a concise English command for InstructPix2Pix: '{caption}'. "
                "Examples: 'make the lighter green', 'add a logo to the lighter'. Output ONLY the English command."
            )
            
            prompt_response = await asyncio.to_thread(
                client.models.generate_content,
                model=chosen_model,
                contents=[translator_prompt]
            )
            english_instruction = prompt_response.text.strip()

            # Step 2: Hugging Face Inference API သို့ မူလပုံနှင့် Instruction ပို့ခြင်း
            headers = {"Authorization": f"Bearer {HF_TOKEN}"}
            files = {"image": ("input.jpg", bytes(image_bytes), "image/jpeg")}
            data = {"prompt": english_instruction}

            def call_hf_api():
                return requests.post(HF_API_URL, headers=headers, data=data, files=files, timeout=90)

            response = await asyncio.to_thread(call_hf_api)

            # Step 3: API တုံ့ပြန်မှုကို စစ်ဆေး၍ Bot ဖြင့် ပုံပြန်ပို့ခြင်း
            if response.status_code == 200:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=BytesIO(response.content),
                    caption=f"✨ ပြင်ဆင်ပြီးသွားသော ပုံဖြစ်ပါတယ်ခင်ဗျာ!\n(Instruction: {english_instruction})"
                )
            elif response.status_code == 503:
                await update.message.reply_text("⏳ Model စတင်နေဆဲဖြစ်ပါသည်၊ စက္ကန့် ၃၀ အကြာတွင် ထပ်မံစမ်းသပ်ပေးပါ။")
            else:
                await update.message.reply_text(f"❌ HF API Error: {response.status_code} - {response.text}")

        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")
        return
    
    # အကယ်၍ ပုံနဲ့အတူ မေးချင်တဲ့ စာသား (Caption) ပါ ပါလာရင်
    if caption and not wants_pdf:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        try:
            mode = USER_MODES.get(chat_id, 'general')
            chosen_model = USER_SELECTED_MODELS.get(chat_id, DEFAULT_MODEL)
            current_cfg = SUBJECT_CONFIGS.get(mode, SUBJECT_CONFIGS['general'])

            image_part = types.Part.from_bytes(data=bytes(image_bytes), mime_type="image/jpeg")

            # ၁။ Configuration ထဲတွင် Google Search Tool ကို ထည့်သွင်းခြင်း
            chat_config = types.GenerateContentConfig(
                temperature=current_cfg['temperature'],
                system_instruction="You are ACE. Answer the user's question clearly.",
                tools=[{"google_search": {}}]  
            )

            chat_session = get_or_create_chat_session(chat_id, chosen_model, chat_config)

            response = await asyncio.to_thread(
                chat_session.send_message,
                [image_part, caption]
            )
            reply_text = response.text or "တောင်းပန်ပါတယ်၊ အဖြေထုတ်လို့ မရပါဘူး။"
            
            # HTML tags တွေ ရှင်းထုတ်ရန်
            clean_text = reply_text.replace("<p>", "").replace("</p>", "\n")
            clean_text = clean_text.replace("<ul>", "").replace("</ul>", "\n")
            clean_text = clean_text.replace("<li>", "• ").replace("</li>", "\n")
            clean_text = clean_text.replace("<strong>", "").replace("</strong>", "")
            clean_text = clean_text.replace("<pre><code>", "```\n").replace("</code></pre>", "\n```")
            clean_text = clean_text.replace("&lt;", "<").replace("&gt;", ">")
            clean_text = clean_text.replace("<html>", "").replace("</html>", "")
            clean_text = clean_text.replace("<body>", "").replace("</body>", "")

            await update.message.reply_text(clean_text)
            
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")
        return

    # Caption မပါဘဲ ပုံသီးသန့်ဆိုရင်တော့ ပုံမှန်အတိုင်း PDF ထုတ်ဖို့ Buffer ထဲ သိမ်းမယ်
    if chat_id not in USER_BUFFERS:
        USER_BUFFERS[chat_id] = []

    USER_BUFFERS[chat_id].append(bytes(image_bytes))

    if chat_id in USER_JOBS:
        return

    USER_JOBS[chat_id] = asyncio.create_task(process_batch(chat_id, context))
async def handle_quiz_generation(chat_id: int, context: ContextTypes.DEFAULT_TYPE, ai_response_text: str):
    try:
        clean_json = ai_response_text.strip()
        if clean_json.startswith("```json"):
            clean_json = clean_json[7:]
        if clean_json.startswith("```"):
            clean_json = clean_json[3:]
        if clean_json.endswith("```"):
            clean_json = clean_json[:-3]
            
        quiz_data = json.loads(clean_json.strip())
        questions = quiz_data.get("questions", [])
        
        await context.bot.send_message(chat_id=chat_id, text=f"🎯 **Quiz စတင်ပါပြီ!** (စုစုပေါင်း မေးခွန်း {len(questions)} ပုဒ်)")
        
        for q in questions:
            q_num = q.get("questionNumber")
            q_text = q.get("question")
            options = q.get("answerOptions", [])
            hint = q.get("hint", "")
            
            options_text = ""
            for i, opt in enumerate(options):
                opt_letter = chr(65 + i) # A, B, C, D
                options_text += f"   <b>{opt_letter}.</b> {opt['text']}\n"
                
            msg = f"<b>Q{q_num}: {q_text}</b>\n\n{options_text}"
            if hint:
                msg += f"\n💡 <i>Hint: {hint}</i>"
                
            await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
            
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ Quiz ဖော်ပြရာတွင် အမှားရှိနေပါသည် - {str(e)}\n\nRaw:\n{ai_response_text}")
async def process_and_send_song(chat_id, query, context, status_msg=None):
    try:
        # Userbot ဆီသို့ သီချင်းရှာခိုင်းရန် ပို့မည်
        userbot_target = 8081029424  # ကိုယ့် userbot username
        await context.bot.send_message(chat_id=userbot_target, text=f"GET_SONG:{query}:{chat_id}")
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ သီချင်းတောင်းဆိုရာတွင် အမှားအယွင်းရှိသွားပါတယ်။: {str(e)}")
# --- NEW: Text Message Handler (စာသားဖြင့် မေးလာလျှင် ပြန်ဖြေရန်) ---
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    
    if user_text.startswith('/'):
        return
    mode = USER_MODES.get(chat_id, 'general')

    if mode == 'ent_music':
        status_msg = await update.message.reply_text("🎧 သီချင်းကို ရှာနေပါပြီ... ခေတ္တစောင့်ပေးပါခင်ဗျာ...တောင်းဆိုမှုကို Assistant AI အား လွှဲပြောင်းပေးလိုက်ပါပြီ..")
        await process_and_send_song(chat_id, user_text, context, status_msg)
        return

    chosen_model = USER_SELECTED_MODELS.get(chat_id, DEFAULT_MODEL)

    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    try:
        # Text Chat အတွက် သီးသန့် ရှင်းလင်းသော System Prompt သတ်မှတ်ပေးခြင်း
        text_system_instruction = (
            f"Today's current date is {current_date_str} and the current time is {current_time_str}. "
            "You are ACE, a genius, highly intelligent, responsible, polite, and deeply hospitable AI academic assistant "
            "developed by @mg_zawe_wint. "
            "Always treat the user with warmth, absolute respect, and a genuine eagerness to help. "
            "If the user greets you for the first time or says 'Hi', 'Hello', 'မင်္ဂလာပါ', warmly welcome them and introduce yourself as ACE. "
            "CRITICAL LANGUAGE RULE: Always reply in the exact same language that the user uses (Burmese or English). "
            "POLITENESS & GENDER RULES: Default to using Burmese male polite particles ('ခင်ဗျာ' or 'ဗျာ') strictly unless requested otherwise. Never mix particles. "
            "in exception, You may switch to 'ရှင်' ONLY if the context or user request explicitly asks for a female perspective or roleplay"
            "Answer based on the user's preferred language and English.\n\n"
            "In English Greeting Responses, do not use 'ခင်ဗျာ/ဗျာ' and 'ရှင်'. "        
            "Always be reliable, anticipate their academic needs, and naturally refer to yourself as ACE when appropriate."
            "FORMATTING RULE: Output strictly in clean Markdown format. DO NOT output HTML tags like <div>, <p>, <html>, or <body>."
        )
    
        chat_config = types.GenerateContentConfig(
            temperature=0.3,
            system_instruction=text_system_instruction,
        )
        
        chat_session = get_or_create_chat_session(chat_id, chosen_model, chat_config)

        response = await asyncio.to_thread(
            chat_session.send_message,
            user_text,
        )         
        reply_text = response.text or "တောင်းပန်ပါတယ်၊ အဖြေထုတ်လို့ မရပါဘူး။"
        
        # HTML tag များ ရှုပ်ထွေးစွာ Replace လုပ်ထားသည့် အပိုင်းများကို ဖြုတ်ပြီး Markdown တိုက်ရိုက် ပို့ပေးပါသည်

        await update.message.reply_text(reply_text)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def process_batch(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        await asyncio.sleep(18.0)

        
        photos = USER_BUFFERS.pop(chat_id, [])
        if not photos:
            return

        mode = USER_MODES.get(chat_id, 'general')
        await context.bot.send_message(chat_id=chat_id, text=f"📌 ဓာတ်ပုံ ({len(photos)}) ပုံ လက်ခံရရှိပြီ! Analysis လုပ်နေပါပြီ...\ncompleted✅")

        if mode == 'quiz':
            await context.bot.send_message(chat_id=chat_id, text="🎯 ဉာဏ်စမ်းမေးခွန်းများ (MCQ Quiz) ဖန်တီးနေပါပြီ...\nခေတ္တစောင့်ပေးပါခင်ဗျာ။")
        else:           
            await context.bot.send_message(chat_id=chat_id, text=f"💬 Concepts and Solutions PDF Format တည်ဆောက်နေပါပြီ... \ncompleted✅")
            await context.bot.send_message(chat_id=chat_id, text=f"""Refining the Document🧻... 
	   အဆင်သင့်ဖြစ်တာနဲ့ ချက်ချင်းထုတ်ပေးပါမယ်ခင်ဗျာ။""", write_timeout=600.0)

        # Write Timeout မဖြစ်အောင် ပုံများကို Compress ပြုလုပ်ခြင်း
        # ပုံများကို သီးခြား Thread ဖြင့် Compress လုပ်ရန် Function ခွဲထုတ်ခြင်း
        def process_image_sync(img_bytes):
            img = Image.open(io.BytesIO(img_bytes))
            img = ImageOps.exif_transpose(img)  # ပုံ စောင်းနေပါက မူလအတိုင်း တည့်ပေးသည်
            img.thumbnail((800, 800))
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=70)
            return buffer.getvalue()

        vision_parts = []
        for img_bytes in photos:
            # ဓာတ်ပုံတစ်ပုံချင်းစီကို Non-blocking ဖြင့် ပြုပြင်ခြင်း
            processed_bytes = await asyncio.to_thread(process_image_sync, img_bytes)
            vision_parts.append(
                types.Part.from_bytes(data=processed_bytes, mime_type='image/jpeg')
            )
        selected_prompt = PROMPTS.get(mode, PROMPTS['general'])
        prompt_parts = vision_parts + [f"\n\nInstruction:\n{selected_prompt}"]

        # Background Task (Auto-Retry စနစ်ဖြင့်)
        async def generate_and_send():
            max_retries = 3
            response = None
            
            current_cfg = SUBJECT_CONFIGS.get(mode, SUBJECT_CONFIGS['general'])

           
            chat_config = types.GenerateContentConfig(
                temperature=current_cfg['temperature'],
                system_instruction=current_cfg['system_instruction']
            )
            
            for attempt in range(max_retries):
                try:
                    chosen_model = USER_SELECTED_MODELS.get(chat_id, DEFAULT_MODEL)
                    

                    chat_session = get_or_create_chat_session(chat_id, chosen_model, chat_config)
                    
                    response = await asyncio.to_thread(
                        chat_session.send_message,
                        prompt_parts
                    )

                    break

                except (httpx.RemoteProtocolError, httpx.TimeoutException, httpx.NetworkError) as net_err:
                    if attempt < max_retries - 1:
                        print(f"⚠️ Connection ပြတ်သွားလို့ ထပ် ကြိုး စား နေ ပါ ပြီ (ကြိုးစားမှု - {attempt + 1}/{max_retries})...")
                        try:
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text=f"Internet connection မကောင်းလို့ reconnect ပြန်လုပ်ပေးနေပါတယ် ({attempt + 1}/3)။ ခေတ္တစောင့်ပေးပါခင်ဗျာ..."
                           )
                        except:
                            pass
                        await asyncio.sleep(4) # ၄ စက္ကန့်စောင့်ပြီးမှ ပြန်ချိတ်မည်
                        continue
                    else:
                        raise net_err # ၃ ခါလုံး မရတော့မှ Error ပစ်မည်
                except ClientError as ce:  
                    if "429" in str(ce) or "RESOURCE_EXHAUSTED" in str(ce):
                        print("⚠️ Google API Quota (Rate Limit) ပြည့်သွားပါပြီ။")
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text="စိတ်မကောင်းပါဘူး🥺..⚠️ Google API ရဲ့ Free Tier Quota Limit ခဏပြည့်သွားပါပြီ ။ မိနစ်အနည်းငယ်လောက် စောင့်ပြီးမှ ထပ်ပို့ပေးပါနော်။💪"
                        )
                        return
                    else:
                        raise ce

            try:
                raw_text = response.text or ""
                if mode == 'quiz':
                    await handle_quiz_generation(chat_id, context, raw_text)
                    return

                html_content = raw_text.replace("```html", "").replace("```", "").strip()

                pdf_bytes = await asyncio.to_thread(
                    lambda: HTML(string=html_content).write_pdf()
                )

                pdf_stream = io.BytesIO(pdf_bytes)
                pdf_stream.name = f"Study_Guide_{mode}.pdf"

                await context.bot.send_document(
                    chat_id=chat_id,
                    document=pdf_stream,
                    filename=f"Study_Guide_{mode}.pdf",
                    caption=f"""📑Your High-quality Study PDF Is Ready! PDF file လေးရပြီပါပီခင်ဗျာ🫶!
                    ACE🔥 is Here for you! """
                )

            except Exception as e:
                print("\n================ ERROR TRACEBACK ================")
                traceback.print_exc()
                print("=================================================\n")
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Error: {str(e)}Sever does not respond!, please send me again 5 mins later😭🙏. ",
                    write_timeout=400.0
                )

        asyncio.create_task(generate_and_send())

    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Error: {str(e)}")
    finally:
        USER_BUFFERS.pop(chat_id, None)
        USER_JOBS.pop(chat_id, None)

# Memory ရှင်းပေးမည့် Function
async def clear_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    USER_CHATS.pop(chat_id, None)
    USER_CLIENTS.pop(chat_id, None)
    USER_LAST_ACTIVE.pop(chat_id, None)
    
    await update.message.reply_text("🧹 Memory clear process completed. Texts,Photos and History are deleted from ACE's memory.")

async def song_command(update, context):
    chat_id = update.effective_chat.id  # တောင်းတဲ့သူရဲ့ chat_id ကို ယူမည်
    
    if not context.args:
        await update.message.reply_text("ကျေးဇူးပြု၍ ရှာလိုသည့် သီချင်းနာမည်ကို ထည့်ပါ။ ဥပမာ: /song ဆောင်းနိမ်း ခ အောမီး")
        return
        
    query = " ".join(context.args)
    await update.message.reply_text(f"⏳ '{query}' ကို ရှာဖွေနေပါပြီ ခဏစောင့်ပါ။  တောင်းဆိုမှုကို Assistant AI အား လွှဲပြောင်းပေးလိုက်ပါပြီ...")

    # ဒီနေရာမှာ Userbot ရဲ့ ID (သို့မဟုတ် target) ကို အမှန်အတိုင်း ထည့်ထားပါ
    userbot_target = 8081029424  # (သင့် Userbot ရဲ့ ID ဂဏန်း)
    await context.bot.send_message(
        chat_id=userbot_target, 
        text=f"GET_SONG:{query}:{chat_id}"
    )
async def handle_userbot_media(update, context):
    try:
        sender = update.effective_user
        if sender and sender.id == 8081029424: # သင့် Userbot ID
            message_text = update.message.caption or update.message.text or ""
            
            if "MOVIE_ID:" in message_text:
                parts = message_text.split(":")
                msg_id = int(parts[1])
                target_chat_id = int(parts[3])
                
                try:
                    await context.bot.copy_message(
                        chat_id=target_chat_id,
                        from_chat_id=ARCHIVE_CHANNEL_ID,
                        message_id=msg_id
                    )
                except Exception as e:
                    print(f"Copy message error: {e}")
                    
            elif "CHAT_ID:" in message_text:
                try:
                    parts = message_text.split("CHAT_ID:")
                    target_chat_id = int(parts[1].strip().split()[0])
                    clean_caption = parts[0].strip() or "🎵 ACE မှ တင်ဆက်ပေးလိုက်ပါတယ်!"
                except Exception as parse_err:
                    print(f"Chat ID parse error: {parse_err}")
                    return
                
                if update.message.audio or update.message.document or update.message.video:
                    audio_file = update.message.audio or update.message.document or update.message.video
                    await context.bot.send_audio(
                        chat_id=target_chat_id,
                        audio=audio_file.file_id,
                        caption=clean_caption
                    )
                elif update.message.text:
                    await context.bot.send_message(chat_id=target_chat_id, text=clean_caption)

    except Exception as e:
        print(f"Error in handle_userbot_media: {e}")

async def unknown_command(update, context):
    await update.message.reply_text(
        "သီချင်းရှာလိုလျှင်\n/song သီချင်းအမည် ... ဥပမာ( '/song ဆောင်းနိမ်း ခ အောမီး' ) ဟု ပို့ပေးပါခင်ဗျာ။"
    )

if __name__ == '__main__':
    request_config = HTTPXRequest(
        connection_pool_size=50,
        connect_timeout=100.0,
        read_timeout=600.0,
        write_timeout=600.0,
        pool_timeout=600.0
    )

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .request(request_config)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("mode", set_mode))
    app.add_handler(CommandHandler("models", models_command))
    app.add_handler(CommandHandler("about", about_ace))
    app.add_handler(CommandHandler("run", run_command))
    app.add_handler(CommandHandler("clear", clear_memory))
    app.add_handler(CommandHandler("search", movie_search_command))
    app.add_handler(CommandHandler("song", song_command))

    app.add_handler(CallbackQueryHandler(handle_model_selection, pattern="^(cat_|set_|back_to_main)"))
    app.add_handler(CallbackQueryHandler(button_callback))

    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler((filters.AUDIO | filters.Document.ALL | filters.VIDEO), handle_userbot_media))  
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    print("ACE is successfully running and polling...")
    app.run_polling(drop_pending_updates=True)

