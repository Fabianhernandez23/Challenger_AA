import os
from pathlib import Path
from dotenv import load_dotenv



# Rutas base del proyecto

BASE_DIR = Path(__file__).resolve().parent.parent
DOCS_DIR = BASE_DIR / "data"
FAISS_INDEX_PATH = BASE_DIR / "faiss_index"
HISTORY_FILE_PATH = BASE_DIR / "chat_history.json"
ENV_FILE = BASE_DIR / ".env"


# Carga de variables de entorno

load_dotenv(dotenv_path=ENV_FILE)

def _get_env_clean(nombre: str, default: str = "") -> str:
    """Lee una variable de entorno y le saca espacios/comillas accidentales."""
    return os.getenv(nombre, default).strip().strip('"').strip("'")
 

GEMINI_API_KEY: str = _get_env_clean("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise EnvironmentError(
        "No se encontró GEMINI_API_KEY en el archivo .env\n"
        f"   Ruta esperada: {ENV_FILE}\n"
        "   Obtén tu clave gratuita en: https://aistudio.google.com/app/apikey"
    )

ADMIN_TOKEN: str = _get_env_clean("ADMIN_TOKEN")
 
if not ADMIN_TOKEN:
    raise EnvironmentError(
        "No se encontró ADMIN_TOKEN en el archivo .env\n"
        f"   Ruta esperada: {ENV_FILE}\n"
        "   Generalo con: python -c \"import secrets; print(secrets.token_urlsafe(32))\"\n"
        "   y agregalo como ADMIN_TOKEN=el_valor_generado"
    )

# Configuración del bot de Telegram

TELEGRAM_BOT_TOKEN: str = _get_env_clean("TELEGRAM_BOT_TOKEN")

if not TELEGRAM_BOT_TOKEN:
    raise EnvironmentError(
        "No se encontró TELEGRAM_BOT_TOKEN en el archivo .env o en las variables de entorno.\n"
        f"  Ruta esperada: {ENV_FILE}\n"
        "  Obtén tu token creando un bot con @BotFather en Telegram."
    )

# Modelos de Google Gemini


LLM_MODEL = "gemini-3.5-flash"
EMBEDDING_MODEL = "models/gemini-embedding-001"


# Parámetros del chunking de documentos

CHUNK_SIZE = 1200       
CHUNK_OVERLAP = 100    

TOP_K_RESULTS = 5


# Configuración del LLM

LLM_TEMPERATURE = 0.2   
LLM_MAX_TOKENS = 2048
