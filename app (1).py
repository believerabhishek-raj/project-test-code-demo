import telebot
import time
import json
import os
import threading
from flask import Flask

# Render environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MY_CHAT_ID = int(os.environ.get("MY_CHAT_ID"))

bot = telebot.TeleBot(BOT_TOKEN, threaded=True)
app = Flask(__name__)

DB_FILE = "users_db.json"
sessions = {}
pending_links = {}
forwarded_messages = {}

def load_users():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f: return set(json.load(f))
        except: return set()
    return set()

def save_user(user_id):
    users = load_users()
    if user_id not in users:
        users.add(user_id)
        with open(DB_FILE, "w") as f: json.dump(list(users), f)

# Memory-safe execution for automatic 10 seconds deletion
def safe_delete(chat_id, message_id):
    try:
        bot.delete_message(chat_id, message_id)
    except:
        pass

def delete_after_10_sec(chat_id, message_id):
    t = threading.Timer(10, safe_delete, args=[chat_id, message_id])
    t.daemon = True
    t.start()

def track_message(user_id, message_id):
    if user_id not in sessions:
        sessions[user_id] = {"start_time": time.time(), "messages": []}
    sessions[user_id]["messages"].append(message_id)

# 1. Welcome Message (With Invisible Dot Screenshot Guard)
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.chat.id
    save_user(user_id)
    bot.send_chat_action(user_id, 'typing')
    
    # 🔥 INVISIBLE GUARD: Only a single dot that STAYS forever to block screenshots layout perfectly
    bot.send_message(user_id, ".", protect_content=True)
    
    msg = bot.send_message(user_id, "Bolo kya Chahiye.", protect_content=True)
    
    delete_after_10_sec(user_id, msg.message_id)
    delete_after_10_sec(user_id, message.message_id)

# Admin Memory Clean
@bot.message_handler(commands=['clean'], func=lambda message: message.chat.id == MY_CHAT_ID)
def admin_clean_memory(message):
    global sessions, pending_links, forwarded_messages
    sessions.clear()
    pending_links.clear()
    forwarded_messages.clear()
    bot.send_message(MY_CHAT_ID, "🧹 **System Memory Flushed!** All temporary lists cleared safely.")

# 2. Bulk Broadcast
@bot.message_handler(commands=['broadcast'], func=lambda message: message.chat.id == MY_CHAT_ID, content_types=['text', 'photo'])
def handle_broadcast(message):
    is_photo = message.content_type == 'photo'
    text = message.caption.strip() if is_photo else message.text.strip()
    
    parts = text.split(' ', 1)
    if len(parts) < 2:
        bot.send_message(MY_CHAT_ID, "❌ Format: `/broadcast Message` ya photo caption me.")
        return
        
    broadcast_msg = parts[1]
    all_users = load_users()
    bot.send_message(MY_CHAT_ID, f"📢 Broadcasting to {len(all_users)} users...")
    success, fail = 0, 0
    
    photo_id = message.photo[-1].file_id if is_photo else None

    for uid in all_users:
        if uid == MY_CHAT_ID: continue
        try:
            if is_photo:
                sent = bot.send_photo(uid, photo_id, caption=broadcast_msg, protect_content=True)
            else:
                sent = bot.send_message(uid, broadcast_msg, protect_content=True)
            track_message(uid, sent.message_id)
            success += 1
            time.sleep(0.05)
        except: 
            fail += 1
            
    bot.send_message(MY_CHAT_ID, f"✅ Done!\n🎯 Sent: {success}\n❌ Failed: {fail}")

# 3. User Msg Forwarding
@bot.message_handler(func=lambda message: message.chat.id != MY_CHAT_ID, content_types=['text', 'photo'])
def forward_to_admin(message):
    user_id = message.chat.id
    save_user(user_id)
        
    auto_msg = bot.send_message(user_id, "Message Sent ✅, Wait for reply ", protect_content=True)
    
    # 10 seconds tracking enabled for user text content
    delete_after_10_sec(user_id, auto_msg.message_id)
    delete_after_10_sec(user_id, message.message_id)
    
    first_name = message.from_user.first_name or ""
    last_name = message.from_user.last_name or ""
    full_name = f"{first_name} {last_name}".strip()
    username = f"@{message.from_user.username}" if message.from_user.username else "No Username ❌"
    
    if message.content_type == 'photo':
        bot.send_chat_action(MY_CHAT_ID, 'upload_photo')
        photo_id = message.photo[-1].file_id
        caption = message.caption if message.caption else "[No Caption]"
        admin_info = f"📸 *New Photo From:* `{user_id}`\n👤 Name: {full_name}\n🔗 User: {username}\n\n📝 Caption: {caption}\n\n👉 Reply: Swipe to reply OR `/reply {user_id} message` \n👉 End chat: `/end {user_id}`"
        fwd_msg = bot.send_photo(MY_CHAT_ID, photo_id, caption=admin_info, parse_mode="Markdown")
    else:
        bot.send_chat_action(MY_CHAT_ID, 'typing')
        admin_info = f"📩 *New Msg From:* `{user_id}`\n👤 Name: {full_name}\n🔗 User: {username}\n\n💬 Message:\n{message.text}\n\n👉 Reply: Swipe to reply OR `/reply {user_id} message` \n👉 End chat: `/end {user_id}`"
        fwd_msg = bot.send_message(MY_CHAT_ID, admin_info, parse_mode="Markdown")
        
    forwarded_messages[fwd_msg.message_id] = user_id

# 4. Admin Reply Handler
@bot.message_handler(func=lambda message: message.chat.id == MY_CHAT_ID, content_types=['text', 'photo'])
def handle_admin_reply(message):
    is_photo = message.content_type == 'photo'
    text = message.caption.strip() if is_photo else (message.text.strip() if message.text else "")
    
    target_user_id = None
    reply_text = text
    
    if text.startswith('/end '):
        try:
            target_user_id = int(text.split(' ')[1])
            end_conversation(target_user_id)
        except:
            bot.send_message(MY_CHAT_ID, "❌ Format: /end [USER_ID]")
        return

    if text.startswith('/reply '):
        try:
            parts = text.split(' ', 2)
            target_user_id = int(parts[1])
            reply_text = parts[2] if len(parts) == 3 else ""
        except Exception as e:
            bot.send_message(MY_CHAT_ID, f"❌ Command Error: {str(e)}")
            return
            
    elif message.reply_to_message:
        replied_msg_id = message.reply_to_message.message_id
        if replied_msg_id in forwarded_messages:
            target_user_id = forwarded_messages[replied_msg_id]

    if not target_user_id:
        return

    if reply_text.lower() == "chat end":
        end_conversation(target_user_id)
        return

    try:
        if not is_photo and ("http://" in reply_text or "https://" in reply_text):
            pending_links[target_user_id] = reply_text
            markup = telebot.types.InlineKeyboardMarkup()
            btn = telebot.types.InlineKeyboardButton(text="👉 ACCESS PREMIUM LINK 🚀", callback_data="get_secret_link")
            markup.add(btn)
            
            sent_msg = bot.send_message(target_user_id, "⚠️ Niche diye gaye button par click karein. Link sirf 10 seconds ke liye dikhega aur copy/forward nahi hoga!", reply_markup=markup, protect_content=True)
            track_message(target_user_id, sent_msg.message_id)
            bot.send_message(MY_CHAT_ID, f"⏳ Link button sent to {target_user_id}.")
        else:
            if is_photo:
                bot.send_chat_action(target_user_id, 'upload_photo')
                photo_id = message.photo[-1].file_id
                sent_msg = bot.send_photo(target_user_id, photo_id, caption=reply_text, protect_content=True)
            else:
                bot.send_chat_action(target_user_id, 'typing')
                sent_msg = bot.send_message(target_user_id, reply_text, protect_content=True)
                
            track_message(target_user_id, sent_msg.message_id)
            bot.send_message(MY_CHAT_ID, f"✅ Delivered to {target_user_id}")
    except Exception as e:
        bot.send_message(MY_CHAT_ID, f"❌ Delivery Error: {str(e)}")

# 5. Secret Link Deletion
@bot.callback_query_handler(func=lambda call: call.data == "get_secret_link")
def handle_link_click(call):
    user_id = call.message.chat.id
    if user_id in pending_links:
        actual_link = pending_links[user_id]
        del pending_links[user_id]
        try: 
            bot.delete_message(user_id, call.message.message_id)
        except: 
            pass
        
        link_msg = bot.send_message(user_id, f"👇 Link is protected! Auto-deleting in 10 seconds:\n\n{actual_link}", protect_content=True)
        delete_after_10_sec(user_id, link_msg.message_id)
    else:
        bot.answer_callback_query(call.id, "❌ Yeh link expired ho chuka hai!", show_alert=True)

# 6. End Conversation Core Module (Wipes all tracked chat content instantly)
def end_conversation(user_id):
    if user_id in sessions:
        for msg_id in sessions[user_id]["messages"]:
            try: 
                bot.delete_message(user_id, msg_id)
            except: 
                pass
        del sessions[user_id]
    try: 
        end_msg = bot.send_message(user_id, "🔒 Is session ko end kar diya gaya hai. Hum aapse jald hi naye session me milenge!", protect_content=True)
        delete_after_10_sec(user_id, end_msg.message_id)
        bot.send_message(MY_CHAT_ID, f"🧹 Session safely closed and cleared for user: `{user_id}`")
    except: 
        pass

@app.route('/')
def home():
    return "Dummy Port Listener Active", 200

def run_dummy_server():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    bot.remove_webhook()
    time.sleep(1)
    
    threading.Thread(target=run_dummy_server, daemon=True).start()
    
    print("🤖 Polling track launched perfectly with Absolute Privacy Restrictions...")
    bot.infinity_polling(timeout=15, long_polling_timeout=5)
