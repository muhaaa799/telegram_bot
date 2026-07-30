import json
import time
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from openai import OpenAI
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

# ==========================================
# 1. DUMMY WEB SERVER TO TRICK RENDER
# ==========================================
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")
        
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_dummy_server():
    # Render assigns a port dynamically via the PORT environment variable
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), DummyHandler)
    server.serve_forever()

# Start the dummy web server on a separate background thread
threading.Thread(target=run_dummy_server, daemon=True).start()

# ==========================================
# 2. BOT CONFIGURATION & CREDENTIALS
# ==========================================
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
AIPIPE_TOKEN = os.environ["AIPIPE_TOKEN"]
LOG_URL = "https://raw.githubusercontent.com/muhaaa799/telegram_bot/main/run.jsonl"
LOG_FILE = "run.jsonl"

client = OpenAI(base_url="https://aipipe.org/openai/v1", api_key=AIPIPE_TOKEN)

# Keeps the last few messages per chat, so multi-turn questions work
conversation_history = {}

# ==========================================
# 3. LOGGING & AUTO-PUSH LOGIC
# ==========================================
def log_event(event: dict):
    event["timestamp"] = time.time()
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(event) + "\n")
    
    # Automatically push the updated log to GitHub
    os.system("git add run.jsonl && git commit -m log && git push")

# ==========================================
# 4. MESSAGE HANDLING & LLM LOGIC
# ==========================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text

    log_event({"type": "incoming", "chat_id": chat_id, "text": user_text})

    history = conversation_history.setdefault(chat_id, [])
    history.append({"role": "user", "content": user_text})

    # Ask the AI to work out the answer. The system prompt tells it exactly how to format the final reply
    system_prompt = (
        "You are a careful data analyst. The user's LAST message asks a "
        "question and tells you exactly what JSON shape to reply with. Work out the "
        "real answer (use any public data you know, e.g. MOSPI statistics, general "
        "world knowledge, or arithmetic on numbers given in the message). "
        "Reply with ONLY that exact JSON object and absolutely nothing else. No "
        "explanation, no markdown, no code fences, just the raw JSON."
    )

    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[{"role": "system", "content": system_prompt}] + history
    )

    reply_text = response.choices[0].message.content.strip()
    history.append({"role": "assistant", "content": reply_text})

    # Make sure we actually reply with valid JSON containing "log_url"
    try:
        parsed = json.loads(reply_text)
    except json.JSONDecodeError:
        # Model added extra text - try to pull out just the {...} part.
        start, end = reply_text.find("{"), reply_text.rfind("}")
        parsed = json.loads(reply_text[start:end + 1])

    parsed["log_url"] = LOG_URL
    final_reply = json.dumps(parsed)

    log_event({"type": "outgoing", "chat_id": chat_id, "text": final_reply})
    await update.message.reply_text(final_reply)

# ==========================================
# 5. START THE BOT
# ==========================================
app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("Bot is running... (Ctrl+C to stop)")
app.run_polling()
