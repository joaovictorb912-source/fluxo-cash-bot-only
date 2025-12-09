"""
Fluxo Cash - Telegram Bot Runner
Script principal para iniciar o bot
"""

import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

# Adicionar diretório app ao path
sys.path.insert(0, str(Path(__file__).parent))

# Carregar variáveis de ambiente
load_dotenv()

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

def main():
    """Inicia o bot Telegram"""
    
    # Verificar variáveis obrigatórias
    telegram_token = os.getenv('TELEGRAM_TOKEN')
    backend_url = os.getenv('BACKEND_URL', 'https://new-bot-nader-production.up.railway.app')
    
    if not telegram_token:
        logger.error("❌ TELEGRAM_TOKEN não configurado!")
        logger.error("Configure no arquivo .env ou nas variáveis de ambiente")
        sys.exit(1)
    
    logger.info("🚀 Iniciando Fluxo Cash Telegram Bot...")
    logger.info(f"📡 Backend URL: {backend_url}")
    
    # Importar e iniciar o bot
    try:
        from app.telegram_bot_simple import main as bot_main
        bot_main()
    except KeyboardInterrupt:
        logger.info("\n👋 Bot encerrado pelo usuário")
    except Exception as e:
        logger.error(f"❌ Erro ao iniciar bot: {e}", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    main()
