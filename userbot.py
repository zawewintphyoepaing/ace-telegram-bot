import os
import asyncio
import re
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

active_song_requests = []

# --- Poster ပုံမှ Movie Title ကို Gemini Vision ဖြင့် ဖတ်ယူ စစ်ဆေးမည့် Function ---
async def get_movie_title_from_poster(photo_bytes):
    try:
        prompt = (
            "Analyze this movie poster image carefully.\n"
            "1. Read the exact text written on the poster (OCR).\n"
            "2. Identify the official standard English movie title and release year.\n"
            "3. Search and double check standard movie database naming if needed.\n"
            "Output ONLY the title and year in this exact format: 'Movie Title (YYYY)'.\n"
            "If it is not a movie poster or text is unreadable, reply with 'UNKNOWN'."
        )
        
        # Telethon Event Loop မပိတ်ဆို့စေရန် Thread Executor ဖြင့် Run ခြင်း
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: gemini_client.models.generate_content(
                model='gemini-2.0-flash',
                contents=[
                    types.Part.from_bytes(data=photo_bytes, mime_type='image/jpeg'),
                    prompt
                ]
            )
        )
        detected_title = response.text.strip()
        return detected_title if "UNKNOWN" not in detected_title else None
    except Exception as e:
        print(f"Gemini Vision Error: {e}")
        return None

# --- (၁) ဇာတ်ကား အားလုံး (Video, Document, Photo Poster, Link) များကို Scan ဖတ်ပြီး Private Channel သို့ ပို့ရန် ---
async def scan_and_forward(event=None):
    if event: await event.reply("🔄 Userbot မှ ဇာတ်ကားများနှင့် Poster များကို စတင် Scan ဖတ်နေပါပြီ...")
    else: print("🕒 နေ့စဉ်အလိုအလျောက် Auto-Scan စတင်နေပါပြီ...")
    
    added_count = 0
    scanned_channels = 0
    
    try:
        existing_titles = set()
        async for arch_msg in client.iter_messages(ARCHIVE_CHANNEL_ID):
            arch_title = arch_msg.caption or arch_msg.text or ""
            if arch_title:
                for line in arch_title.split('\n'):
                    clean_l = line.strip().lower()
                    if clean_l:
                        existing_titles.add(clean_l)
                
        async for dialog in client.iter_dialogs():
            if dialog.is_channel or dialog.is_group:
                if dialog.id == ARCHIVE_CHANNEL_ID: continue 
                
                scanned_channels += 1
                try:
                    async for message in client.iter_messages(dialog.entity, limit=500):
                        if getattr(message, 'action', None): continue
                        
                        clean_title = None
                        should_save = False
                        is_photo_with_poster = False

                        # (၁) ဗီဒီယို သို့မဟုတ် Document ဆိုရင် တန်းသိမ်းမည်
                        if message.video or message.document:
                            should_save = True
                            raw_title = message.caption or getattr(message.video or message.document, 'file_name', None) or f"media_{message.id}"
                            clean_title = raw_title.split("\n")[0].strip()

                        # (၂) ပုံ (Photo) ဆိုရင် Caption ထဲမှာ လင့်ခ် ပါမှ သိမ်းမည် + Gemini AI ဖြင့် နာမည် ဖတ်မည်
                        elif message.photo:
                            if message.caption and url_pattern.search(message.caption):
                                photo_bytes = await client.download_media(message.photo, file=bytes)
                                verified_title = await get_movie_title_from_poster(photo_bytes)
                                
                                if verified_title:
                                    clean_title = verified_title
                                    is_photo_with_poster = True
                                else:
                                    clean_title = message.caption.split("\n")[0].strip()
                                
                                should_save = True

                        # (၃) စာသားသီးသန့် (Text) ဆိုရင် လင့်ခ် ပါမှ သိမ်းမည်
                        elif message.text and url_pattern.search(message.text):
                            should_save = True
                            clean_title = message.text.split("\n")[0].strip()

                        # သိမ်းဖို့ သတ်မှတ်ချက်နဲ့ ကိုက်ညီရင် သိမ်းမည်
                        if should_save and clean_title:
                            if clean_title.lower() not in existing_titles:
                                if is_photo_with_poster:
                                    # Poster ပုံဖြစ်ပါက အင်္ဂလိပ် နာမည်ပါ Search မိအောင် Caption တွင် ထည့်သိမ်းမည်
                                    new_caption = f"{message.caption}\n\n🎬 **Detected Title:** {clean_title}"
                                    await client.send_file(ARCHIVE_CHANNEL_ID, message.photo, caption=new_caption)
                                else:
                                    await client.forward_messages(ARCHIVE_CHANNEL_ID, message)
                                    
                                existing_titles.add(clean_title.lower())
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
        if event: await event.reply(f"❌ Scan ဖတ်ရာတွင် အမှား: {str(e)}")

@client.on(events.NewMessage(chats=ACE_BOT_ID, pattern="SCAN_CHANNELS_AUTO"))
async def handle_auto_scan(event):
    await scan_and_forward(event)

async def daily_auto_scan():
    await asyncio.sleep(15)
    while True:
        await scan_and_forward()
        await asyncio.sleep(86400)

# --- (၂) Main Bot မှ ရှာခိုင်းသည့်အခါ Message ID ပို့ပေးရန် ---
@client.on(events.NewMessage(from_users=ACE_BOT, pattern=r'SEARCH_MOVIE:(.+):(\d+)'))
async def handle_movie_search(event):
    query = event.pattern_match.group(1).lower()
    target_chat_id = event.pattern_match.group(2)
    
    try:
        found_count = 0
        async for msg in client.iter_messages(ARCHIVE_CHANNEL_ID, search=query, limit=5):
            found_count += 1
            await client.send_message(
                ACE_BOT, 
                f"MOVIE_ID:{msg.id}:CHAT_ID:{target_chat_id}"
            )
            await asyncio.sleep(0.5)
            
        if found_count == 0:
            await client.send_message(ACE_BOT, f"❌ '{query}' နှင့် ပတ်သက်သော ဇာတ်ကား/Poster မတွေ့ရှိပါ။\n\nCHAT_ID:{target_chat_id}")
            
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
    
    client.loop.create_task(daily_auto_scan())
    client.run_until_disconnected()
