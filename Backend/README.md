# 🎮 Agente RAG — Soporte Técnico SEGA

API de inteligencia artificial que responde preguntas en lenguaje natural sobre la documentación oficial de SEGA, usando un pipeline **RAG (Retrieval-Augmented Generation)** construido con **FastAPI**, **LangChain**, **FAISS** y **Google Gemini**.

---

##  Tabla de Contenidos

- [Arquitectura](#arquitectura)
- [Tecnologías](#tecnologías)
- [Estructura del Proyecto](#estructura-del-proyecto)
- [Requisitos Previos](#requisitos-previos)
- [Instalación](#instalación)
- [Configuración](#configuración)
- [Ejecución](#ejecución)
- [Endpoints de la API](#endpoints-de-la-api)
- [Pipeline RAG](#pipeline-rag)
- [Gestión de Sesiones](#gestión-de-sesiones)
- [Seguridad](#seguridad)

---

## Arquitectura

```
Usuario → FastAPI → AgenteRAG
                       ├── VectorStoreManager (FAISS + Embeddings Gemini)
                       │       └── DocumentLoader (PyMuPDF → LangChain Documents)
                       └── ChatGoogleGenerativeAI (Gemini 2.5 Flash)
```

El flujo de una consulta es el siguiente:

1. El usuario envía una pregunta al endpoint `/chat`
2. El retriever busca los fragmentos más relevantes en el índice FAISS
3. Se construye el prompt con el contexto recuperado y el historial de la sesión
4. Gemini genera la respuesta en español
5. Se devuelve la respuesta junto con las fuentes utilizadas

---

## Tecnologías

| Categoría | Librería / Servicio |
|---|---|
| Framework API | FastAPI + Uvicorn |
| LLM | Google Gemini 2.5 Flash |
| Embeddings | `gemini-embedding-001` |
| Orquestación RAG | LangChain (LCEL) |
| Vector Store | FAISS (local) |
| Lectura de PDFs | PyMuPDF (`fitz`) |
| Rate Limiting | SlowAPI |
| Validación de datos | Pydantic v2 |
| Variables de entorno | python-dotenv |

---

## Estructura del Proyecto

```
BackEnd/
├── app/
│   ├── main.py             # Aplicación FastAPI, endpoints y middleware
│   ├── agente.py           # Clase AgenteRAG — lógica principal del chat
│   ├── vectorStore.py      # Clase VectorStoreManager — FAISS + embeddings
│   ├── document_loader.py  # Clase DocumentLoader — carga y parseo de PDFs
│   ├── config.py           # Configuración global y variables de entorno
│   └── prompts.py          # Prompts del sistema y mensajes predefinidos
├── Documentacion/          # PDFs de soporte técnico de SEGA
├── faiss_index/            # Índice FAISS persistido en disco (auto-generado)
│   ├── index.faiss
│   └── index.pkl
├── static/
│   ├── requirements.txt    # Dependencias del proyecto
│   └── .env.example        # Plantilla de variables de entorno
├── .env                    # Variables de entorno (no subir al repo)
└── README.md
```

---

## Requisitos Previos

- **Python** 3.11 o superior
- **API Key de Google Gemini** — obtén la tuya gratis en [aistudio.google.com](https://aistudio.google.com/app/apikey)
- (Opcional) **entorno virtual** — recomendado para aislar dependencias

---

## Instalación

**1. Clona el repositorio y entra al directorio del backend:**

```bash
git clone <url-del-repo>
cd BackEnd
```

**2. Crea y activa un entorno virtual:**

```bash
# Crear entorno
python -m venv venv

# Activar en Linux/macOS
source venv/bin/activate

# Activar en Windows
venv\Scripts\activate
```

**3. Instala las dependencias:**

```bash
pip install -r static/requirements.txt
```

---

## Configuración

**1. Crea el archivo `.env`** en la raíz de `BackEnd/` copiando la plantilla:

```bash
cp static/.env.example .env
```

**2. Completa las variables en `.env`:**

```env
# Clave de la API de Google Gemini
GEMINI_API_KEY=tu_clave_aqui

# Token de administrador para endpoints protegidos
# Genera uno seguro con:  python -c "import secrets; print(secrets.token_urlsafe(32))"
ADMIN_TOKEN=tu_token_aqui
```

>  **Nunca subas el archivo `.env` al repositorio.** Está incluido en `.gitignore`.

---

## Ejecución

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Al arrancar, el servidor automáticamente:
- Intenta cargar el índice FAISS desde disco (`faiss_index/`)
- Si no existe, lo construye procesando los PDFs de `Documentacion/`

Una vez iniciado, accede a la documentación interactiva en:

- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## Endpoints de la API

### `GET /`
Mensaje de bienvenida y estado general del servicio.

---

### `GET /health`
Verifica que el vector store y el agente estén operativos.

**Respuesta:**
```json
{
  "estado": "activo",
  "vector_store_listo": true,
  "agente_listo": true,
  "mensaje": "Servicio completamente operativo"
}
```

---

### `POST /chat`
Envía una pregunta al agente RAG. Limitado a **15 peticiones por minuto** por IP.

**Headers:**

| Header | Tipo | Descripción |
|---|---|---|
| `x-session-id` | `string` (UUID) | Opcional. ID de sesión para mantener el hilo de conversación. Si no se envía, se genera uno nuevo. |

**Body:**
```json
{
  "pregunta": "¿Cómo puedo recuperar mi contraseña de SEGA?"
}
```

**Respuesta:**
```json
{
  "respuesta": "Para recuperar tu contraseña, ve a la página de inicio de sesión...",
  "fuentes": ["Soporte de cuentas de SEGA.pdf"],
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

> Guarda el `session_id` devuelto y envíalo en las siguientes peticiones para mantener el contexto de la conversación.

---

### `POST /reset-chat`
Limpia el historial de conversación de una sesión específica.

**Headers:**

| Header | Tipo | Descripción |
|---|---|---|
| `x-session-id` | `string` (UUID) | Requerido. ID de la sesión a limpiar. |

---

### `POST /reset-index`
Regenera el índice FAISS leyendo los PDFs de `Documentacion/`. Limitado a **3 peticiones por hora**.

**Headers:**

| Header | Tipo | Descripción |
|---|---|---|
| `x-admin-token` | `string` | Requerido. Token de administrador definido en `.env`. |

---

## Pipeline RAG

```
PDFs (Documentacion/)
        │
        ▼
  DocumentLoader          ← PyMuPDF extrae texto página por página
        │
        ▼
RecursiveCharacterTextSplitter  ← chunks de 1200 chars, overlap 100
        │
        ▼
  GoogleGenerativeAIEmbeddings  ← modelo gemini-embedding-001
        │
        ▼
    FAISS Index             ← persistido en faiss_index/
        │
   [en cada /chat]
        │
        ▼
  Retriever (top-5)         ← búsqueda por similitud coseno
        │
        ▼
  ChatPromptTemplate        ← contexto + historial + pregunta
        │
        ▼
  Gemini 2.5 Flash          ← temperatura 0.2, max 2048 tokens
        │
        ▼
    Respuesta + Fuentes
```

### Parámetros de configuración (`config.py`)

| Parámetro | Valor | Descripción |
|---|---|---|
| `LLM_MODEL` | `gemini-2.5-flash` | Modelo de lenguaje |
| `EMBEDDING_MODEL` | `gemini-embedding-001` | Modelo de embeddings |
| `CHUNK_SIZE` | `1200` | Tamaño de fragmento en caracteres |
| `CHUNK_OVERLAP` | `100` | Solapamiento entre fragmentos |
| `TOP_K_RESULTS` | `5` | Fragmentos recuperados por consulta |
| `LLM_TEMPERATURE` | `0.2` | Determinismo de la respuesta |
| `LLM_MAX_TOKENS` | `2048` | Tokens máximos por respuesta |

---

## Gestión de Sesiones

El historial de conversación se almacena **en memoria por proceso**, identificado por un UUID de sesión.

| Parámetro | Valor | Descripción |
|---|---|---|
| `MAX_HISTORY_TURNS` | `5` | Turnos máximos de conversación en memoria |
| `SESSION_TTL_SECONDS` | `3600` | Sesiones expiran tras 1 hora de inactividad |
| `CLEANUP_INTERVAL_SECONDS` | `600` | El recolector de basura corre cada 10 minutos |

> **Nota de escalabilidad:** Si el servicio corre con múltiples workers (`--workers > 1`) o en varias instancias, cada proceso tendrá su propio historial desincronizado. Para ese escenario, reemplaza el dict en memoria por un backend compartido como **Redis**.

---

## Seguridad

- **Rate limiting** en `/chat` (15/min) y `/reset-index` (3/hora) mediante SlowAPI
- **CORS** restringido a `localhost:3000` y `localhost:4200`
- **Validación de session_id** — solo acepta UUIDs válidos
- **Token de administrador** comparado con `secrets.compare_digest` para prevenir ataques de timing
- **Longitud máxima** de pregunta: 500 caracteres
- Las claves sensibles se cargan exclusivamente desde el archivo `.env`
