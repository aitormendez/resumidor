"""
Carga de variables de entorno y utilidades de logging / flags.
Se importa en todos los módulos.
"""
from __future__ import annotations
import os, time

# --- variables de entorno ---
OLLAMA_URL   = os.getenv("OLLAMA_URL",  "http://localhost:11434")
MODEL        = os.getenv("OLLAMA_MODEL","qwen3:14b")
NUM_CTX      = int(os.getenv("NUM_CTX", "32768"))
TEMPERATURE  = float(os.getenv("TEMPERATURE", "0.1"))
NUM_PREDICT  = int(os.getenv("NUM_PREDICT", "2048"))

CONNECT_TIMEOUT = float(os.getenv("CONNECT_TIMEOUT", "10"))
READ_TIMEOUT    = None if os.getenv("READ_TIMEOUT", "").strip()=="" else float(os.getenv("READ_TIMEOUT"))
CHUNK_FRACTION  = float(os.getenv("CHUNK_FRACTION", "0.5"))
OVERLAP_TOKENS  = int(os.getenv("OVERLAP_TOKENS", "200"))

# --- flags on/off ---
_DEF_TRUE  = {"1","true","yes","on","y"}
_DEF_FALSE = {"0","false","no","off","n"}
def env_flag(name: str, default: bool=False) -> bool:
    v = str(os.getenv(name,"")).strip().lower()
    if not v:                 return default
    if v in _DEF_TRUE:        return True
    if v in _DEF_FALSE:       return False
    return default

VERBOSE     = env_flag("VERBOSE",  True)
STREAM      = env_flag("STREAM",   True)
STREAM_MAP  = env_flag("STREAM_MAP",  True)
STREAM_FUSE = env_flag("STREAM_FUSE", True)

# --- logging ---
def log(msg: str) -> None:
    if VERBOSE:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)