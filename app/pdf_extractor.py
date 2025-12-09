# Extração híbrida de PDFs
# Tenta extrair texto do PDF primeiro (rápido, grátis)
# Se falhar, usa OpenAI Vision (lento, pago)

import re
import logging
from typing import Dict, Optional
from datetime import datetime

try:
    import pdfplumber
    PDF_TEXT_SUPPORT = True
except:
    PDF_TEXT_SUPPORT = False

logger = logging.getLogger(__name__)

# Padrões regex para extração de dados de comprovantes PIX
PATTERNS = {
    'valor': [
        r'Valor[:\s]*R?\$?\s*([\d.,]+)',  # "Valor: R$ 49.500,00"
        r'R\$\s*([\d.,]+)',  # "R$ 49.500,00"
        r'(?:valor|quantia|total)[:\s]*R?\$?\s*([\d.,]+)',  # Variações
        r'Valor\s+da\s+transação[:\s]*R?\$?\s*([\d.,]+)',  # Específico
    ],
    'pix_remetente': [
        # UUID (chave aleatória) - prioridade alta
        r'(?:pagador|origem|de|remetente|quem\s+enviou).*?(?:chave|pix)[:\s]*([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})',
        r'(?:chave|pix)[:\s]*(?:pagador|origem|de|remetente).*?([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})',
        r'(?:pagador|origem|de|remetente).*?([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})',
        # CNPJ formatado (XX.XXX.XXX/XXXX-XX)
        r'(?:pagador|origem|de|remetente).*?(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})',
        # CNPJ sem formatação (14 dígitos)
        r'(?:pagador|origem|de|remetente).*?(\d{14})',
        # CPF (11 dígitos)
        r'(?:pagador|origem|de|remetente).*?(\d{11})',
        # Email
        r'(?:pagador|origem|de|remetente).*?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
        # Telefone
        r'(?:pagador|origem|de|remetente).*?(\+55\s*\d{2}\s*\d{4,5}[-\s]?\d{4})',
    ],
    'pix_destinatario': [
        # UUID (chave aleatória) - prioridade alta
        r'(?:favorecido|destinat[aá]rio|recebedor|para|benefici[aá]rio|quem\s+recebeu).*?(?:chave|pix)[:\s]*([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})',
        r'(?:chave|pix)[:\s]*(?:favorecido|destinat[aá]rio|recebedor|para|benefici[aá]rio).*?([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})',
        r'(?:favorecido|destinat[aá]rio|recebedor|para|benefici[aá]rio).*?([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})',
        # CNPJ formatado (XX.XXX.XXX/XXXX-XX)
        r'(?:favorecido|destinat[aá]rio|recebedor|para|benefici[aá]rio).*?(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})',
        # CNPJ sem formatação (14 dígitos) - captura números completos
        r'(?:favorecido|destinat[aá]rio|recebedor|para|benefici[aá]rio).*?(\d{14})',
        # CPF (11 dígitos)
        r'(?:favorecido|destinat[aá]rio|recebedor|para|benefici[aá]rio).*?(\d{11})',
        # Email
        r'(?:favorecido|destinat[aá]rio|recebedor|para|benefici[aá]rio).*?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
        # Telefone
        r'(?:favorecido|destinat[aá]rio|recebedor|para|benefici[aá]rio).*?(\+55\s*\d{2}\s*\d{4,5}[-\s]?\d{4})',
    ],
    'beneficiario': [
        r'(?:favorecido|benefici[aá]rio|nome)[:\s]+([A-ZÀ-Ú][A-ZÀ-Ú\s]{2,50})',
    ],
    'endtoend': [
        r'(E\d{32})',
        r'End\s*to\s*End[:\s]+(E\d{32})',
    ],
    'data': [
        r'(\d{2}[/-]\d{2}[/-]\d{4})',
        r'(\d{4}[-/]\d{2}[-/]\d{2})',
        r'Data[:\s]+(\d{2}[/-]\d{2}[/-]\d{4})',
    ]
}

def extract_from_pdf_text(pdf_path: str) -> Dict:
    """
    Tenta extrair dados diretamente do texto do PDF
    Retorna None se não conseguir extrair informações suficientes
    """
    if not PDF_TEXT_SUPPORT:
        return None
    
    try:
        text = ""
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
        
        if not text or len(text) < 50:
            logger.warning(f"📄 PDF sem texto extraível ou muito curto")
            return None
        
        logger.info(f"📄 Texto extraído do PDF ({len(text)} caracteres)")
        
        # Extrair dados usando regex
        data = {
            'value': None,
            'sender_pix_key': None,
            'receiver_pix_key': None,
            'beneficiary': None,
            'endtoend': None,
            'date': None,
            'method': 'pdf_text'
        }
        
        # Valor
        for pattern in PATTERNS['valor']:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                value_str = match.group(1).strip()
                
                # Lógica de conversão do formato brasileiro:
                # 49.850,00 -> 49850.00 (valor com centavos)
                # 49.850 -> 49850.00 (valor sem centavos)
                # 49,85 -> 49.85 (valor pequeno com centavos)
                
                if ',' in value_str:
                    # Tem vírgula = formato brasileiro com centavos
                    # Remove pontos (separadores de milhar) e troca vírgula por ponto
                    value_str = value_str.replace('.', '').replace(',', '.')
                else:
                    # Não tem vírgula, só ponto
                    # Verificar se é separador de milhar ou decimal
                    parts = value_str.split('.')
                    if len(parts) == 2 and len(parts[1]) <= 2:
                        # Tem ponto com 1-2 dígitos após = decimal (formato americano)
                        # Ex: 49.85 -> manter como está
                        pass
                    else:
                        # Tem ponto com 3+ dígitos = separador de milhar
                        # Ex: 49.850 -> remover ponto
                        value_str = value_str.replace('.', '')
                
                try:
                    data['value'] = float(value_str)
                    logger.info(f"💰 Valor encontrado: R$ {data['value']:.2f}")
                    break
                except Exception as e:
                    logger.warning(f"⚠️ Erro ao converter valor '{value_str}': {e}")
                    continue
        
        # PIX Remetente
        for pattern in PATTERNS['pix_remetente']:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                data['sender_pix_key'] = match.group(1).strip()
                logger.info(f"👤 PIX Remetente encontrado: {data['sender_pix_key']}")
                break
        
        if not data['sender_pix_key']:
            logger.warning(f"⚠️ PIX Remetente NÃO encontrado no texto")
        
        # PIX Destinatário
        for pattern in PATTERNS['pix_destinatario']:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                data['receiver_pix_key'] = match.group(1).strip()
                logger.info(f"🎯 PIX Destinatário encontrado: {data['receiver_pix_key']}")
                break
        
        if not data['receiver_pix_key']:
            logger.warning(f"⚠️ PIX Destinatário NÃO encontrado no texto")
        
        # Beneficiário
        for pattern in PATTERNS['beneficiario']:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                data['beneficiary'] = match.group(1).strip()
                logger.info(f"📝 Beneficiário: {data['beneficiary']}")
                break
        
        # EndToEnd
        for pattern in PATTERNS['endtoend']:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                data['endtoend'] = match.group(1).strip()
                logger.info(f"🔢 EndToEnd: {data['endtoend']}")
                break
        
        # Data
        for pattern in PATTERNS['data']:
            match = re.search(pattern, text)
            if match:
                date_str = match.group(1)
                # Tentar converter para formato ISO
                try:
                    if '/' in date_str:
                        if date_str.count('/') == 2:
                            parts = date_str.split('/')
                            if len(parts[0]) == 4:  # YYYY/MM/DD
                                data['date'] = date_str.replace('/', '-')
                            else:  # DD/MM/YYYY
                                data['date'] = f"{parts[2]}-{parts[1]}-{parts[0]}"
                    elif '-' in date_str:
                        data['date'] = date_str
                    logger.info(f"📅 Data: {data['date']}")
                    break
                except:
                    continue
        
        # Validar se extraiu informações mínimas
        if data['value'] and data['value'] > 0:
            logger.info(f"✅ Extração de PDF bem-sucedida (texto nativo)")
            return {
                **data,
                'success': True,
                'confidence': 0.98,  # Alta confiança em texto nativo
                'error': None
            }
        else:
            logger.warning(f"⚠️ Dados insuficientes extraídos do PDF")
            return None
    
    except Exception as e:
        logger.error(f"❌ Erro ao extrair texto do PDF: {e}")
        return None

def should_use_pdf_extractor(file_path: str) -> bool:
    """Determina se deve tentar extração de texto do PDF"""
    return file_path.lower().endswith('.pdf') and PDF_TEXT_SUPPORT
