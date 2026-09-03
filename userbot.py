import os
import asyncio
import re
import unicodedata
import base64
from groq import AsyncGroq
from google import genai
from google.genai import types
from telethon import events, TelegramClient
from telethon.sessions import StringSession
from dotenv import load_dotenv

load_dotenv()

api_id = int(os.getenv("USERBOT_API_ID"))
api_hash = os.getenv("USERBOT_API_HASH")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY_3")

ACE_BOT_ID = 8255035281
ACE_BOT = '@ace_study_ass_bot'    
TARGET_SONGBOT = '@somgsforme_bot'
ARCHIVE_CHANNEL_ID = -1003943796781 

url_pattern = re.compile(r'https?://[^\s]+')

# Gemini Client စတင်ခြင်း
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# SESSION_STRING စစ်ဆေးပြီး ချိတ်ဆက်ခြင်း
session_string = os.getenv("SESSION_STRING")
if session_string:
    client = TelegramClient(StringSession(session_string), api_id, api_hash)
else:
    client = TelegramClient('my_userbot', api_id, api_hash)

# --- မြန်မာစာ normalization နှင့် Sanitization Helper Functions ---
def normalize_myanmar_text(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize('NFC', text)
    text = re.sub(r'[\u200b\u200c\u200d\uFEFF]', '', text)
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()

def sanitize_keyword(text: str) -> str:
    if not text:
        return ""
    text = normalize_myanmar_text(text).lower()
    clean_text = re.sub(r'[\s\-_:=+.,!@#$%^&*()\[\]{}<>\/\\\'"]+', '', text)
    return clean_text



# Groq API Keys များကို Env မှ ယူခြင်း
GROQ_KEYS = [
    os.getenv("GROQ_API_KEY_1"),
    os.getenv("GROQ_API_KEY_2"),
]
GROQ_KEYS = [k for k in GROQ_KEYS if k]

# Async Client များ ဖန်တီးခြင်း
groq_clients = [AsyncGroq(api_key=key) for key in GROQ_KEYS]
current_groq_index = 0

async def get_movie_title_from_poster(photo_bytes):
    global current_groq_index
    if not groq_clients or not photo_bytes:
        return None

    # Groq Vision အတွက် Image Bytes ကို Base64 သို့ ပြောင်းခြင်း
    base64_image = base64.b64encode(photo_bytes).decode('utf-8')
    data_url = f"data:image/jpeg;base64,{base64_image}"

    prompt = (
        "Analyze this movie poster image carefully.\n"
        "1. Read the exact text written on the poster (OCR).\n"
        "2. Identify the official standard English movie title and release year.\n"
        "Output ONLY the title and year in this exact format: 'Movie Title (YYYY)'.\n"
        "If it is not a movie poster or text is unreadable, reply with 'UNKNOWN'."
    )

    total_clients = len(groq_clients)

    for attempt in range(total_clients):
        client = groq_clients[current_groq_index]
        try:
            # Groq Llama-3.2 Vision Model ကို အသုံးပြု၍ ခေါ်ယူခြင်း
            chat_completion = await client.chat.completions.create(
                model="llama-3.2-11b-vision-preview",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": data_url}
                            }
                        ]
                    }
                ],
                temperature=0.0, # Strict Accuracy ရရှိရန် 0.0 ထားရှိခြင်း
                max_tokens=100
            )

            detected_title = chat_completion.choices[0].message.content.strip()
            
            # Next Key Rotation
            current_groq_index = (current_groq_index + 1) % total_clients
            return detected_title if "UNKNOWN" not in detected_title else None

        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "rate_limit" in error_str:
                print(f"⚠️ Groq Key Index {current_groq_index} Rate limit မိသွားပါသည်။ နောက် Key သို့ ပြောင်းနေသည်...")
                current_groq_index = (current_groq_index + 1) % total_clients
                await asyncio.sleep(1)
            else:
                print(f"Groq Vision Error: {e}")
                return None

    return None

# --- (၁) ဇာတ်ကား အားလုံးကို Scan ဖတ်ပြီး Archive Channel သို့ ပို့ရန် ---
async def scan_and_forward(event=None):
    if event: await event.reply("🔄 Userbot မှ ဇာတ်ကားများနှင့် Poster များကို စတင် Scan ဖတ်နေပါပြီ...")
    else: print("🕒 Manual Scan စတင်နေပါပြီ...")
    
    added_count = 0
    scanned_channels = 0
    
    try:
        # [MODIFIED] Archive ထဲရှိ Title များကို sanitize လုပ်၍ သိမ်းဆည်းခြင်း
        existing_sanitized_titles = set()
        async for arch_msg in client.iter_messages(ARCHIVE_CHANNEL_ID):
            arch_title = arch_msg.text or getattr(arch_msg, 'caption', None) or ""
            if arch_title:
                clean_arch = sanitize_keyword(arch_title)
                if clean_arch:
                    existing_sanitized_titles.add(clean_arch)
                
        async for dialog in client.iter_dialogs():
            if dialog.is_channel or dialog.is_group:
                if dialog.id == ARCHIVE_CHANNEL_ID: continue 
                
                scanned_channels += 1
                try:
                    async for message in client.iter_messages(dialog.entity, limit=700):
                        if getattr(message, 'action', None): continue
                        
                        clean_title = None
                        should_save = False
                        is_photo_with_poster = False

                        raw_msg_text = message.text or getattr(message, 'caption', None) or ""
                        # [MODIFIED] Text/Caption ကို normalize ပြုလုပ်ခြင်း
                        normalized_msg_text = normalize_myanmar_text(raw_msg_text)

                        # (၁) ဗီဒီယို သို့မဟုတ် Document ဆိုရင် တန်းသိမ်းမည်
                        if message.video or message.document:
                            should_save = True
                            raw_title = normalized_msg_text or getattr(message.video or message.document, 'file_name', None) or f"media_{message.id}"
                            clean_title = raw_title.split("\n")[0].strip()

                        # (၂) ပုံ (Photo) ဆိုရင် Caption ထဲမှာ လင့်ခ် ပါမှ သိမ်းမည်
                        elif message.photo:
                            if normalized_msg_text and url_pattern.search(normalized_msg_text):
                                photo_bytes = await client.download_media(message.photo, file=bytes)
                                verified_title = await get_movie_title_from_poster(photo_bytes)
                                
                                if verified_title:
                                    clean_title = verified_title
                                    is_photo_with_poster = True
                                else:
                                    clean_title = normalized_msg_text.split("\n")[0].strip()
                                
                                should_save = True
                                print("⏳ Gemini API တွင် ဝန်မပိစေရန် ၁ မိနစ် စောင့်ဆိုင်းနေပါသည်...")
                                await asyncio.sleep(60)

                        # (၃) စာသားသီးသန့် (Text) ဆိုရင် လင့်ခ် ပါမှ သိမ်းမည်
                        elif normalized_msg_text and url_pattern.search(normalized_msg_text):
                            should_save = True
                            clean_title = normalized_msg_text.split("\n")[0].strip()

                        # သိမ်းဖို့ သတ်မှတ်ချက်နဲ့ ကိုက်ညီရင် သိမ်းမည်
                        if should_save and clean_title:
                            sanitized_check = sanitize_keyword(clean_title)
                            if sanitized_check not in existing_sanitized_titles:
                                if is_photo_with_poster:
                                    new_caption = f"{normalized_msg_text}\n\n🎬 **Detected Title:** {clean_title}"
                                    await client.send_file(ARCHIVE_CHANNEL_ID, message.photo, caption=new_caption)
                                else:
                                    # [MODIFIED] Text/Caption ပြင်ဆင်ပြီးမှ Send / Forward လုပ်မည်
                                    if message.photo or message.video or message.document:
                                        await client.send_file(ARCHIVE_CHANNEL_ID, message.media, caption=normalized_msg_text)
                                    else:
                                        await client.send_message(ARCHIVE_CHANNEL_ID, normalized_msg_text)
                                    
                                existing_sanitized_titles.add(sanitized_check)
                                added_count += 1
                                await asyncio.sleep(0.5)
                                
                    await asyncio.sleep(2)
                except Exception as e:
                    print(f"Error scanning dialog: {e}")
                    continue
                    
        msg = f"✅ **Scan ပြီးဆုံးပါပြီ!**\n📂 ချန်နယ်: {scanned_channels} ခု\n✨ အသစ်သိမ်းဆည်းနိုင်ခဲ့သော ဇာတ်ကား/Poster အရေအတွက်: {added_count} ခု"
        if event: await event.reply(msg)
        else: print(msg)

    except Exception as e:
        error_msg = f"❌ Scan ဖတ်ရာတွင် အမှား: {str(e)}"
        print(error_msg)
        if event: await event.reply(error_msg)


@client.on(events.NewMessage(from_users=ACE_BOT, pattern="SCAN_CHANNELS_AUTO"))
async def handle_auto_scan(event):
    await scan_and_forward(event)

# --- (၂) [MODIFIED] Main Bot မှ ရှာခိုင်းသည့်အခါ Message ID ပို့ပေးမည့် Robust Search Handler ---
@client.on(events.NewMessage(from_users=ACE_BOT, pattern=r'SEARCH_MOVIE:(.+):(\d+)'))
async def handle_movie_search(event):
    raw_query = event.pattern_match.group(1)
    target_chat_id = event.pattern_match.group(2)
    
    clean_query = sanitize_keyword(raw_query)
    
    try:
        found_count = 0
        found_message_ids = set()
        
        # Space ပါသည်ဖြစ်စေ၊ မပါသည်ဖြစ်စေ Variant အဖြစ် တွဲဖက်ရှာဖွေခြင်း
        query_variants = [raw_query, raw_query.replace(" ", "")]
        
        for q in query_variants:
            if not q.strip(): 
                continue
            
            async for msg in client.iter_messages(ARCHIVE_CHANNEL_ID, search=q, limit=20):
                if msg.id in found_message_ids:
                    continue
                
                msg_content = msg.text or getattr(msg, 'caption', None) or ""
                clean_msg_content = sanitize_keyword(msg_content)
                
                # Space/Punctuation မပါဘဲ Substring Matching Exact စစ်ဆေးခြင်း
                if clean_query in clean_msg_content:
                    found_message_ids.add(msg.id)
                    found_count += 1
                    
                    await client.send_message(
                        ACE_BOT, 
                        f"MOVIE_ID:{msg.id}:CHAT_ID:{target_chat_id}"
                    )
                    await asyncio.sleep(0.5)
                    
                    if found_count >= 5:
                        break
            
        if found_count == 0:
            await client.send_message(
                ACE_BOT, 
                f"❌ '{raw_query}' နှင့် ပတ်သက်သော ဇာတ်ကား/Poster မတွေ့ရှိပါ။\n\nCHAT_ID:{target_chat_id}"
            )
            
    except Exception as e:
        print(f"Movie search error: {e}")

# --- (၃) သီချင်းရှာဖွေရန် Songbot Proxy Logic ---
active_song_requests = {}
song_request_lock = asyncio.Lock()

@client.on(events.NewMessage(from_users=ACE_BOT, pattern=r'GET_SONG:(.+):(\d+)'))
async def handle_song_request(event):
    song_name = event.pattern_match.group(1)
    target_chat_id = int(event.pattern_match.group(2))
    
    async with song_request_lock:
        try:
            async with client.conversation(TARGET_SONGBOT) as conv:
                await conv.send_message('/start')
                await asyncio.sleep(1)
                
                await conv.send_message(song_name)
                response = await conv.get_response()
                
                if response.buttons:
                    flat_buttons = [btn for row in response.buttons for btn in row][:10]
                    for button in flat_buttons:
                        active_song_requests[conv.chat_id] = target_chat_id
                        await button.click()
                        await asyncio.sleep(2)
                        
        except Exception as e:
            print(f"Song fetch error: {e}")

@client.on(events.NewMessage(from_users=TARGET_SONGBOT))
async def capture_songs(event):
    if event.media and active_song_requests:
        chat_id = event.chat_id
        target_chat_id = active_song_requests.get(chat_id)
        
        if target_chat_id:
            caption_text = f"🎵 CHAT_ID:{target_chat_id}"
            await client.send_file(ACE_BOT, event.media, caption=caption_text)
            active_song_requests.pop(chat_id, None)

# --- (၄) ပရိုဂရမ် စတင်ခြင်း ---
if __name__ == '__main__':
    print("⚡ Userbot စတင် အလုပ်လုပ်နေပြီ...")
    client.start()
    client.run_until_disconnected()
