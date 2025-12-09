# Fluxo Cash - Telegram Bot

Bot do Telegram para processamento de comprovantes de pagamento PIX com integração ao Google Sheets.

## 🚀 Funcionalidades

- ✅ Recebe comprovantes PIX via Telegram
- ✅ Detecta duplicatas (SHA256, OCR, pHash)
- ✅ Valida usuários autorizados
- ✅ Envia para backend (Railway) para processamento
- ✅ Registra transações no Google Sheets automaticamente
- ✅ Suporte a media groups
- ✅ Reactions automáticas (✅ sucesso, ❌ erro)

## 📋 Requisitos

- Python 3.9+
- Conta no Render (ou Railway/Heroku)
- Token do Telegram Bot
- Backend rodando (Railway)

## ⚙️ Configuração

### 1. Variáveis de Ambiente

Crie um arquivo `.env` ou configure no Render:

```env
# Telegram Bot
TELEGRAM_TOKEN=seu_token_aqui
TELEGRAM_CHAT_ID=seu_chat_id_aqui

# Backend URL
BACKEND_URL=https://seu-backend.up.railway.app

# OpenAI (opcional, para OCR avançado)
OPENAI_API_KEY=sk-...

# Detecção de Duplicatas
PHASH_THRESHOLD=5
```

### 2. Instalação Local

```bash
pip install -r requirements.txt
python run_bot.py
```

### 3. Deploy no Render

1. **Conecte este repositório** ao Render
2. **Escolha**: Web Service (para webhook) ou Background Worker (para polling)
3. **Configuração**:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python run_bot.py`
4. **Adicione as variáveis de ambiente** acima

## 🏗️ Estrutura

```
bot-repository/
├── run_bot.py                 # Script principal
├── app/
│   ├── telegram_bot_simple.py # Lógica do bot (polling)
│   ├── telegram_webhook.py    # Webhook handler
│   ├── extractors.py          # Extração de dados de comprovantes
│   ├── pdf_extractor.py       # Processamento de PDFs
│   └── pix_utils.py           # Utilitários PIX
├── requirements.txt
├── .env.example
└── README.md
```

## 🔧 Como Funciona

1. **Usuário envia comprovante** no Telegram
2. **Bot recebe** e valida usuário autorizado
3. **Extração de dados**: valor, chave PIX, tipo de operação
4. **Verificação de duplicatas**: SHA256 hash, OCR, pHash
5. **Envia para backend**: POST /api/deposits ou /api/withdrawals
6. **Backend processa**: salva no PostgreSQL
7. **Google Sheets atualizado**: registro automático com formatação

## 🐛 Troubleshooting

### Bot não responde
- Verifique se `TELEGRAM_TOKEN` está correto
- Teste com `/start` no chat

### Comprovantes não são processados
- Verifique `BACKEND_URL`
- Confira logs: `tail -f bot.log`

### Duplicatas não detectadas
- Ajuste `PHASH_THRESHOLD` (padrão: 5)
- Verifique se PIL/imagehash estão instalados

## 📞 Suporte

Para problemas com:
- **Backend**: Verifique Railway logs
- **Google Sheets**: Verifique Service Account permissions
- **Bot**: Verifique variáveis de ambiente

## 📝 Licença

Uso privado - Fluxo Cash
