import logging
from pathlib import Path
from typing import List

import fitz  
from langchain_core.documents import Document

from app.config import DOCS_DIR

logger = logging.getLogger(__name__)


class DocumentLoader:
    """
    Carga los archivos PDF de la carpeta Documentacion/ y los convierte
    en objetos Document de LangChain con metadatos enriquecidos.

    Pipeline RAG:
        [DocumentLoader] → Chunking → Embeddings → VectorStore → Retriever
    """

    def __init__(self, docs_dir: Path | str = DOCS_DIR):
        self.docs_dir = Path(docs_dir)

    
    # Carga de un solo PDF
    
    def _load_pdf(self, pdf_path: Path) -> Document | None:
        """
        Lee un archivo PDF página por página y convierte cada una en un Document.
        De esta forma, los metadatos de la página se preservan tras el chunking.

        Args:
            pdf_path: Ruta al archivo PDF.

        Returns:
            Lista de objetos Document (uno por página con texto), o lista vacía si falla.
        """
        doc = None
        documents_por_pagina: List[Document] = []
        try:
            doc = fitz.open(str(pdf_path))
            
            for page_num, page in enumerate(doc, start=1):
                text = page.get_text("text")
                if not text.strip():
                    continue
                
                doc_objeto = Document(
                    page_content=text.strip(),
                    metadata={
                        "fuente": pdf_path.name,
                        "ruta": str(pdf_path),
                        "pagina": page_num,         # ← Metadato exacto por fragmento
                        "total_paginas": len(doc),  # ← Utilidad complementaria
                        "tipo": "soporte_tecnico_sega",
                    },
                )
                documents_por_pagina.append(doc_objeto)
            if not documents_por_pagina:
                logger.warning("%s — no contiene texto extraíble en ninguna página", pdf_path.name)

        except Exception as e:
            logger.error("Error leyendo %s: %s", pdf_path.name, e)
        finally:
            if doc is not None:
                doc.close()
                
        return documents_por_pagina
                


    # Carga de todos los PDFs
    
    def load(self) -> List[Document]:
        """
        Carga todos los archivos PDF de la carpeta Documentacion/.

        Returns:
            Lista de Documents listos para el siguiente paso del pipeline.

        Raises:
            FileNotFoundError: Si la carpeta no existe o no hay PDFs.
            ValueError: Si no se pudo extraer texto de ningún archivo.
        """
        if not self.docs_dir.exists():
            raise FileNotFoundError(
                f"La carpeta de documentos no existe: {self.docs_dir}"
            )

        pdf_files = sorted(self.docs_dir.glob("*.pdf"))

        if not pdf_files:
            raise FileNotFoundError(
                f"No se encontraron archivos PDF en: {self.docs_dir}"
            )

        logger.info("Carpeta de documentos: %s", self.docs_dir)
        logger.info("Archivos encontrados: %d PDFs", len(pdf_files))

        all_documents: List[Document] = []

        for pdf_path in pdf_files:
            logger.info(" Procesando: %s", pdf_path.name)
            paginas_cargadas = self._load_pdf(pdf_path)


            if paginas_cargadas:
                all_documents.extend(paginas_cargadas)
                logger.info(
                    "  %s — %d páginas con texto procesadas",
                    pdf_path.name,
                    len(paginas_cargadas),
                )

        if not all_documents:
            raise ValueError(
                "No se pudo extraer texto de ningún documento PDF del directorio."
            )

        logger.info(
            "Carga completa: %d páginas totales preparadas para la fase de chunking.",
            len(all_documents),
        )
        return all_documents