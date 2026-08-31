import os
import asyncio
from telethon import events
from telethon import TelegramClient
from telethon.sessions import StringSession
from dotenv import load_dotenv

load_dotenv()

api_id = int(os.getenv("USERBOT_API_ID"))
api_hash = os.getenv("USERBOT_API_HASH")

ACE_BOT_ID = 8255035281
ACE_BOT = '@ace_study_ass_bot'   
TARGET_SONGBOT = '@somgsforme_bot'
ARCHIVE_CHANNEL_ID = -1003943796781 

# SESSION_STRING စစ်ဆေးပြီး ချိတ်ဆက်ခြင်း
session_string = os.getenv("SESSION_STRING")
if session_string:
    client = TelegramClient(StringSession(session_string), api_id, api_hash)
else:
    client = TelegramClient('my_userbot', api_id, api_hash)

active_song_requests = []

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
                existing_titles.add(arch_title.split('\n')[0].strip().lower())
                
        async for dialog in client.iter_dialogs():
            if dialog.is_channel or dialog.is_group:
                if dialog.id == ARCHIVE_CHANNEL_ID: continue 
                
                scanned_channels += 1
                try:
                    async for message in client.iter_messages(dialog.entity, limit=500):
                        if getattr(message, 'action', None): continue
                        
                        title = None
                        if message.video or message.document:
                            title = message.caption or getattr(message.video or message.document, 'file_name', None) or ""
                        elif message.photo:
                            title = message.caption or ""
                        elif message.text and "http" in message.text:
                            title = message.text

                        if title:
                            clean_title = title.split("\n")[0].strip()
                            if clean_title and clean_title.lower() not in existing_titles:
                                await client.forward_messages(ARCHIVE_CHANNEL_ID, message)
                                existing_titles.add(clean_title.lower())
                                added_count += 1
                                await asyncio.sleep(0.5)
                                
                    await asyncio.sleep(2)
                except Exception:
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
song_request_lock = asyncio.Lock()
@client.on(events.NewMessage(from_users=ACE_BOT, pattern=r'GET_SONG:(.+):(\d+)'))
async def handle_song_request(event):
    song_name = event.pattern_match.group(1)
    target_chat_id = event.pattern_match.group(2)
    
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
                        # နှိပ်လိုက်တဲ့ ခလုတ်အရေအတွက်အတိုင်း target_chat_id ကို queue ထဲ ထည့်ပေးခြင်း
                        active_song_requests.append(target_chat_id)
                        await button.click()
                        await asyncio.sleep(2)
                        
        except Exception as e:
            print(f"Song fetch error: {e}")


@client.on(events.NewMessage(from_users=TARGET_SONGBOT))
async def capture_songs(event):
    if event.media and active_song_requests:
        target_chat_id = active_song_requests.pop(0)
        caption_text = f"🎵 CHAT_ID:{target_chat_id}"
        
        await client.send_file(ACE_BOT, event.media, caption=caption_text)

# --- (၄) ပရိုဂရမ် စတင်ခြင်း ---
if __name__ == '__main__':
    print("⚡ Userbot စတင် အလုပ်လုပ်နေပြီ...")
    client.start()
    
    client.loop.create_task(daily_auto_scan())
    client.run_until_disconnected()
