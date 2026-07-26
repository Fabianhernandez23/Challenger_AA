import logging
import sys
import asyncio
from app.config import ADMIN_TOKEN
from contextlib import asynccontextmanager

import secrets
import uuid
import os

import uvicorn
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.agente import AgenteRAG
from app.prompts import WELCOME_MESSAGE
from app.vectorStore import VectorStoreManager


# Logging configuración

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# Instancias singleton

vsm = VectorStoreManager()
agente = AgenteRAG(vsm)

limiter = Limiter(key_func=get_remote_address)


# Lifespan: startup y shutdown

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa el vector store y el agente de forma segura al arrancar el servidor."""
    logger.info("Iniciando servidor del Agente RAG...")
    try:
        await asyncio.to_thread(vsm.initialize) 
        await agente.initialize() 
        logger.info("Servicio listo para recibir consultas")
    except Exception as e:
        logger.critical(f"Error crítico durante el arranque: {e}", exc_info=True)
        raise
    yield
    logger.info("Deteniendo servidores y limpiando tareas en segundo plano...")
    await agente.shutdown()
    logger.info("Servidor detenido correctamente.")



# Aplicación FastAPI

app = FastAPI(
    title="Agente RAG - Asistente de Información Nutricional Abbott.",
    description=(
        "API de inteligencia artificial que responde preguntas en lenguaje natural "
        "sobre información nutricional de los productos de Abbott usando RAG (Gemini + FAISS)."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:4200", 
] + [o for o in os.getenv("EXTRA_CORS_ORIGINS", "").split(",") if o]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)



# Modelos de datos (Pydantic)

class ChatRequest(BaseModel):
    pregunta: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Pregunta del usuario en lenguaje natural",
        examples=["¿Cuál es la información nutricional del producto X?", "¿Qué beneficios tiene el producto Y?"],
    )


class ChatResponse(BaseModel):
    respuesta: str = Field(description="Respuesta generada por el agente")
    fuentes: list[str] = Field(description="Documentos utilizados para responder")
    session_id: str = Field(description="ID de sesión — guardalo para mantener el hilo de la conversación")

class HealthResponse(BaseModel):
    estado: str
    vector_store_listo: bool
    agente_listo: bool
    mensaje: str


class ResetResponse(BaseModel):
    exito: bool
    mensaje: str

def _validar_o_generar_session_id(x_session_id: str | None) -> str:
    """Valida que el session_id sea un UUID válido; genera uno nuevo si falta o es inválido."""
    if x_session_id is None:
        return str(uuid.uuid4())
    try:
        uuid.UUID(x_session_id)
        return x_session_id
    except ValueError:
        logger.warning(f"session_id inválido recibido, generando uno nuevo.")
        return str(uuid.uuid4())
 


# Endpoints

@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Estado del servicio",
    tags=["Sistema"],
)
async def health_check():
    """Verifica que el vector store y el agente estén operativos."""
    agente_listo = agente.is_ready
    return HealthResponse(
        estado="activo" if agente_listo else "iniciando",
        vector_store_listo=vsm.is_ready,
        agente_listo=agente_listo,
        mensaje=(
            "Servicio completamente operativo"
            if agente_listo
            else "El servicio está iniciando, espera un momento"
        ),
    )


@app.post(
    "/chat",
    response_model=ChatResponse,
    summary="Enviar pregunta al agente",
    tags=["Chat"],
)
@limiter.limit("30/minute")
async def chat(
    request: Request,
    chat_request: ChatRequest,
    x_session_id: str | None = Header(None, description="ID único de sesión (UUID). Si no se envía, se genera uno nuevo."),
):
    """
    Envía una pregunta al agente RAG vinculada a una sesión específica.
    Evita la fuga de historiales entre diferentes usuarios.
    """
    if not agente.is_ready:
        raise HTTPException(
            status_code=503,
            detail="El agente todavía está inicializando. Intenta en unos segundos.",
        )
    session_id = _validar_o_generar_session_id(x_session_id)
    resultado = await agente.chat(pregunta=chat_request.pregunta, session_id=session_id)
    return ChatResponse(session_id=session_id, **resultado)


@app.post(
    "/reset-chat",
    response_model=ResetResponse,
    summary="Limpiar historial de conversación",
    tags=["Chat"],
)
async def reset_chat(x_session_id: str = Header(..., description="ID único de la sesión que se desea limpiar (UUID)")):
    """Reinicia el historial de conversación del agente (nueva sesión)."""

    try:
        uuid.UUID(x_session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="session_id inválido, debe ser un UUID.")

    await agente.reset_historial(session_id=x_session_id)
    return ResetResponse(
        exito=True,
        mensaje=f"Historial de la sesión {x_session_id} limpiado correctamente.",
    )


@app.post(
    "/reset-index",
    response_model=ResetResponse,
    summary="Regenerar índice FAISS",
    tags=["Sistema"],
)
@limiter.limit("3/hour")
async def reset_index(
    request: Request,
    x_admin_token: str = Header(..., description="Token de autenticación de administrador")):
    """
    Regenera el índice FAISS leyendo los PDFs del almacenamiento. 
    Protegido contra llamadas maliciosas de denegación de servicio (DoS).
    """

    if not secrets.compare_digest(x_admin_token, ADMIN_TOKEN):
        raise HTTPException(
            status_code=403, 
            detail="No tienes los permisos necesarios para realizar esta operación."
        )

    try:
        logger.info("Regenerando índice FAISS por solicitud del usuario...")
        await asyncio.to_thread(vsm.build_index)
        
        return ResetResponse(
            exito=True,
            mensaje="Índice FAISS regenerado correctamente en disco.",
        )
    except Exception as e:
        logger.error(f"Error regenerando índice: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error al regenerar el índice: {str(e)}",
        )


@app.get(
    "/",
    summary="Bienvenida",
    tags=["Sistema"],
)
async def root():
    """Endpoint raíz con mensaje de bienvenida."""
    return {
        "servicio": "Agente RAG - Asistente de Información Nutricional Abbott. ",
        "version": "1.0.0",
        "mensaje": WELCOME_MESSAGE,
        "documentacion": "/docs",
        "estado": "/health",
    }


# ─────────────────────────────────────────────
# Punto de entrada directo
# ─────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
