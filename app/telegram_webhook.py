"""
Telegram Webhook Handler
Processa updates do Telegram sem precisar de polling
"""
import logging
import requests
import io
import os
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Read token from environment (do not hardcode in source)
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
if TELEGRAM_TOKEN:
    TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
else:
    TELEGRAM_API = None
    logger.warning('TELEGRAM_TOKEN not set in environment; Telegram API calls will fail until token is provided')


def send_reaction(chat_id: int, message_id: int, emoji: str = "✅"):
    """Enviar reação para mensagem"""
    try:
        requests.post(
            f"{TELEGRAM_API}/setMessageReaction",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "reaction": [{"type": "emoji", "emoji": emoji}]
            },
            timeout=5
        )
    except Exception as e:
        logger.error(f"Erro ao enviar reação: {e}")


def send_message(chat_id: int, text: str, reply_to: int = None):
    """Enviar mensagem de texto"""
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        if reply_to:
            payload["reply_to_message_id"] = reply_to
            
        requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json=payload,
            timeout=10
        )
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem: {e}")


def download_file(file_id: str) -> bytes:
    """Baixar arquivo do Telegram"""
    try:
        # Obter file_path
        response = requests.get(
            f"{TELEGRAM_API}/getFile",
            params={"file_id": file_id},
            timeout=10
        )
        
        if response.status_code == 200:
            file_info = response.json()
            if file_info.get('ok'):
                file_path = file_info['result']['file_path']
                file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
                
                # Baixar arquivo
                file_response = requests.get(file_url, timeout=30)
                return file_response.content
    except Exception as e:
        logger.error(f"Erro ao baixar arquivo: {e}")
    
    return None


async def process_telegram_update(update: Dict[str, Any], backend_url: str):
    """
    Processar update do Telegram
    """
    try:
        message = update.get('message')
        if not message:
            return {"ok": True}
        
        chat_id = message.get('chat', {}).get('id')
        message_id = message.get('message_id')
        user_id = message.get('from', {}).get('id')
        first_name = message.get('from', {}).get('first_name', 'Usuário')
        text = message.get('text', '').strip()
        
        # Processar comandos
        if text.startswith('/start'):
            welcome = (
                f"👋 Bem-vindo ao Fluxo-Cash Bot!\n\n"
                f"🆔 Seu ID: `{user_id}`\n\n"
                f"📸 Envie comprovantes PIX (foto ou PDF)\n"
                f"Use /help para mais informações."
            )
            send_message(chat_id, welcome)
            return {"ok": True}
        
        elif text.startswith('/help'):
            help_text = (
                "📚 Ajuda - Fluxo-Cash Bot\n\n"
                "**Comandos:**\n"
                "/start - Iniciar\n"
                "/help - Ajuda\n"
                "/id - Ver seu ID\n\n"
                "**Enviar comprovante:**\n"
                "Envie foto ou PDF do comprovante PIX"
            )
            send_message(chat_id, help_text)
            return {"ok": True}
        
        elif text.startswith('/id'):
            send_message(chat_id, f"🆔 Seu ID: `{user_id}`")
            return {"ok": True}
        
        # Ensure backend_url falls back to production if not provided
        if not backend_url:
            backend_url = os.getenv('BACKEND_URL', 'https://new-bot-nader-production.up.railway.app')

        # Processar foto
        if 'photo' in message:
            send_reaction(chat_id, message_id, "⏳")
            
            photo = message['photo'][-1]  # Maior resolução
            file_bytes = download_file(photo['file_id'])
            
            if file_bytes:
                # Upload para backend
                response = await upload_to_backend(
                    file_bytes=file_bytes,
                    filename=f"comprovante_{user_id}.jpg",
                    user_id=user_id,
                    user_name=first_name,
                        backend_url=backend_url
                )
                
                # Processar resposta
                if response.get('processed'):
                    send_reaction(chat_id, message_id, "✅")
                else:
                    send_reaction(chat_id, message_id, "❌")
            else:
                send_reaction(chat_id, message_id, "❌")
        
        # Processar documento (PDF)
        elif 'document' in message:
            document = message['document']
            if document.get('mime_type') == 'application/pdf':
                send_reaction(chat_id, message_id, "⏳")
                
                file_bytes = download_file(document['file_id'])
                
                if file_bytes:
                    response = await upload_to_backend(
                        file_bytes=file_bytes,
                        filename=document.get('file_name', 'documento.pdf'),
                        user_id=user_id,
                        user_name=first_name,
                        backend_url=backend_url
                    )
                    
                    if response.get('processed'):
                        send_reaction(chat_id, message_id, "✅")
                    else:
                        send_reaction(chat_id, message_id, "❌")
                else:
                    send_reaction(chat_id, message_id, "❌")
        
        return {"ok": True}
        
    except Exception as e:
        logger.error(f"Erro ao processar update: {e}")
        return {"ok": False, "error": str(e)}


async def upload_to_backend(file_bytes: bytes, filename: str, user_id: int, user_name: str, backend_url: str):
    """Upload para o backend"""
    import asyncio
    
    def _upload():
        try:
            files = {'files': (filename, io.BytesIO(file_bytes))}
            data = {
                'telegram_user_id': str(user_id),
                'telegram_user_name': user_name
            }
            
            response = requests.post(
                f"{backend_url}/telegram/upload",
                files=files,
                data=data,
                timeout=120
            )
            
            return response.json()
        except Exception as e:
            logger.error(f"Erro no upload: {e}")
            return {"success": False, "error": str(e)}
    
    return await asyncio.to_thread(_upload)
