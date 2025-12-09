# 🤖 Fluxo Cash - Bot Deploy Script

Este script cria um novo repositório no GitHub apenas com o código do bot.

## 📦 O que está incluído:

- ✅ `run_bot.py` - Script principal
- ✅ `app/telegram_bot_simple.py` - Lógica do bot
- ✅ `app/telegram_webhook.py` - Webhook handler
- ✅ `app/extractors.py` - Extração de dados
- ✅ `app/pdf_extractor.py` - Processamento de PDFs
- ✅ `app/pix_utils.py` - Utilitários PIX
- ✅ `requirements.txt` - Dependências Python
- ✅ `.gitignore` - Arquivos ignorados
- ✅ `README.md` - Documentação completa

## 🚀 Passos para fazer o commit:

### 1️⃣ Inicializar Git
```powershell
cd "c:\Users\jvbar\OneDrive\Área de Trabalho\New-bot-nader-main\bot-repository"
git init
git add .
git commit -m "🤖 Initial commit: Fluxo Cash Telegram Bot"
```

### 2️⃣ Criar repositório no GitHub

**Opção A - Via GitHub Web:**
1. Acesse: https://github.com/new
2. Nome: `fluxo-cash-bot` (ou outro nome)
3. Descrição: "Telegram bot para processamento de comprovantes PIX"
4. ⚠️ **NÃO marque** "Add a README file"
5. Clique em "Create repository"

**Opção B - Via GitHub CLI (se tiver instalado):**
```powershell
gh repo create fluxo-cash-bot --public --source=. --remote=origin --push
```

### 3️⃣ Conectar e fazer push

Depois de criar o repositório no GitHub, use os comandos que aparecerão na tela:

```powershell
git remote add origin https://github.com/SEU_USUARIO/fluxo-cash-bot.git
git branch -M main
git push -u origin main
```

**Substitua `SEU_USUARIO` pelo seu username do GitHub!**

---

## 🎯 Deploy no Render

Depois do push:

1. **Render.com** → "New" → "Web Service"
2. **Connect Repository**: Selecione `fluxo-cash-bot`
3. **Configuração**:
   - Name: `fluxo-cash-bot`
   - Environment: `Python 3`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python run_bot.py`
4. **Environment Variables** (copie do Railway):
   - `TELEGRAM_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `BACKEND_URL`
   - `OPENAI_API_KEY` (opcional)

---

## ✅ Comandos Completos (copie e cole):

```powershell
# 1. Inicializar repositório
cd "c:\Users\jvbar\OneDrive\Área de Trabalho\New-bot-nader-main\bot-repository"
git init
git add .
git commit -m "🤖 Initial commit: Fluxo Cash Telegram Bot"

# 2. Depois de criar o repositório no GitHub, execute:
# (substitua SEU_USUARIO pelo seu username)
git remote add origin https://github.com/SEU_USUARIO/fluxo-cash-bot.git
git branch -M main
git push -u origin main
```

---

## 🔐 Importante - Variáveis de Ambiente

⚠️ **NÃO commite o arquivo `.env` com dados reais!**

O `.gitignore` já está configurado para ignorar `.env`, mas certifique-se de **nunca** adicionar credenciais ao Git.

Para o Render, adicione as variáveis manualmente no dashboard.

---

## 📞 Problemas?

- **Erro de autenticação Git**: Configure seu token GitHub ou SSH key
- **Repositório já existe**: Use `git remote set-url origin https://...` para mudar a URL
- **Push rejeitado**: Use `git pull origin main --allow-unrelated-histories` primeiro

---

Pronto! Seu bot estará em um repositório separado e pronto para deploy! 🚀
