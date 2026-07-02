# main.py
# ================= requirements.txt =================
"""
python-telegram-bot==20.7
androguard==3.4.0.1
aiofiles==23.2.1
"""

import asyncio
import logging
import os
import re
import tempfile
import zipfile
import json
from pathlib import Path
from typing import Optional, Dict
import base64
import io

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from androguard.core.apk import APK

# ================= CONFIG =================

BOT_TOKEN = "8622682032:AAF_2WW4daRtuES_tZoYx-D6tJu4QJ2fNjA"  # REPLACE WITH YOUR BOT TOKEN

# ================= LOGGING =================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================= KEYBOARDS =================

main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📱 Extract Firebase Config")],
        [KeyboardButton(text="ℹ️ Help")],
    ],
    resize_keyboard=True
)

# ================= FIREBASE EXTRACTOR =================

class FirebaseExtractor:
    """Extract Firebase configuration from APK files"""
    
    # Firebase patterns
    FIREBASE_URL_PATTERNS = [
        re.compile(rb'https://[a-zA-Z0-9\-_]+\.firebaseio\.com'),
        re.compile(rb'https://[a-zA-Z0-9\-_]+\.firebasedatabase\.app'),
        re.compile(rb'"firebase_url":"([^"]+)"'),
        re.compile(rb'firebaseUrl\s*[:=]\s*["\']([^"\']+)["\']'),
        re.compile(rb'https://[a-zA-Z0-9\-_]+\.firebase\.io'),
    ]
    
    API_KEY_PATTERNS = [
        re.compile(rb'AIza[0-9A-Za-z\-_]{35}'),
        re.compile(rb'"api_key":"([^"]+)"'),
        re.compile(rb'apiKey\s*[:=]\s*["\']([^"\']+)["\']'),
        re.compile(rb'AIza[0-9A-Za-z\-_]{35,40}'),
    ]
    
    PROJECT_ID_PATTERNS = [
        re.compile(rb'"project_id":"([^"]+)"'),
        re.compile(rb'projectId\s*[:=]\s*["\']([^"\']+)["\']'),
        re.compile(rb'project_id\s*[:=]\s*["\']([^"\']+)["\']'),
    ]
    
    BUCKET_URL_PATTERNS = [
        re.compile(rb'"storage_bucket":"([^"]+)"'),
        re.compile(rb'storageBucket\s*[:=]\s*["\']([^"\']+)["\']'),
        re.compile(rb'storage\.googleapis\.com/([a-zA-Z0-9\-_\.]+)'),
    ]
    
    APP_ID_PATTERNS = [
        re.compile(rb'"mobilesdk_app_id":"([^"]+)"'),
        re.compile(rb'appId\s*[:=]\s*["\']([^"\']+)["\']'),
        re.compile(rb'gmp_app_id":"([^"]+)"'),
    ]
    
    SENDER_ID_PATTERNS = [
        re.compile(rb'"project_number":"([^"]+)"'),
        re.compile(rb'senderId\s*[:=]\s*["\']([^"\']+)["\']'),
        re.compile(rb'gcm_sender_id":"([^"]+)"'),
    ]

    @staticmethod
    def extract_strings_from_bytes(data: bytes) -> bytes:
        """Extract readable strings from bytes"""
        strings = []
        current = []
        for byte in data:
            if 32 <= byte <= 126 or byte in (9, 10, 13):
                current.append(byte)
            else:
                if len(current) > 5:
                    strings.append(bytes(current))
                current = []
        if len(current) > 5:
            strings.append(bytes(current))
        return b'\n'.join(strings)

    @classmethod
    def extract_from_bytes(cls, data: bytes) -> Dict[str, Optional[str]]:
        """Extract Firebase config from bytes data"""
        config = {
            "firebase_url": None,
            "api_key": None,
            "project_id": None,
            "project_name": None,
            "storage_bucket": None,
            "app_id": None,
            "sender_id": None,
            "package_name": None,
            "version": None,
        }
        
        # Try all patterns
        for pattern in cls.FIREBASE_URL_PATTERNS:
            matches = pattern.findall(data)
            if matches:
                if isinstance(matches[0], bytes):
                    config["firebase_url"] = matches[0].decode('utf-8', errors='ignore')
                elif isinstance(matches[0], str):
                    config["firebase_url"] = matches[0]
                else:
                    config["firebase_url"] = str(matches[0])
                break
        
        for pattern in cls.API_KEY_PATTERNS:
            matches = pattern.findall(data)
            if matches:
                if isinstance(matches[0], bytes):
                    config["api_key"] = matches[0].decode('utf-8', errors='ignore')
                elif isinstance(matches[0], str):
                    config["api_key"] = matches[0]
                else:
                    config["api_key"] = str(matches[0])
                break
        
        for pattern in cls.PROJECT_ID_PATTERNS:
            matches = pattern.findall(data)
            if matches:
                if isinstance(matches[0], bytes):
                    config["project_id"] = matches[0].decode('utf-8', errors='ignore')
                elif isinstance(matches[0], str):
                    config["project_id"] = matches[0]
                else:
                    config["project_id"] = str(matches[0])
                break
        
        for pattern in cls.BUCKET_URL_PATTERNS:
            matches = pattern.findall(data)
            if matches:
                if isinstance(matches[0], bytes):
                    config["storage_bucket"] = matches[0].decode('utf-8', errors='ignore')
                elif isinstance(matches[0], str):
                    config["storage_bucket"] = matches[0]
                else:
                    config["storage_bucket"] = str(matches[0])
                break
        
        for pattern in cls.APP_ID_PATTERNS:
            matches = pattern.findall(data)
            if matches:
                if isinstance(matches[0], bytes):
                    config["app_id"] = matches[0].decode('utf-8', errors='ignore')
                elif isinstance(matches[0], str):
                    config["app_id"] = matches[0]
                else:
                    config["app_id"] = str(matches[0])
                break
        
        for pattern in cls.SENDER_ID_PATTERNS:
            matches = pattern.findall(data)
            if matches:
                if isinstance(matches[0], bytes):
                    config["sender_id"] = matches[0].decode('utf-8', errors='ignore')
                elif isinstance(matches[0], str):
                    config["sender_id"] = matches[0]
                else:
                    config["sender_id"] = str(matches[0])
                break
        
        return config

    @classmethod
    def extract_from_apk(cls, apk_path: str) -> Dict[str, Optional[str]]:
        """Extract Firebase config from APK file"""
        config = {}
        
        try:
            apk = APK(apk_path)
            config["package_name"] = apk.get_package()
            config["version"] = apk.get_androidversion_name()
            config["version_code"] = apk.get_androidversion_code()
            config["app_name"] = apk.get_app_name()
            
            # Check for google-services.json
            if 'google-services.json' in apk.files:
                try:
                    json_data = apk.get_file('google-services.json')
                    if json_data:
                        services = json.loads(json_data)
                        project_info = services.get('project_info', {})
                        if project_info:
                            config["project_id"] = project_info.get('project_id')
                            config["project_name"] = project_info.get('name')
                            config["firebase_url"] = project_info.get('firebase_url')
                        
                        client = services.get('client', [{}])[0]
                        if client:
                            client_info = client.get('client_info', {})
                            config["app_id"] = client_info.get('mobilesdk_app_id')
                            
                            api_key = client.get('api_key', [{}])[0]
                            config["api_key"] = api_key.get('current_key')
                            
                            oauth_client = client.get('oauth_client', [{}])[0]
                            if oauth_client:
                                config["client_id"] = oauth_client.get('client_id')
                except Exception as e:
                    logger.error(f"Error parsing google-services.json: {e}")
            
            # Check all files for config
            for file_path in apk.files:
                if any(file_path.endswith(ext) for ext in ['.xml', '.json', '.txt', '.properties', '.dex']):
                    try:
                        file_data = apk.get_file(file_path)
                        if file_data:
                            extracted = cls.extract_from_bytes(file_data)
                            for key, value in extracted.items():
                                if value and not config.get(key):
                                    config[key] = value
                    except Exception:
                        pass
            
            # Check resources.arsc specifically
            if 'resources.arsc' in apk.files:
                try:
                    arsc_data = apk.get_file('resources.arsc')
                    if arsc_data:
                        extracted = cls.extract_from_bytes(arsc_data)
                        for key, value in extracted.items():
                            if value and not config.get(key):
                                config[key] = value
                except Exception as e:
                    logger.error(f"Error parsing resources.arsc: {e}")
            
            # Try to find any strings in AndroidManifest
            try:
                manifest = apk.get_android_manifest_xml()
                if manifest:
                    # Look for firebase in manifest
                    manifest_str = str(manifest)
                    extracted = cls.extract_from_bytes(manifest_str.encode())
                    for key, value in extracted.items():
                        if value and not config.get(key):
                            config[key] = value
            except Exception:
                pass
                
        except Exception as e:
            logger.error(f"Error extracting from APK: {e}")
            
        return config

# ================= BOT HANDLERS =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when /start is issued"""
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Hello {user.first_name}!\n\n"
        f"🔍 I can extract Firebase configuration from APK files.\n\n"
        f"📱 Just send me an APK file and I'll extract:\n"
        f"• 🔥 Firebase Database URL\n"
        f"• 🔑 API Key\n"
        f"• 📋 Project ID\n"
        f"• 📝 Project Name\n"
        f"• 📦 Storage Bucket\n"
        f"• 🆔 App ID\n"
        f"• 📬 Sender ID\n"
        f"• 📦 Package Name\n\n"
        f"Send me an APK to get started!",
        reply_markup=main_kb
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send help message"""
    await update.message.reply_text(
        "📚 <b>How to use this bot:</b>\n\n"
        "1️⃣ Send me an APK file\n"
        "2️⃣ I'll analyze it and extract Firebase configuration\n"
        "3️⃣ You'll get all the details in a nice format\n\n"
        "<b>What I can extract:</b>\n"
        "• Firebase URL\n"
        "• API Key\n"
        "• Project ID & Name\n"
        "• Storage Bucket\n"
        "• App ID\n"
        "• Sender ID\n"
        "• Package Name\n"
        "• Version info\n\n"
        "Just send any APK file!",
        parse_mode='HTML',
        reply_markup=main_kb
    )

async def handle_apk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle APK file uploads"""
    message = update.message
    document = message.document
    
    if not document:
        await message.reply_text("❌ Please send an APK file.")
        return
    
    if not document.file_name or not document.file_name.lower().endswith('.apk'):
        await message.reply_text("❌ Please send a valid APK file.")
        return
    
    # Send processing message
    processing_msg = await message.reply_text(
        f"🔍 Analyzing <b>{document.file_name}</b>...\n"
        f"This may take 30-60 seconds.",
        parse_mode='HTML'
    )
    
    try:
        # Download APK
        file = await document.get_file()
        
        # Create temp file
        with tempfile.NamedTemporaryFile(suffix='.apk', delete=False) as tmp_file:
            await file.download_to_drive(tmp_file.name)
            tmp_path = tmp_file.name
        
        # Extract config
        config = FirebaseExtractor.extract_from_apk(tmp_path)
        
        # Clean up
        try:
            os.unlink(tmp_path)
        except:
            pass
        
        # Format results
        if any(config.values()):
            result_text = f"📊 <b>Firebase Configuration</b>\n"
            result_text += f"📱 <b>File:</b> {document.file_name}\n\n"
            
            if config.get('app_name'):
                result_text += f"📝 <b>App Name:</b> {config['app_name']}\n"
            
            if config.get('package_name'):
                result_text += f"📦 <b>Package:</b> <code>{config['package_name']}</code>\n"
            
            if config.get('version'):
                result_text += f"📌 <b>Version:</b> {config['version']}"
                if config.get('version_code'):
                    result_text += f" ({config['version_code']})"
                result_text += "\n\n"
            
            result_text += "🔥 <b>Firebase Configuration:</b>\n\n"
            
            found = False
            
            # Firebase URL
            if config.get('firebase_url'):
                result_text += f"🔗 <b>Firebase URL:</b>\n<code>{config['firebase_url']}</code>\n\n"
                found = True
            
            # API Key
            if config.get('api_key'):
                result_text += f"🔑 <b>API Key:</b>\n<code>{config['api_key']}</code>\n\n"
                found = True
            
            # Project ID
            if config.get('project_id'):
                result_text += f"📋 <b>Project ID:</b>\n<code>{config['project_id']}</code>\n\n"
                found = True
            
            # Project Name
            if config.get('project_name'):
                result_text += f"📝 <b>Project Name:</b>\n{config['project_name']}\n\n"
                found = True
            
            # Storage Bucket
            if config.get('storage_bucket'):
                result_text += f"📦 <b>Storage Bucket:</b>\n<code>{config['storage_bucket']}</code>\n\n"
                found = True
            
            # App ID
            if config.get('app_id'):
                result_text += f"🆔 <b>App ID:</b>\n<code>{config['app_id']}</code>\n\n"
                found = True
            
            # Sender ID
            if config.get('sender_id'):
                result_text += f"📬 <b>Sender ID:</b>\n<code>{config['sender_id']}</code>\n\n"
                found = True
            
            # Client ID
            if config.get('client_id'):
                result_text += f"🔐 <b>Client ID:</b>\n<code>{config['client_id']}</code>\n\n"
                found = True
            
            if not found:
                result_text += "❌ No Firebase configuration found in this APK.\n\n"
                result_text += "💡 This app might not use Firebase, or the config is obfuscated."
            
            # Delete processing message and send results
            await processing_msg.delete()
            await message.reply_text(result_text, parse_mode='HTML')
            
            # Also send as a file in case message is too long
            if len(result_text) > 4000:
                with io.BytesIO(result_text.encode()) as f:
                    f.name = "firebase_config.txt"
                    await message.reply_document(
                        document=f,
                        caption="📄 Full configuration exported as text file."
                    )
            
        else:
            await processing_msg.edit_text("❌ No Firebase configuration found in this APK.")
            
    except Exception as e:
        logger.error(f"Error processing APK: {e}")
        await processing_msg.edit_text(f"❌ Error processing APK: {str(e)[:100]}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button presses"""
    text = update.message.text
    
    if text == "📱 Extract Firebase Config":
        await update.message.reply_text(
            "📱 Send me an APK file and I'll extract all Firebase configuration.\n\n"
            "🔍 Looking for:\n"
            "• Firebase URL\n"
            "• API Key\n"
            "• Project ID\n"
            "• Storage Bucket\n"
            "• App ID\n"
            "• And more!"
        )
    elif text == "ℹ️ Help":
        await help_command(update, context)
    else:
        await update.message.reply_text(
            "Send me an APK file or use the buttons below.",
            reply_markup=main_kb
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")

# ================= MAIN =================

async def main():
    """Start the bot"""
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_handler))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_apk))
    application.add_handler(MessageHandler(filters.ANIMATION, handle_apk))
    application.add_error_handler(error_handler)
    
    # Start the bot
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    logger.info("Bot started. Press Ctrl+C to stop.")
    
    try:
        # Keep the bot running
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

if __name__ == "__main__":
    asyncio.run(main())