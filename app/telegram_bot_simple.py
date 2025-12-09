"""
Telegram Bot - Fluxo Cash v3 (Refeito)
Polling bot com detecção de duplicatas (SHA256, OCR, pHash), validação de usuário,
reactions, media groups, logging robusto e suporte a backend de produção.

Ambiente:
  TELEGRAM_TOKEN: token do bot (obrigatório)
  BACKEND_URL: URL do backend (padrão: https://new-bot-nader-production.up.railway.app)
  OPENAI_API_KEY: opcional, para OCR via OpenAI
  PHASH_THRESHOLD: distância máxima de pHash para duplicata (padrão: 5)
"""

import os
import sys
import logging
import requests
import json
import time
import io
import threading
import hashlib
import base64
import traceback
from pathlib import Path
from dotenv import load_dotenv
from typing import Optional, Tuple, Dict, List, Any

# Optional libraries
try:
    from PIL import Image
except ImportError:
    Image = None

try:
    import imagehash
except ImportError:
    imagehash = None

try:
    import pytesseract
except ImportError:
    pytesseract = None

# ============================================================================
# CONFIGURATION
# ============================================================================

load_dotenv()

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
BACKEND_URL = os.getenv('BACKEND_URL', 'https://new-bot-nader-production.up.railway.app')
PHASH_THRESHOLD = int(os.getenv('PHASH_THRESHOLD', '5'))
BOT_LOG_FILE = Path(__file__).parent / 'bot.log'

# Validate token early
if not TELEGRAM_TOKEN:
    print('ERROR: TELEGRAM_TOKEN not set in environment. Exiting.')
    sys.exit(1)

TELEGRAM_API = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}'

# ============================================================================
# LOGGING
# ============================================================================

def setup_logging():
    """Configure logging to file and console with timestamps."""
    logger = logging.getLogger('telegram_bot')
    logger.setLevel(logging.DEBUG)
    
    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # File handler
    fh = logging.FileHandler(str(BOT_LOG_FILE), encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    
    # Console handler - write to stdout immediately
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG)
    ch.flush = lambda: sys.stdout.flush()  # Force flush after each log
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger

logger = setup_logging()

# ============================================================================
# DUPLICATE DETECTION (Backend-only, no local SQLite)
# ============================================================================

def compute_sha256(file_bytes: bytes) -> str:
    """Compute SHA256 hash of file."""
    return hashlib.sha256(file_bytes).hexdigest()

def compute_phash(file_bytes: bytes) -> Optional[str]:
    """Compute perceptual hash using imagehash (if available)."""
    if not imagehash or not Image:
        return None
    try:
        with Image.open(io.BytesIO(file_bytes)) as img:
            ph = imagehash.phash(img)
            return str(ph)
    except Exception as e:
        logger.debug(f'phash error: {e}')
        return None

def compute_ocr_fingerprint(file_bytes: bytes) -> Optional[str]:
    """Extract text via OpenAI OCR (if key set) or pytesseract; return SHA256 of normalized text."""
    # Try OpenAI if configured
    openai_key = os.getenv('OPENAI_API_KEY')
    if openai_key:
        try:
            b64 = base64.b64encode(file_bytes).decode('ascii')
            payload = {
                'model': 'gpt-4o-mini-vision',
                'messages': [
                    {
                        'role': 'user',
                        'content': [
                            {'type': 'text', 'text': 'Extract all text from the image. Return only plain text.'},
                            {'type': 'image_url', 'image_url': {'url': f'data:image;base64,{b64}'}}
                        ]
                    }
                ]
            }
            headers = {'Authorization': f'Bearer {openai_key}', 'Content-Type': 'application/json'}
            resp = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, json=payload, timeout=60)
            if resp.status_code == 200:
                j = resp.json()
                text = ''
                for choice in j.get('choices', []):
                    if choice.get('message', {}).get('content'):
                        text += choice['message']['content']
                if text:
                    norm = ''.join(ch for ch in text.lower() if ch.isalnum())
                    return hashlib.sha256(norm.encode('utf-8')).hexdigest()
        except Exception as e:
            logger.debug(f'OpenAI OCR failed: {e}')
    
    # Fallback to pytesseract
    if pytesseract and Image:
        try:
            with Image.open(io.BytesIO(file_bytes)) as img:
                text = pytesseract.image_to_string(img)
                if text:
                    norm = ''.join(ch for ch in text.lower() if ch.isalnum())
                    return hashlib.sha256(norm.encode('utf-8')).hexdigest()
        except Exception as e:
            logger.debug(f'pytesseract OCR failed: {e}')
    
    return None

def is_duplicate_and_record(file_bytes: bytes, user_id: int = None, user_name: str = None) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Check duplicates via backend (PostgreSQL 24/7).
    No local SQLite cache - backend is authoritative and always available.
    Returns (is_dup, reason_dict) with original user info if duplicate found.
    """
    sha = compute_sha256(file_bytes)
    
    # Check backend first (single source of truth)
    try:
        logger.debug(f'🔍 [BACKEND] Checking for duplicate: {sha[:16]}...')
        resp = requests.get(
            f'{BACKEND_URL}/telegram/check-duplicate/{sha}',
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get('is_duplicate'):
                original = data.get('original', {})
                logger.info(f'🔁 [BACKEND] Duplicate found: {original.get("user_name")} (ID: {original.get("user_id")})')
                return True, {
                    'method': data.get('method', 'sha256'),
                    'original_user_id': original.get('user_id'),
                    'original_user_name': original.get('user_name')
                }
        logger.debug(f'✅ [BACKEND] No duplicate found')
    except Exception as e:
        logger.error(f'❌ [BACKEND CHECK FAILED] {e}')
        # Don't block - continue to record anyway
    
    # Record fingerprint to backend (for future duplicate detection)
    try:
        logger.debug(f'📤 [BACKEND] Recording new fingerprint...')
        ocr_hash = compute_ocr_fingerprint(file_bytes)
        phash = compute_phash(file_bytes)
        
        payload = {
            'sha256': sha,
            'ocr_hash': ocr_hash,
            'phash': phash,
            'user_id': user_id,
            'user_name': user_name,
            'timestamp': int(time.time())
        }
        
        resp = requests.post(
            f'{BACKEND_URL}/telegram/record-fingerprint',
            json=payload,
            timeout=10
        )
        if resp.status_code == 201:
            logger.debug(f'✅ [BACKEND] Fingerprint recorded successfully')
        else:
            logger.debug(f'⚠️ [BACKEND] Fingerprint record returned {resp.status_code}')
    except Exception as e:
        logger.debug(f'⚠️ [BACKEND RECORD FAILED] {e}')
    
    return False, None

# ============================================================================
# TELEGRAM HELPERS
# ============================================================================

def send_message(chat_id: int, text: str, parse_mode: str = 'Markdown') -> Optional[Dict]:
    """Send text message."""
    try:
        resp = requests.post(
            f'{TELEGRAM_API}/sendMessage',
            json={'chat_id': chat_id, 'text': text, 'parse_mode': parse_mode},
            timeout=10
        )
        return resp.json() if resp.status_code == 200 else None
    except Exception as e:
        logger.error(f'send_message error: {e}')
        return None

def reply_to_message(chat_id: int, message_id: int, text: str, parse_mode: str = 'Markdown') -> Optional[Dict]:
    """Send reply to a message."""
    try:
        logger.debug(f'📤 Sending reply to message {message_id} in chat {chat_id}')
        resp = requests.post(
            f'{TELEGRAM_API}/sendMessage',
            json={'chat_id': chat_id, 'reply_to_message_id': message_id, 'text': text, 'parse_mode': parse_mode},
            timeout=10
        )
        if resp.status_code == 200:
            logger.info(f'✅ Reply sent: {text[:50]}...')
            return resp.json()
        else:
            logger.error(f'❌ Failed to send reply: status={resp.status_code}, response={resp.text[:100]}')
            return None
    except Exception as e:
        logger.error(f'reply_to_message error: {e}')
        return None

def set_reaction(chat_id: int, message_id: int, emoji: str = '👍') -> bool:
    """Set reaction emoji on message."""
    try:
        payload = {
            'chat_id': chat_id,
            'message_id': message_id,
            'reaction': [{'type': 'emoji', 'emoji': emoji}]
        }
        resp = requests.post(f'{TELEGRAM_API}/setMessageReaction', json=payload, timeout=10)
        if resp.status_code == 400:
            # Fallback: try simple string
            payload['reaction'] = emoji
            resp = requests.post(f'{TELEGRAM_API}/setMessageReaction', json=payload, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        logger.debug(f'set_reaction error: {e}')
        return False

def download_file(file_id: str) -> Optional[bytes]:
    """Download file from Telegram."""
    try:
        resp = requests.get(f'{TELEGRAM_API}/getFile', params={'file_id': file_id}, timeout=10)
        if resp.status_code != 200:
            return None
        
        file_info = resp.json()
        if not file_info.get('ok'):
            return None
        
        file_path = file_info['result']['file_path']
        file_url = f'https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}'
        file_resp = requests.get(file_url, timeout=30)
        return file_resp.content if file_resp.status_code == 200 else None
    except Exception as e:
        logger.error(f'download_file error: {e}')
        return None

# ============================================================================
# UPLOAD HELPERS
# ============================================================================

def upload_to_backend(file_bytes: bytes, filename: str, user_id: int, user_name: str) -> Dict[str, Any]:
    """Upload file to backend with fingerprints."""
    try:
        logger.info(f'[UPLOAD] {filename} ({len(file_bytes)} bytes) for user_id={user_id}')
        
        # Compute fingerprints
        try:
            sha = compute_sha256(file_bytes)
        except Exception:
            sha = None
        try:
            ocr = compute_ocr_fingerprint(file_bytes)
        except Exception:
            ocr = None
        try:
            ph = compute_phash(file_bytes)
        except Exception:
            ph = None
        
        files = {'files': (filename, io.BytesIO(file_bytes))}
        data = {
            'telegram_user_id': str(user_id),
            'telegram_user_name': user_name,
            'sha256': sha,
            'ocr_hash': ocr,
            'phash': ph
        }
        
        resp = requests.post(f'{BACKEND_URL}/telegram/upload', files=files, data=data, timeout=120)
        logger.info(f'[UPLOAD] response status={resp.status_code}')
        
        result = resp.json() if resp.status_code == 200 else {'success': False, 'error': resp.text}
        if isinstance(result, list) and len(result) == 2:
            result = result[0]
        
        logger.debug(f'[UPLOAD] result: {str(result)[:200]}')
        return result
    except Exception as e:
        logger.error(f'[UPLOAD] error: {e}\n{traceback.format_exc()}')
        return {'success': False, 'error': str(e)}

def upload_multiple_to_backend(files_list: List[Tuple[bytes, str]], user_id: int, user_name: str) -> Dict[str, Any]:
    """Upload multiple files in one request."""
    try:
        logger.info(f'[UPLOAD_MULTIPLE] {len(files_list)} files for user_id={user_id}')
        
        files = []
        sha256s, ocr_hashes, phashes = [], [], []
        
        for fb, fname in files_list:
            files.append(('files', (fname, io.BytesIO(fb))))
            try:
                sha256s.append(compute_sha256(fb))
            except Exception:
                sha256s.append(None)
            try:
                ocr_hashes.append(compute_ocr_fingerprint(fb))
            except Exception:
                ocr_hashes.append(None)
            try:
                phashes.append(compute_phash(fb))
            except Exception:
                phashes.append(None)
        
        data = {
            'telegram_user_id': str(user_id),
            'telegram_user_name': user_name,
            'sha256s': json.dumps(sha256s),
            'ocr_hashes': json.dumps(ocr_hashes),
            'phashes': json.dumps(phashes)
        }
        
        resp = requests.post(f'{BACKEND_URL}/telegram/upload', files=files, data=data, timeout=180)
        logger.info(f'[UPLOAD_MULTIPLE] response status={resp.status_code}')
        
        result = resp.json() if resp.status_code == 200 else {'success': False, 'error': resp.text}
        if isinstance(result, list) and len(result) == 2:
            result = result[0]
        
        logger.debug(f'[UPLOAD_MULTIPLE] result: {str(result)[:200]}')
        return result
    except Exception as e:
        logger.error(f'[UPLOAD_MULTIPLE] error: {e}\n{traceback.format_exc()}')
        return {'success': False, 'error': str(e)}

# ============================================================================
# MESSAGE HANDLERS
# ============================================================================

media_group_buffer = {}
media_group_lock = threading.Lock()

def handle_start(chat_id: int, user_id: int, first_name: str, is_group: bool):
    """Handle /start command."""
    if is_group:
        logger.info(f'✅ /start in group by {first_name} (ID={user_id})')
        return
    
    welcome = (
        f'👋 Bem-vindo ao Fluxo-Cash Bot!\n\n'
        f'🆔 Seu ID: `{user_id}`\n'
        f'(Este é seu identificador no sistema)\n\n'
        f'📋 Como usar:\n'
        f'1. Envie uma foto ou PDF de um comprovante PIX\n'
        f'2. O bot extrairá os dados automaticamente\n'
        f'3. Seu crédito será atualizado em segundos\n\n'
        f'Use /help para mais informações.'
    )
    send_message(chat_id, welcome)
    logger.info(f'✅ /start in private from {first_name} (ID={user_id})')

def handle_help(chat_id: int):
    """Handle /help command."""
    help_text = (
        '📚 Ajuda - Fluxo-Cash Bot\n\n'
        '**Comandos disponíveis:**\n'
        '/start - Iniciar\n'
        '/help - Esta mensagem\n'
        '/id - Ver seu ID\n\n'
        '**Para enviar comprovante:**\n'
        'Envie uma foto ou PDF do comprovante PIX\n\n'
        '**Dica:** Fotos claras funcionam melhor!'
    )
    send_message(chat_id, help_text)

def handle_id(chat_id: int, user_id: int, first_name: str):
    """Handle /id command."""
    id_text = f'🆔 Seu ID no Fluxo-Cash\n\n**ID Telegram:** `{user_id}`\n**Nome:** {first_name}\n\nEste é seu identificador único.'
    send_message(chat_id, id_text)
    logger.info(f'✅ /id from {first_name} (ID={user_id})')

def is_client_id_not_found_error(error_msg: str) -> bool:
    """Check if error is related to client ID not found."""
    if not error_msg:
        return False
    lower_msg = error_msg.lower()
    return ('client' in lower_msg and 'nao encontrado' in lower_msg) or \
           ('cliente' in lower_msg and 'nao encontrado' in lower_msg) or \
           ('cliente' in lower_msg and 'not found' in lower_msg) or \
           ('whitelist' in lower_msg)

def handle_photo(chat_id: int, message_id: int, user_id: int, first_name: str, photo: List, is_group: bool):
    """Handle photo upload."""
    set_reaction(chat_id, message_id, '⏳')
    
    try:
        # Download
        file_id = photo[-1]['file_id']
        file_bytes = download_file(file_id)
        
        if not file_bytes:
            set_reaction(chat_id, message_id, '❌')
            logger.error(f'Failed to download photo from {user_id}')
            return
        
        logger.info(f'📸 Photo from user_id={user_id} ({first_name}), group={is_group}')
        
        # Check duplicate
        is_dup, dup_info = is_duplicate_and_record(file_bytes, user_id, first_name)
        if is_dup:
            orig_uid = dup_info.get('original_user_id')
            orig_uname = dup_info.get('original_user_name', 'Desconhecido')
            logger.info(f'🔁 Duplicate detected (method={dup_info.get("method")}): originally from user {orig_uid} ({orig_uname})')
            set_reaction(chat_id, message_id, '🔁')
            reply_to_message(chat_id, message_id, f'🔁 Este comprovante já foi enviado por **{orig_uname}** (ID: {orig_uid}) anteriormente.')
            return
        
        # Upload
        response = upload_to_backend(file_bytes, f'comprovante_{user_id}_{int(time.time())}.jpg', user_id, first_name)
        
        # Handle response
        processed = response.get('processed', [])
        failed = response.get('failed', [])
        
        logger.debug(f'Response: processed={len(processed)}, failed={len(failed)}')
        
        # If at least one succeeded
        if len(processed) > 0 and len(failed) == 0:
            logger.info(f'✅ All files accepted')
            set_reaction(chat_id, message_id, '✅')
            for item in processed:
                value = item.get('value', 0)
                logger.info(f"✅ Accepted: user_id={user_id}, R$ {value:.2f}")
                reply_to_message(chat_id, message_id, f'✅ **Comprovante processado com sucesso!**\n\n💵 Valor creditado: R$ {value:.2f}')
        # If mixed (some succeeded, some failed)
        elif len(processed) > 0 and len(failed) > 0:
            logger.info(f'⚠️ Partial success: {len(processed)} ok, {len(failed)} failed')
            set_reaction(chat_id, message_id, '⚠️')
            for item in processed:
                value = item.get('value', 0)
                reply_to_message(chat_id, message_id, f'✅ **Processado!** 💵 R$ {value:.2f}')
            for f in failed:
                ferr = f.get('error') or f.get('reason') or 'Unknown error'
                if is_client_id_not_found_error(ferr):
                    set_reaction(chat_id, message_id, '🚫')
                    reply_to_message(chat_id, message_id, f'🚫 **Cliente não encontrado na whitelist**\n\nID do cliente: `{user_id}`\n\nPor favor, contate um administrador do sistema ou realize o cadastro do cliente.')
                    logger.warning(f'🚫 Client ID not found: user_id={user_id}')
                else:
                    logger.warning(f'⚠️ Partial fail: {ferr}')
                    reply_to_message(chat_id, message_id, f'⚠️ {ferr}')
        # All failed
        else:
            logger.warning(f'❌ All files rejected')
            error_msg = response.get('detail') or response.get('error') or 'Processing error'
            if len(failed) > 0:
                error_msg = failed[0].get('error', 'Processing error')
            
            if is_client_id_not_found_error(error_msg):
                set_reaction(chat_id, message_id, '🚫')
                reply_to_message(chat_id, message_id, f'🚫 **Cliente não encontrado na whitelist**\n\nID do cliente: `{user_id}`\n\nPor favor, contate um administrador do sistema ou realize o cadastro do cliente.')
                logger.warning(f'🚫 Client ID not found: user_id={user_id}')
            else:
                set_reaction(chat_id, message_id, '❌')
                reply_to_message(chat_id, message_id, f'❌ {error_msg}')
                logger.warning(f'❌ Error: {error_msg}')
    
    except Exception as e:
        set_reaction(chat_id, message_id, '❌')
        logger.error(f'handle_photo error: {e}\n{traceback.format_exc()}')

def handle_document(chat_id: int, message_id: int, user_id: int, first_name: str, document: Dict, is_group: bool):
    """Handle PDF document upload."""
    set_reaction(chat_id, message_id, '⏳')
    
    try:
        # Download
        file_id = document['file_id']
        file_bytes = download_file(file_id)
        
        if not file_bytes:
            set_reaction(chat_id, message_id, '❌')
            logger.error(f'Failed to download PDF from {user_id}')
            return
        
        logger.info(f'📄 PDF from user_id={user_id} ({first_name}), group={is_group}')
        
        # Check duplicate
        is_dup, dup_info = is_duplicate_and_record(file_bytes, user_id, first_name)
        if is_dup:
            orig_uid = dup_info.get('original_user_id')
            orig_uname = dup_info.get('original_user_name', 'Desconhecido')
            logger.info(f'🔁 Duplicate detected (method={dup_info.get("method")}): originally from user {orig_uid} ({orig_uname})')
            set_reaction(chat_id, message_id, '🔁')
            reply_to_message(chat_id, message_id, f'🔁 Este comprovante já foi enviado por **{orig_uname}** (ID: {orig_uid}) anteriormente.')
            return
        
        # Upload
        response = upload_to_backend(file_bytes, document.get('file_name', 'documento.pdf'), user_id, first_name)
        
        # Handle response (same logic as photo)
        processed = response.get('processed', [])
        failed = response.get('failed', [])
        
        logger.debug(f'Response: processed={len(processed)}, failed={len(failed)}')
        
        # If at least one succeeded
        if len(processed) > 0 and len(failed) == 0:
            logger.info(f'✅ All files accepted')
            set_reaction(chat_id, message_id, '✅')
            for item in processed:
                value = item.get('value', 0)
                logger.info(f"✅ Accepted: user_id={user_id}, R$ {value:.2f}")
                reply_to_message(chat_id, message_id, f'✅ **Comprovante processado com sucesso!**\n\n💵 Valor creditado: R$ {value:.2f}')
        # If mixed (some succeeded, some failed)
        elif len(processed) > 0 and len(failed) > 0:
            logger.info(f'⚠️ Partial success: {len(processed)} ok, {len(failed)} failed')
            set_reaction(chat_id, message_id, '⚠️')
            for item in processed:
                value = item.get('value', 0)
                reply_to_message(chat_id, message_id, f'✅ **Processado!** 💵 R$ {value:.2f}')
            for f in failed:
                ferr = f.get('error') or f.get('reason') or 'Unknown error'
                if is_client_id_not_found_error(ferr):
                    set_reaction(chat_id, message_id, '🚫')
                    reply_to_message(chat_id, message_id, f'🚫 **Cliente não encontrado na whitelist**\n\nID do cliente: `{user_id}`\n\nPor favor, contate um administrador do sistema ou realize o cadastro do cliente.')
                    logger.warning(f'🚫 Client ID not found: user_id={user_id}')
                else:
                    logger.warning(f'⚠️ Partial fail: {ferr}')
                    reply_to_message(chat_id, message_id, f'⚠️ {ferr}')
        # All failed
        else:
            logger.warning(f'❌ All files rejected')
            error_msg = response.get('detail') or response.get('error') or 'Processing error'
            if len(failed) > 0:
                error_msg = failed[0].get('error', 'Processing error')
            
            if is_client_id_not_found_error(error_msg):
                set_reaction(chat_id, message_id, '🚫')
                reply_to_message(chat_id, message_id, f'🚫 **Cliente não encontrado na whitelist**\n\nID do cliente: `{user_id}`\n\nPor favor, contate um administrador do sistema ou realize o cadastro do cliente.')
                logger.warning(f'🚫 Client ID not found: user_id={user_id}')
            else:
                set_reaction(chat_id, message_id, '❌')
                reply_to_message(chat_id, message_id, f'❌ {error_msg}')
                logger.warning(f'❌ Error: {error_msg}')
    
    except Exception as e:
        set_reaction(chat_id, message_id, '❌')
        logger.error(f'handle_document error: {e}\n{traceback.format_exc()}')

# ============================================================================
# POLLING & UPDATE PROCESSING
# ============================================================================

last_update_id = None

def get_updates(timeout: int = 30) -> List[Dict]:
    """Poll for updates."""
    global last_update_id
    try:
        resp = requests.get(
            f'{TELEGRAM_API}/getUpdates',
            params={'offset': last_update_id, 'timeout': timeout, 'allowed_updates': ['message']},
            timeout=timeout + 5
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get('ok'):
                return data.get('result', [])
    except Exception as e:
        logger.error(f'get_updates error: {e}')
    
    return []

def process_update(update: Dict):
    """Process single update."""
    global last_update_id
    
    update_id = update.get('update_id')
    last_update_id = update_id + 1
    
    message = update.get('message')
    if not message:
        return
    
    chat_id = message.get('chat', {}).get('id')
    chat_type = message.get('chat', {}).get('type', 'private')
    user_id = message.get('from', {}).get('id')
    first_name = message.get('from', {}).get('first_name', 'User')
    message_id = message.get('message_id')
    
    if not first_name or first_name == 'Group':
        username = message.get('from', {}).get('username')
        first_name = username or f'User_{user_id}'
    
    is_group = chat_type in ['group', 'supergroup']
    
    if not all([chat_id, user_id]):
        return
    
    # Process text commands
    text = message.get('text', '').strip()
    
    if text.startswith('/start'):
        handle_start(chat_id, user_id, first_name, is_group)
    elif text.startswith('/help'):
        handle_help(chat_id)
    elif text.startswith('/id'):
        handle_id(chat_id, user_id, first_name)
    
    # Process photo (in background thread to avoid blocking polling)
    if 'photo' in message:
        photo = message.get('photo')
        t = threading.Thread(target=handle_photo, args=(chat_id, message_id, user_id, first_name, photo, is_group), daemon=True)
        t.start()
    
    # Process document (in background thread to avoid blocking polling)
    elif 'document' in message:
        document = message.get('document')
        if document.get('mime_type') == 'application/pdf':
            t = threading.Thread(target=handle_document, args=(chat_id, message_id, user_id, first_name, document, is_group), daemon=True)
            t.start()
        else:
            logger.warning(f'Non-PDF document ignored: {document.get("mime_type")}')

# ============================================================================
# MAIN LOOP
# ============================================================================

def main():
    """Main polling loop."""
    logger.info('=' * 70)
    logger.info('🤖 TELEGRAM BOT - FLUXO CASH v3 (Refeito)')
    logger.info('=' * 70)
    logger.info(f'Token: {TELEGRAM_TOKEN[:20]}...')
    logger.info(f'Backend: {BACKEND_URL}')
    logger.info(f'pHash threshold: {PHASH_THRESHOLD}')
    logger.info(f'Log file: {BOT_LOG_FILE}')
    logger.info('=' * 70)
    
    # Test connection
    try:
        resp = requests.get(f'{TELEGRAM_API}/getMe', timeout=5)
        if resp.status_code == 200:
            bot_info = resp.json()
            if bot_info.get('ok'):
                bot_name = bot_info['result'].get('username', 'Bot')
                logger.info(f'✅ Connected: @{bot_name}')
    except Exception as e:
        logger.error(f'❌ Connection failed: {e}')
        return
    
    logger.info('✅ Bot ready! Waiting for messages...\n')
    
    # Polling loop
    try:
        while True:
            try:
                updates = get_updates(timeout=30)
                
                for update in updates:
                    try:
                        process_update(update)
                    except Exception as e:
                        logger.error(f'Update processing error: {e}\n{traceback.format_exc()}')
                
                if not updates:
                    logger.debug('No new updates.')
                    
            except Exception as e:
                logger.error(f'Polling error: {e}')
                time.sleep(1)
    
    except KeyboardInterrupt:
        logger.info('\n✅ Bot stopped by user.')

if __name__ == '__main__':
    main()
