import logging
from pathlib import Path
from typing import List
import threading

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from app.config import (
    DOCS_DIR,
    FAISS_INDEX_PATH,
    GEMINI_API_KEY,
    EMBEDDING_MODEL,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    TOP_K_RESULTS,
)
from app.document_loader import DocumentLoader

logger = logging.getLogger(__name__)


class VectorStoreManager:
    """
    Maneja el ciclo de vida completo del vector store FAISS:
    - Carga de PDFs desde la carpeta Documentacion/
    - Conversión a chunks de texto
    - Generación de embeddings con Google text-embedding-004
    - Persistencia del índice FAISS en disco
    - Exposición del retriever para el agente RAG
    """

    def __init__(self):
        self._embeddings = GoogleGenerativeAIEmbeddings(
            model=EMBEDDING_MODEL,
            google_api_key=GEMINI_API_KEY,
        )
        self._vector_store: FAISS | None = None
        self._lock = threading.Lock() 

    
    # Carga de documentos PDF
    
    def load_documents(self) -> List[Document]:
        """
        Delega la carga de PDFs al DocumentLoader (primera etapa del pipeline).
        """
        loader = DocumentLoader(docs_dir=DOCS_DIR)
        return loader.load()

    
    # División en chunks
  
    def _split_documents(self, documents: List[Document]) -> List[Document]:
        """Divide los documentos en fragmentos más pequeños para mejor retrieval."""
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            separators=["\n\n", "\n", ". ", " ", ""],
            length_function=len,
        )
        chunks = splitter.split_documents(documents)
        logger.info(f"Documentos divididos en {len(chunks)} fragmentos (chunks)")
        return chunks

    
    # Construcción del índice FAISS
   
    def build_index(self) -> None:
        """
        Carga los PDFs, los divide en chunks, genera embeddings
        y guarda el índice FAISS en disco.
        """
        logger.info("Construyendo índice FAISS desde cero...")

        try:
            documents = self.load_documents()
            chunks = self._split_documents(documents)
            chunks = [ c for c in chunks if c.page_content.strip() ]

            if not chunks:
                raise ValueError(
                    f"No se generaron fragmentos de texto válidos. "
                    f"Verifica que existan PDFs con texto legible en: {DOCS_DIR}"
                )

            logger.info("Generando embeddings con Google text-embedding-004...")
            nuevo_vector_store = FAISS.from_documents(chunks, self._embeddings)

            Path(FAISS_INDEX_PATH).mkdir(parents=True, exist_ok=True)
            nuevo_vector_store.save_local(str(FAISS_INDEX_PATH))

            with self._lock:   
                self._vector_store = nuevo_vector_store

            logger.info(f"Índice FAISS guardado en: {FAISS_INDEX_PATH}")
        except Exception as e:
            logger.error(f"Error crítico construyendo el índice FAISS: {e}", exc_info=True)
            raise

    
    # Carga del índice existente
    
    def load_index(self) -> bool:
        """
        Intenta cargar el índice FAISS desde disco.
        Retorna True si tuvo éxito, False si no existe.
        """
        index_file = Path(FAISS_INDEX_PATH) / "index.faiss"

        if not index_file.exists():
            logger.info("No se encontró índice FAISS en disco.")
            return False

        try:
            instancia_local = FAISS.load_local(
                str(FAISS_INDEX_PATH),
                self._embeddings,
                allow_dangerous_deserialization=True,
            )
            
            with self._lock:   # ← Protegemos la mutación de la propiedad global
                self._vector_store = instancia_local
                
            logger.info(f"Índice FAISS cargado correctamente desde: {FAISS_INDEX_PATH}")
            return True
        except Exception as e:
            logger.error(f"Error cargando índice FAISS (posible archivo corrupto): {e}")
            return False

    
    # Inicialización (carga o construye)
    
    def initialize(self) -> None:
        """
        Punto de entrada principal. Intenta cargar el índice desde disco;
        si no existe, lo construye desde los PDFs.
        """
        if not self.load_index():
            logger.info("Construyendo nuevo índice desde los documentos...")
            self.build_index()


    # Retriever para el agente
    
    def get_retriever(self):
        """Devuelve el retriever de LangChain configurado con TOP_K_RESULTS."""
        
        with self._lock:
            if self._vector_store is None:
                raise RuntimeError(
                    "El vector store no está inicializado. "
                    "Llama a initialize() primero antes de solicitar el retriever."
                )
            return self._vector_store.as_retriever(
                search_type="similarity",
                search_kwargs={"k": TOP_K_RESULTS},
            )

    @property
    def is_ready(self) -> bool:
        """Indica si el vector store está listo para consultas."""
        return self._vector_store is not None
