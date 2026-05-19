import json
import os
from typing import Optional, Dict

locales = {}

def load_locales():
    # Locate local directory (parent of python_app, then local)
    current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # We search both inside workspace root and parent folder if nested
    paths_to_try = [
        os.path.join(current_dir, "local"),
        os.path.join(os.path.dirname(current_dir), "local")
    ]
    
    local_dir = None
    for p in paths_to_try:
        if os.path.exists(p):
            local_dir = p
            break
            
    if not local_dir:
        print("[i18n] Warn: 'local' directory containing localization JSON files not found.")
        return
        
    for filename in ["en.json", "am.json"]:
        filepath = os.path.join(local_dir, filename)
        if os.path.exists(filepath):
            lang = filename.split(".")[0]
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    locales[lang] = json.load(f)
                print(f"[i18n] Loaded locale '{lang}' from {filepath}")
            except Exception as e:
                print(f"[i18n] Error loading {filepath}: {e}")

def t_sync(lang: str, key: str, replacements: Optional[Dict] = None) -> str:
    lang_dict = locales.get(lang, locales.get("en", {}))
    template = lang_dict.get(key, locales.get("en", {}).get(key, key))
    if replacements:
        for k, v in replacements.items():
            template = template.replace(f"{{{k}}}", str(v))
    return template

# Load locales on import
load_locales()
