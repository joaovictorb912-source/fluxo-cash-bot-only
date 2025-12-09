# OpenAI Extractor
import os
import json
import base64
import logging
import time
from pathlib import Path
from typing import Dict
from PIL import Image
import io
from dotenv import load_dotenv

# Carregar variáveis de ambiente do .env (apenas se existir localmente)
env_path = Path(__file__).parent.parent / '.env'
if env_path.exists():
    load_dotenv(dotenv_path=env_path)

try:
    from openai import OpenAI
    api_key = os.getenv("OPENAI_API_KEY")
    client = OpenAI(api_key=api_key) if api_key else None
    if api_key:
        logger_temp = logging.getLogger(__name__)
        logger_temp.info(f"✅ OpenAI configurado (key: {api_key[:20]}...)")
except Exception as e:
    client = None
    logger_temp = logging.getLogger(__name__)
    logger_temp.warning(f"⚠️ OpenAI não configurado: {e}")

# Try to import PDF libraries
try:
    from pdf2image import convert_from_path
    PDF_SUPPORT = True
except:
    PDF_SUPPORT = False

try:
    import pdfplumber
    PDF_TEXT_SUPPORT = True
except:
    PDF_TEXT_SUPPORT = False

logger = logging.getLogger(__name__)

# Rate limiting: adicionar delay entre chamadas para evitar 429
last_openai_call_time = 0
MIN_CALL_INTERVAL = 5.0  # 5 segundos entre chamadas = ~12 chamadas/minuto (reduz rate limit 429s)

# Importar extrator de PDF por texto
try:
    from pdf_extractor import extract_from_pdf_text
except:
    def extract_from_pdf_text(file_path):
        return None

def encode_image(fp: str) -> str:
    with open(fp, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')

def pdf_to_image(pdf_path: str) -> str:
    """Converte a primeira página de um PDF em imagem JPEG temporária"""
    if not PDF_SUPPORT:
        raise Exception("pdf2image não instalado. Execute: pip install pdf2image")
    
    try:
        # Converter primeira página do PDF
        images = convert_from_path(pdf_path, first_page=1, last_page=1, dpi=200)
        
        if not images:
            raise Exception("Não foi possível converter PDF")
        
        # Salvar como JPEG temporário
        temp_path = pdf_path.replace('.pdf', '_temp.jpg')
        images[0].save(temp_path, 'JPEG', quality=95)
        
        logger.info(f"📄 PDF convertido para imagem: {temp_path}")
        return temp_path
        
    except Exception as e:
        logger.error(f"Erro ao converter PDF: {e}")
        raise

def extract_proof_data(file_path: str) -> Dict:
    global last_openai_call_time
    
    if not client:
        return {'value': None, 'sender_pix_key': None, 'receiver_pix_key': None, 'success': False, 'error': 'OpenAI not configured'}
    
    # OTIMIZAÇÃO: Para PDFs, tentar extrair texto primeiro (GRÁTIS!)
    ext = Path(file_path).suffix.lower()
    if ext == '.pdf' and PDF_TEXT_SUPPORT:
        logger.info(f"🔍 Tentando extrair texto do PDF (sem OpenAI)...")
        pdf_data = extract_from_pdf_text(file_path)
        
        if pdf_data and pdf_data.get('success'):
            logger.info(f"✅ PDF processado localmente - ECONOMIA de 1 requisição OpenAI!")
            return pdf_data
        else:
            logger.info(f"⚠️ Extração de texto falhou, usando OpenAI Vision como fallback...")
    
    # Rate limiting: aguardar intervalo mínimo entre chamadas
    current_time = time.time()
    time_since_last_call = current_time - last_openai_call_time
    if time_since_last_call < MIN_CALL_INTERVAL:
        sleep_time = MIN_CALL_INTERVAL - time_since_last_call
        logger.info(f"⏳ Rate limiting: aguardando {sleep_time:.2f}s...")
        time.sleep(sleep_time)
    
    try:
        if ext not in ['.jpg', '.jpeg', '.png', '.pdf']:
            return {'value': None, 'sender_pix_key': None, 'receiver_pix_key': None, 'success': False, 'error': 'Unsupported file'}
        
        # Converter PDF para imagem se necessário
        temp_file = None
        if ext == '.pdf':
            if not PDF_SUPPORT:
                return {'value': None, 'sender_pix_key': None, 'receiver_pix_key': None, 'success': False, 'error': 'PDF não suportado. Instale: pip install pdf2image'}
            
            file_path = pdf_to_image(file_path)
            temp_file = file_path  # Marcar para deletar depois
            ext = '.jpg'
        
        b64 = encode_image(file_path)
        mime = 'image/jpeg' if ext in ['.jpg', '.jpeg'] else 'image/png'
        
        prompt = """Analise este comprovante de transferência PIX e extraia as seguintes informações em formato JSON:

{
  "valor": 0.0,
  "chave_pix_remetente": "",
  "chave_pix_destinatario": "",
  "beneficiario": "",
  "endtoend": "",
  "data": "YYYY-MM-DD"
}

INSTRUÇÕES CRÍTICAS PARA EXTRAÇÃO:

1. VALOR (MUITO IMPORTANTE):
   - Leia o valor COMPLETO com todos os dígitos
   - Valores brasileiros usam ponto (.) para MILHAR e vírgula (,) para CENTAVOS
   - Exemplos:
     * "R$ 49.500,00" = 49500.00 (quarenta e nove mil e quinhentos reais)
     * "R$ 49,50" = 49.50 (quarenta e nove reais e cinquenta centavos)
     * "R$ 500.000,00" = 500000.00 (quinhentos mil reais)
     * "R$ 1.234,56" = 1234.56 (mil duzentos e trinta e quatro reais)
   - NUNCA ignore os dígitos antes do ponto
   - Se o valor tem formato "XX.XXX,XX" retorne o número COMPLETO

2. CHAVE PIX DESTINATÁRIO (FAVORECIDO/RECEBEDOR):
   ⚠️ **ATENÇÃO CRÍTICA**: A chave PIX DEVE estar explicitamente identificada no comprovante!
   
   - Procure APENAS em campos rotulados como:
     * "Chave PIX"
     * "Chave Pix"
     * "Chave"
     * "PIX Key"
     * Próximo ao texto "Chave:" ou "Chave PIX:"
   
   - **NÃO CONFUNDA** com outros campos:
     * ❌ CPF/CNPJ do beneficiário (geralmente aparece como "CPF:", "CNPJ:", "Documento:")
     * ❌ Número de conta bancária
     * ❌ Agência bancária
     * ❌ Código do banco
   
   - A chave PIX pode ser:
     * Chave aleatória (UUID): 88d663a9-3c79-48c8-8b86-16d583c553c3
     * CNPJ: 62.648.338/0001-01 (SOMENTE se estiver no campo "Chave PIX")
     * CPF: 123.456.789-00 (SOMENTE se estiver no campo "Chave PIX")
     * Email: email@exemplo.com
     * Telefone: +5511999999999
   
   - **REGRA DE OURO**: Se você não vê explicitamente escrito "Chave PIX" ou "Chave" próximo ao valor, deixe o campo VAZIO ("")
   - SEMPRE retorne a chave completa sem modificações

3. CHAVE PIX REMETENTE (PAGADOR/ORIGEM):
   - Procure em: "Pagador", "Origem", "De", "Remetente"
   - Mesmos formatos da chave destinatário

4. BENEFICIÁRIO: Nome completo de quem recebeu o PIX

5. ENDTOEND: Código da transação (formato: E + 32 dígitos)

6. DATA: Formato YYYY-MM-DD

ATENÇÃO ESPECIAL:
- Se ver "62.648.338/0001-01", retorne EXATAMENTE assim (não simplifique)
- Se ver "88d663a9-3c79-48c8-8b86-16d583c553c3", retorne EXATAMENTE assim
- Não omita zeros à esquerda em CNPJs/CPFs
- Retorne APENAS o JSON válido, sem markdown ou explicações"""
        
        # Atualizar timestamp antes da chamada
        last_openai_call_time = time.time()
        
        resp = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[{'role':'user','content':[
                {'type':'text','text': prompt},
                {'type':'image_url','image_url':{'url':f'data:{mime};base64,{b64}'}}
            ]}],
            max_tokens=500,
            temperature=0.1
        )
        
        raw = resp.choices[0].message.content.strip()
        if '```' in raw:
            raw = raw.split('```')[1].replace('json','').strip()
        
        r = json.loads(raw)
        v = r.get('valor') or r.get('value')
        if isinstance(v, str):
            # Remover R$ e espaços
            v = v.replace('R$','').strip()
            
            # Lógica de conversão do formato brasileiro:
            # 49.850,00 -> 49850.00 (valor com centavos)
            # 49.850 -> 49850.00 (valor sem centavos)
            # 49,85 -> 49.85 (valor pequeno com centavos)
            
            if ',' in v:
                # Tem vírgula = formato brasileiro com centavos
                # Remove pontos (separadores de milhar) e troca vírgula por ponto
                v = v.replace('.', '').replace(',', '.')
            else:
                # Não tem vírgula, só ponto
                # Verificar se é separador de milhar ou decimal
                parts = v.split('.')
                if len(parts) == 2 and len(parts[1]) <= 2:
                    # Tem ponto com 1-2 dígitos após = decimal (formato americano)
                    # Ex: 49.85 -> manter como está
                    pass
                else:
                    # Tem ponto com 3+ dígitos = separador de milhar
                    # Ex: 49.850 -> remover ponto
                    v = v.replace('.', '')
            
            v = float(v or 0)
        elif v is None:
            v = 0
        
        # Deletar arquivo temporário se foi criado
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
                logger.info(f"🗑️ Arquivo temporário removido: {temp_file}")
            except:
                pass
        
        return {
            'value': v,
            'sender_pix_key': r.get('chave_pix_remetente'),
            'receiver_pix_key': r.get('chave_pix_destinatario'),
            'beneficiary': r.get('beneficiario'),
            'endtoend': r.get('endtoend'),
            'date': r.get('data'),
            'confidence': 0.95 if v else 0.5,
            'success': bool(v and v > 0),
            'error': None
        }
    except Exception as e:
        logger.error(f'OpenAI error: {e}')
        
        # Limpar arquivo temporário em caso de erro
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass
        
        return {'value': None, 'sender_pix_key': None, 'receiver_pix_key': None, 'success': False, 'error': str(e)}
