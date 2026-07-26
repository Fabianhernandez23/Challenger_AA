import logging
from typing import List, TypedDict, Dict
import time
import asyncio


from google.api_core.exceptions import GoogleAPIError, ResourceExhausted
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import (
    GEMINI_API_KEY,
    LLM_MODEL,
    LLM_TEMPERATURE,
    LLM_MAX_TOKENS,
)

from app.prompts import (
    SYSTEM_PROMPT,
    ERROR_MESSAGE,
    NO_CONTEXT_MESSAGE,
    #MEDICAL_DISCLAIMER,
)

from app.vectorStore import VectorStoreManager

logger = logging.getLogger(__name__)

MAX_HISTORY_TURNS = 5
MAX_PREGUNTA_LENGTH = 500
SESSION_TTL_SECONDS = 3600 
CLEANUP_INTERVAL_SECONDS = 600

class SessionData(TypedDict):
    messages: List[BaseMessage]
    last_access: float

def _format_docs(docs: List[Document]) -> str:
    """Formats retrieved documents into a clean string for prompt injection,

    preserving product context and page metadata.
    """
    formatted_chunks = []
    for doc in docs:
        fuente = doc.metadata.get("fuente", "Ficha Técnica Abbott")
        pagina = doc.metadata.get("pagina", "N/A")
        producto = doc.metadata.get("producto", "Información General")

        header = f"[Producto: {producto} | Fuente: {fuente} | Pág: {pagina}]"
        formatted_chunks.append(f"{header}\n{doc.page_content}")

    return "\n\n---\n\n".join(formatted_chunks)

"""def _format_docs(docs: List[Document]) -> str:
    ""Convierte una lista de documentos en texto para el contexto del prompt.""
    return "\n\n---\n\n".join(
        f"[Fuente: {doc.metadata.get('fuente', 'Desconocido')}]\n{doc.page_content}"
        for doc in docs
    )"""

class AgenteRAG:
    """
    Agente de IA RAG especializado en productos de Nutrición Clínica de Abbott.

    Flujo de una consulta (LCEL):
    1. El usuario envía una pregunta
    2. El retriever busca los fragmentos más relevantes en FAISS
    3. Se construye el prompt con el contexto recuperado + historial
    4. Gemini genera la respuesta en español
    5. Se devuelve la respuesta con las fuentes utilizadas

    Nota de escalabilidad: el historial vive en memoria del proceso (Dict).
    Si el servicio corre con múltiples workers (Gunicorn/Uvicorn con --workers > 1)
    o múltiples instancias en OCI, cada proceso tendrá su propio historial
    desincronizado. Para ese escenario, reemplazar self._historiales por un
    backend compartido (Redis) — ver notas al final del archivo.
    """

    def __init__(self, vector_store_manager: VectorStoreManager):
        self._vsm = vector_store_manager
        self._llm: ChatGoogleGenerativeAI | None = None
        self._prompt: ChatPromptTemplate | None = None
        self._historiales: Dict[str, SessionData] = {}
        self._initialized = False
        self._session_lock = asyncio.Lock()   # Protege lectura/escritura de historiales
        self._cleanup_lock = asyncio.Lock()   # Protege el ciclo de limpieza en background
        self._cleanup_task: asyncio.Task | None = None

    
    # Inicialización del agente
    
    async def initialize(self) -> None:
        """Construye los componentes base de la cadena RAG con LCEL."""
        logger.info(f"Inicializando agente RAG con modelo {LLM_MODEL}...")

 
        self._llm = ChatGoogleGenerativeAI(
            model=LLM_MODEL,
            google_api_key=GEMINI_API_KEY,
            temperature=LLM_TEMPERATURE,
            max_output_tokens=LLM_MAX_TOKENS,
        )

        ## Construcción del prompt con el sistema y placeholders


        self._prompt = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="historial"),
        ("human", "{pregunta}"),
    ]
        )

        ## Inicialización de la memoria de sesiones

        self._initialized = True
        self._start_background_cleanup()
        logger.info("Agente RAG inicializado correctamente")

    async def shutdown(self) -> None:
        """
        Detiene ordenadamente la tarea de limpieza en background.
        Llamar desde el evento 'shutdown' de FastAPI.
        """
        if self._cleanup_task is not None and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            logger.info("Tarea de limpieza de sesiones cancelada correctamente")

    
    # Persistencia de Historial

    async def _get_session_history(self, session_id: str) -> List:
        """Obtiene y limita el historial específico de una sesión."""
        async with self._session_lock:
            if session_id not in self._historiales:
                self._historiales[session_id] = {"messages": [], "last_access": time.time()}
                
            self._historiales[session_id]["last_access"] = time.time()
            return list(self._historiales[session_id]["messages"][-MAX_HISTORY_TURNS * 2:])

    async def _save_session_historial(self, session_id: str, pregunta: str, respuesta: str) -> None:
        """Guarda la interacción en la sesión y recorta el exceso de memoria de forma segura."""
        async with self._session_lock:
            if session_id not in self._historiales:
                self._historiales[session_id] = {"messages": [], "last_access": time.time()}

            session = self._historiales[session_id]
            session["messages"].append(HumanMessage(content=pregunta))
            session["messages"].append(AIMessage(content=respuesta))
            session["last_access"] = time.time()
            
            if len(session["messages"]) > MAX_HISTORY_TURNS * 2:
                session["messages"] = session["messages"][-MAX_HISTORY_TURNS * 2:]

    def _start_background_cleanup(self) -> None:
        """Lanza un demonio que limpia la RAM de forma asíncrona cada cierto intervalo."""
        async def cleanup_loop():
            while True:
                await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
                try:
                    ahora = time.time()
                    async with self._session_lock:
                        expiradas = [
                            sid for sid, data in self._historiales.items()
                            if ahora - data["last_access"] > SESSION_TTL_SECONDS
                        ]
                        for sid in expiradas:
                            del self._historiales[sid]
                    if expiradas:
                        logger.info(f"Recolector de basura: {len(expiradas)} sesiones inactivas eliminadas de la RAM.")
                except Exception as e:
                    logger.error(f"Error en el ciclo de limpieza de sesiones: {e}", exc_info=True)

        self._cleanup_task = asyncio.create_task(cleanup_loop())


    
    # Método principal de chat
   
    async def chat(self, pregunta: str, session_id: str) -> dict:
        """
        Procesa de forma asíncrona una pregunta aislada por ID de sesión.
 
        Args:
            pregunta: La consulta del usuario.
            session_id: Identificador único del usuario o chat.
 
        Returns:
            dict con 'respuesta' (str) y 'fuentes' (list[str])
        """
        if not self._initialized or self._llm is None or self._prompt is None:
            raise RuntimeError(
                "El agente no está inicializado. Llama a initialize() primero."
            )

        if not pregunta.strip():
            return {"respuesta": "Por favor, escribe tu pregunta.", "fuentes": []}
        
        if len(pregunta) > MAX_PREGUNTA_LENGTH:
            return {
                "respuesta": f"Tu pregunta es muy larga (máximo {MAX_PREGUNTA_LENGTH} caracteres). Intenta ser más breve.",
                "fuentes": []
             }

        try:
            logger.info(f"Procesando pregunta: {pregunta[:50]}...")

            retriever = self._vsm.get_retriever()
            docs = await asyncio.to_thread(retriever.invoke, pregunta)
            
            if not docs:
                contexto = NO_CONTEXT_MESSAGE 
                ##"No hay información relevante en la base de conocimiento para este mensaje."
            else:
                contexto = _format_docs(docs)

            historial_usuario = await self._get_session_history(session_id)

            cadena = self._prompt | self._llm | StrOutputParser()

            respuesta = await cadena.ainvoke({
                "context": contexto,
                "historial": historial_usuario,
                "pregunta": pregunta,
            })

            await self._save_session_historial(session_id, pregunta, respuesta)

            fuentes = list(dict.fromkeys(
                doc.metadata.get("fuente", "Documento desconocido")
                for doc in docs
            ))

            return {"respuesta": respuesta, "fuentes": fuentes}

        except ResourceExhausted as e:
            logger.error(f"Cuota de la API de Gemini excedida: {e}")
            return {"respuesta": "Se alcanzó el límite de uso del servicio. Intenta en unos minutos.", "fuentes": []}
        except GoogleAPIError as e:
            logger.error(f"Error de la API de Gemini: {e}")
            return {"respuesta": ERROR_MESSAGE, "fuentes": []}
        except Exception as e:
            logger.error(f"Error inesperado al procesar pregunta: {e}", exc_info=True)
            return {"respuesta": ERROR_MESSAGE, "fuentes": []}

    
    # Limpiar historial de conversación
    
    async def reset_historial(self, session_id: str) -> None:
        """Borra explícitamente una sesión de memoria usando exclusión mutua."""
        async with self._session_lock:
            if session_id in self._historiales:
                del self._historiales[session_id]
                logger.info(f"Historial de la sesión {session_id} reiniciado")

    
    # Estado del agente
    
    @property
    def is_ready(self) -> bool:
        """Indica si el agente está listo para recibir preguntas."""
        return self._initialized and self._llm is not None
