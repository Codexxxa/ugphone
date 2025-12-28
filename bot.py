import os
import json
import logging
import asyncio
from typing import Dict, List, Optional
from datetime import datetime

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import NetworkError
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from ugphone_api import attempt_purchase, validate_credentials

# Define the filter class to suppress NetworkError logs
class NetworkErrorFilter(logging.Filter):
    def filter(self, record):
        if record.exc_info:
            exc_type, exc_value, _ = record.exc_info
            if isinstance(exc_value, NetworkError) or "Bad Gateway" in str(exc_value):
                return False
        if "Bad Gateway" in record.getMessage():
            return False
        if "NetworkError" in record.getMessage():
            return False
        return True

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Silence httpx and urllib3 logging to prevent spam
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

# Apply filter to telegram.ext.Updater to suppress transient network errors
logging.getLogger("telegram.ext.Updater").addFilter(NetworkErrorFilter())

# Load environment variables
load_dotenv()
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# File to store accounts
ACCOUNTS_FILE = 'accounts.json'

class AccountManager:
    def __init__(self, filename):
        self.filename = filename
        self.accounts = self.load_accounts() # Structure: { str(user_id): [ { "ug_id": "...", "token": "..." } ] }

    def load_accounts(self) -> Dict[str, List[dict]]:
        if not os.path.exists(self.filename):
            return {}
        try:
            with open(self.filename, 'r') as f:
                data = json.load(f)
                # Migration check: if list (old format), discard or migrate.
                # User said "ignore old data", so if it's a list, return empty dict.
                if isinstance(data, list):
                    return {}
                return data
        except json.JSONDecodeError:
            return {}

    def save_accounts(self):
        with open(self.filename, 'w') as f:
            json.dump(self.accounts, f, indent=4)

    def add_account(self, user_id: int, token: str, ug_id: str) -> str:
        s_user_id = str(user_id)
        if s_user_id not in self.accounts:
            self.accounts[s_user_id] = []

        user_accounts = self.accounts[s_user_id]

        # Check if exists
        for acc in user_accounts:
            if acc['ug_id'] == ug_id:
                acc['token'] = token
                self.save_accounts()
                return "Account updated."

        user_accounts.append({"ug_id": ug_id, "token": token})
        self.save_accounts()
        return "Account added."

    def remove_account(self, user_id: int, ug_id: str) -> bool:
        s_user_id = str(user_id)
        if s_user_id not in self.accounts:
            return False

        initial_len = len(self.accounts[s_user_id])
        self.accounts[s_user_id] = [acc for acc in self.accounts[s_user_id] if acc['ug_id'] != ug_id]

        if len(self.accounts[s_user_id]) < initial_len:
            self.save_accounts()
            return True
        return False

    def get_accounts(self, user_id: int) -> List[dict]:
        return self.accounts.get(str(user_id), [])

    def get_all_users(self) -> List[str]:
        return list(self.accounts.keys())

account_manager = AccountManager(ACCOUNTS_FILE)

# In-memory status tracking to avoid spamming
# Structure: { str(user_id): { str(ug_id): { "last_msg_id": int, "last_status": str } } }
status_tracker = {}

def update_status_tracker(user_id: int, ug_id: str, msg_id: int, status: str):
    s_uid = str(user_id)
    if s_uid not in status_tracker:
        status_tracker[s_uid] = {}
    status_tracker[s_uid][ug_id] = {"last_msg_id": msg_id, "last_status": status}

def get_status_tracker(user_id: int, ug_id: str):
    s_uid = str(user_id)
    return status_tracker.get(s_uid, {}).get(ug_id)

def clear_status_tracker(user_id: int, ug_id: str):
    s_uid = str(user_id)
    if s_uid in status_tracker and ug_id in status_tracker[s_uid]:
        del status_tracker[s_uid][ug_id]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to the UgPhone Auto-Buyer Bot!\n\n"
        "Commands:\n"
        "/add - Add a UgPhone account (Paste UGPHONE-MQTT JSON)\n"
        "/list - List your accounts\n"
        "/remove - Remove an account\n"
        "\n"
        "The bot will automatically check for stock and attempt to purchase. "
        "You will receive status updates here."
    )

def parse_credentials(json_input: str):
    try:
        data = json.loads(json_input)
    except json.JSONDecodeError:
        return None, None, "Invalid JSON format."

    if "access_token" in data and "login_id" in data:
        return data["access_token"], data["login_id"], None

    # Legacy support if user pastes old format
    if "UGPHONE-Token" in data and "UGPHONE-ID" in data:
        return data["UGPHONE-Token"], data["UGPHONE-ID"], None

    return None, None, "JSON must contain 'access_token' and 'login_id' (UGPHONE-MQTT)."

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Please paste the **UGPHONE-MQTT** JSON string to add your account.\n"
        "Example: `{\"access_token\": \"...\", \"login_id\": \"...\", ...}`"
    )
    # Set state to wait for input?
    # For simplicity, we can just handle the next text message,
    # but a better way is to ask the user to use the command like `/add <json>`
    # or just listen to text if we had a conversation handler.
    # Given the requirements, let's keep it simple: tell user to send JSON.
    # However, to avoid parsing random chat, let's suggest `/add_data <json>` or just rely on the user sending it.
    # A cleaner approach for Telegram is often conversation handlers, but let's try a direct command argument first.
    # If the JSON is long/complex, pasting it as an argument might be tricky on mobile.
    # Let's use a simple approach: The user uses `/add`, and we reply.
    # The NEXT message from the user is treated as the key IF it looks like JSON?
    # No, let's just make a command `/add_account <json>` or ask them to reply to the bot.
    # Actually, simpler: Any message that is valid JSON with the right keys is treated as an add attempt?
    # Use ConversationHandler? Yes, better experience.

    # For now, let's stick to a simpler implementation:
    # User sends /add, bot says "Paste JSON". User pastes JSON.
    # But wait, without ConversationHandler, we don't know context.
    # Let's use `/add <json>` for now, but if no args, tell them how to use it.

    if context.args:
        # Join args in case spaces are in JSON
        json_str = " ".join(context.args)
        await process_add_account(update, json_str)
    else:
        # Prompt user to copy-paste
        await update.message.reply_text("Usage: `/add <Paste JSON Here>`", parse_mode='Markdown')

async def process_add_account(update: Update, json_str: str):
    user_id = update.effective_user.id
    token, ug_id, error = parse_credentials(json_str)

    if error:
        await update.message.reply_text(f"❌ Error: {error}")
        return

    msg = await update.message.reply_text("Validating credentials...")

    is_valid, val_msg = await asyncio.get_running_loop().run_in_executor(
        None, validate_credentials, token, ug_id
    )

    if not is_valid:
        await msg.edit_text(f"❌ Validation Failed: {val_msg}")
        return

    result = account_manager.add_account(user_id, token, ug_id)
    await msg.edit_text(f"✅ {result} (ID: {ug_id})")

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    accounts = account_manager.get_accounts(user_id)

    if not accounts:
        await update.message.reply_text("You have no configured accounts.")
        return

    text = "📋 **Your Accounts:**\n\n"
    for i, acc in enumerate(accounts, 1):
        # Mask token
        t = acc['token']
        masked = t[:5] + "..." + t[-5:] if len(t) > 10 else "***"
        text += f"{i}. ID: `{acc['ug_id']}`\n   Token: `{masked}`\n\n"

    await update.message.reply_text(text, parse_mode='Markdown')

async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    accounts = account_manager.get_accounts(user_id)

    if not accounts:
        await update.message.reply_text("You have no accounts to remove.")
        return

    keyboard = []
    for acc in accounts:
        ug_id = acc['ug_id']
        # Button callback data: REMOVE:<ug_id>
        keyboard.append([InlineKeyboardButton(f"Delete ID: {ug_id}", callback_data=f"REMOVE:{ug_id}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select an account to remove:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("REMOVE:"):
        ug_id = data.split(":", 1)[1]
        user_id = query.from_user.id

        if account_manager.remove_account(user_id, ug_id):
            await query.edit_message_text(f"✅ Account {ug_id} removed.")
        else:
            await query.edit_message_text(f"❌ Account {ug_id} not found or already removed.")

async def purchase_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Background task to iterate all users and accounts.
    """
    all_users = account_manager.get_all_users()

    for user_id_str in all_users:
        user_id = int(user_id_str)
        accounts = account_manager.get_accounts(user_id)

        # Snapshot copy to allow modification (removal) during iteration
        for acc in list(accounts):
            ug_id = acc['ug_id']
            token = acc['token']

            # Run purchase logic
            res = await asyncio.get_running_loop().run_in_executor(
                None, attempt_purchase, token, ug_id
            )

            timestamp = datetime.now().strftime("%H:%M:%S")
            status_msg = f"[{timestamp}] {res['message']}"

            # Log process status to console as requested
            logging.info(f"User {user_id} - Account {ug_id}: {res['message']}")

            tracker = get_status_tracker(user_id, ug_id)

            if res['success']:
                # Notify success
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"🎉 **SUCCESS!**\n\nAccount: `{ug_id}`\nMessage: {res['message']}\n\nAccount has been removed from the list."
                    )
                except Exception as e:
                    logging.error(f"Failed to send success msg to {user_id}: {e}")

                # Remove account
                account_manager.remove_account(user_id, ug_id)
                clear_status_tracker(user_id, ug_id)

            else:
                # Check for critical errors
                msg_text = res['message']
                if msg_text == "Could not find UVIP config ID." or msg_text == "Failed to get Amount ID. Msg: Do not repeat the activity":

                    critical_msg = (
                        "Purchase failed and account removed. "
                        "You must use a new UgPhone account that has never claimed a trial "
                        "and has already claimed the 250 Diamonds bonus for new users."
                    )

                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=f"❌ **CRITICAL ERROR**\n\nAccount: `{ug_id}`\n\n{critical_msg}\n\nOriginal Error: {msg_text}"
                        )
                    except Exception as e:
                        logging.error(f"Failed to send critical error msg to {user_id}: {e}")

                    # Remove account
                    account_manager.remove_account(user_id, ug_id)
                    clear_status_tracker(user_id, ug_id)
                    continue

                # Notify progress/failure
                # If we have a tracked message, try to edit it
                # If the status message content is basically the same (ignoring timestamp), maybe don't edit every time to save rate limits?
                # User wants to know "process is running".

                # Logic:
                # If no message tracked -> Send new message, track ID.
                # If message tracked -> Edit message with new timestamp/status.
                # If edit fails (e.g. message deleted), send new one.

                should_send_new = False
                msg_id = None

                if tracker:
                    msg_id = tracker['last_msg_id']
                    # Try to edit
                    try:
                        await context.bot.edit_message_text(
                            chat_id=user_id,
                            message_id=msg_id,
                            text=f"🔄 **Processing...**\nID: `{ug_id}`\nStatus: {status_msg}"
                        )
                    except Exception:
                        # Message might be deleted or too old. Send new one.
                        should_send_new = True
                else:
                    should_send_new = True

                if should_send_new:
                    try:
                        sent_msg = await context.bot.send_message(
                            chat_id=user_id,
                            text=f"🔄 **Processing...**\nID: `{ug_id}`\nStatus: {status_msg}"
                        )
                        update_status_tracker(user_id, ug_id, sent_msg.message_id, status_msg)
                    except Exception as e:
                        logging.error(f"Failed to send status msg to {user_id}: {e}")


def main():
    if not TOKEN or TOKEN == "your_telegram_bot_token_here":
        print("Error: TELEGRAM_BOT_TOKEN not set in .env")
        return

    application = ApplicationBuilder().token(TOKEN).build()

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add", add_command))
    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(CommandHandler("remove", remove_command))
    application.add_handler(CallbackQueryHandler(button_handler))

    # Job Queue
    job_queue = application.job_queue
    job_queue.run_repeating(purchase_job, interval=60, first=10)

    print("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
