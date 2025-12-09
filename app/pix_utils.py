"""
PIX utilities: normalization helpers used across the backend.
"""
import re

def normalize_pix_key(pix: str) -> str:
    """Normalize a PIX key for consistent comparison.
    Removes whitespace and common punctuation, lowercases, and returns an empty
    string for None inputs.
    """
    if pix is None:
        return ""
    s = str(pix).strip().lower()
    # remover prefixo 'pix' ou 'pix:' se presente
    if s.startswith('pix:'):
        s = s[4:].strip()
    elif s.startswith('pix '):
        s = s[4:].strip()
    elif s == 'pix':
        s = ''
    # remove spaces, hyphens, dots, slashes, parentheses, colons and backslashes
    s = re.sub(r"[\s\-\./():\\]+", "", s)
    return s
