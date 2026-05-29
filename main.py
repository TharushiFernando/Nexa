from fastapi.responses import JSONResponse
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uuid
import os
from typing import Optional, Dict, Any
import datetime
from fastapi.staticfiles import StaticFiles
import threading

# ====================== MYSQL CONNECTOR (SAFE IMPORT) ======================
mysql_connector = None
try:
    import mysql.connector
    mysql_connector = mysql.connector
    print("✅ MySQL connector loaded successfully")
except ModuleNotFoundError:
    print("⚠️  mysql-connector-python is not installed. Database logging will be disabled.")
except Exception as e:
    print(f"⚠️  Error loading MySQL connector: {e}")

# ====================== LANGCHAIN & OTHER IMPORTS ======================
LANGCHAIN_AVAILABLE = True
try:
    from langchain_community.document_loaders import PyPDFLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_ollama import OllamaEmbeddings, ChatOllama
    from langchain_chroma import Chroma
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
    from langchain_core.output_parsers import StrOutputParser
    from langchain.chains import create_history_aware_retriever, create_retrieval_chain
    from langchain_core.runnables.history import RunnableWithMessageHistory
    from langchain_community.chat_message_histories import ChatMessageHistory
except ModuleNotFoundError:
    LANGCHAIN_AVAILABLE = False
    print("⚠️  LangChain dependencies not fully installed.")


IMAGE_RUNTIME_AVAILABLE = True
try:
    from diffusers import DiffusionPipeline
    import torch
except ModuleNotFoundError:
    IMAGE_RUNTIME_AVAILABLE = False
    DiffusionPipeline = None
    torch = None

try:
    from markdown_pdf import MarkdownPdf, Section
except ModuleNotFoundError:
    MarkdownPdf = None
    Section = None

WORKSPACE_DIR = os.path.dirname(__file__)

PDF_PATHS = [
    os.path.join(WORKSPACE_DIR, "G6_Science_Textbook_removed_compressed (1).pdf"),
    os.path.join(WORKSPACE_DIR, "gr12Ente3.pdf"),
    os.path.join(WORKSPACE_DIR, "gr13Phyte3.pdf"),
    os.path.join(WORKSPACE_DIR, "Gr12te3.pdf")
]

INDEX_PATH = os.path.join(WORKSPACE_DIR, "index.html")

MODEL_NAME = "llama3.1:8b-instruct-q5_K_M"
EMBED_MODEL = "nomic-embed-text"

SESSION_STORE: Dict[str, Any] = {}

IMAGE_OUTPUT_DIR = os.path.join(WORKSPACE_DIR, "assets")
UPLOAD_DIR = os.path.join(WORKSPACE_DIR, "uploads")

os.makedirs(IMAGE_OUTPUT_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

IMAGE_STATUS: Dict[str, str] = {}

DB_CONFIG = {
    "host": os.getenv("NEXA_DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("NEXA_DB_PORT", "3306")),
    "user": os.getenv("NEXA_DB_USER", "nexa_user"),
    "password": os.getenv("NEXA_DB_PASSWORD", "NexaPass123!"),
    "database": os.getenv("NEXA_DB_NAME", "nexa_ai"),
}

TEST_USER_NAME = "Test User"


class ChatLogPayload(BaseModel):
    log_id: str
    user_name: str
    user_prompt: str
    nexa_response: str
    timestamp: str
    stars: int = 0


class RatingPayload(BaseModel):
    log_id: str
    user_name: str
    stars: int
    timestamp: str


class PopPayload(BaseModel):
    log_id: str


# Server-side stack to mirror push/pop operations done by the UI.
chat_stack = []



# ====================== LOAD PDFs ======================
docs = []
retriever = None
llm = None
rag_chain = None
conversational_rag_chain = None

if LANGCHAIN_AVAILABLE:
    print("Loading PDFs...")
    for pdf in PDF_PATHS:
        if os.path.exists(pdf):
            loader = PyPDFLoader(pdf)
            docs.extend(loader.load())

    if docs:
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=300)
        splits = text_splitter.split_documents(docs)

        embeddings = OllamaEmbeddings(model=EMBED_MODEL)
        vectorstore = Chroma.from_documents(
            documents=splits,
            embedding=embeddings,
            collection_name="curriculum_db"
        )

        retriever = vectorstore.as_retriever(search_kwargs={"k": 6})

        llm = ChatOllama(model=MODEL_NAME, temperature=0.4)

# ====================== HISTORY RETRIEVER ======================
if LANGCHAIN_AVAILABLE and retriever is not None and llm is not None:
    contextualize_q_prompt = ChatPromptTemplate.from_messages([
        ("system", "Given the chat history and latest user question, reformulate it as a standalone query about the curriculum."),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ])

    history_aware_retriever = create_history_aware_retriever(llm, retriever, contextualize_q_prompt)

# ====================== YOUR SYSTEM PROMPT (UNCHANGED) ======================
system_prompt = ( "You are an expert educator and curriculum designer. " "Use ONLY the provided curriculum excerpts and previous conversation context " "to create high-quality, engaging lesson plans. " "Always stay faithful to the curriculum PDFs. " "\n\n" "- If the user asks a simple question (What is..., Explain..., Define..., etc.), give a **clear, direct, and student-friendly explanation**. Do NOT use >" "- Only use the full lesson plan structure when the user explicitly says 'lesson plan', 'create a lesson plan', 'teaching plan', or 'make a lesson'.\n\n" "Output **everything in clean Markdown format** so it can be easily converted to PDF:\n" "- Start with a single # Main Title\n" "- Use ## for major sections (Objectives, Materials, Activities, etc.)\n" "- Use ### for subsections\n" "- Use - or * for bullet points\n" "- Use 1. 2. 3. for numbered steps\n" "- Use **bold** and *italic* where appropriate\n" "- Use Markdown tables when showing rubrics, materials lists, or schedules\n" "\n" "Required structure:\n" "Grade\n" "Subject\n" "Topic\n" "Learning Objectives (aligned to curriculum)\n" "Duration\n" "Materials\n" "Step-by-step Activities\n" "Differentiation strategies\n" "Assessment methods\n" "Extensions / Homework\n\n" "Curriculum context: {context}\n\n" "Chat history (for continuity): {chat_history}" )

if LANGCHAIN_AVAILABLE and llm is not None:
    qa_prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ])

    question_answer_chain = qa_prompt | llm | StrOutputParser()

    rag_chain = create_retrieval_chain(history_aware_retriever, question_answer_chain)

# ====================== SESSION ======================
if LANGCHAIN_AVAILABLE and rag_chain is not None:
    def get_session_history(session_id: str):
        if session_id not in SESSION_STORE:
            SESSION_STORE[session_id] = ChatMessageHistory()
        return SESSION_STORE[session_id]

    conversational_rag_chain = RunnableWithMessageHistory(
        rag_chain,
        get_session_history,
        input_messages_key="input",
        history_messages_key="chat_history",
        output_messages_key="answer"
    )

# ====================== IMAGE MODEL ======================
pipe = None
if IMAGE_RUNTIME_AVAILABLE:
    print("Loading Qwen Image...")
    try:
        pipe = DiffusionPipeline.from_pretrained(
            "Qwen/Qwen-Image-2512",
            torch_dtype=torch.bfloat16
        ).to("cuda")
        print("Image model loaded")
    except Exception as exc:
        print("Image model unavailable:", exc)
        pipe = None


def generate_image_task(prompt, path, image_id):

    try:
        if pipe is None or torch is None:
            IMAGE_STATUS[image_id] = "failed"
            return

        print(f"Starting generation for {image_id}")

        image = pipe(
            prompt=prompt,
            negative_prompt="blurry, low quality",
            width=1024,
            height=1024,
            num_inference_steps=50,
            true_cfg_scale=5.0,
            generator=torch.Generator(device="cuda").manual_seed(42)
        ).images[0]

        image.save(path)

        print(f"Image saved: {path}")

        torch.cuda.empty_cache()

        # ✅ VERY IMPORTANT
        IMAGE_STATUS[image_id] = "ready"

        print(f"Image status updated: {image_id} -> ready")

    except Exception as e:

        print("IMAGE THREAD ERROR:", e)

        IMAGE_STATUS[image_id] = "failed"

# ====================== FASTAPI ======================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

app.mount("/assets", StaticFiles(directory=IMAGE_OUTPUT_DIR), name="assets")

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    fallback_index = os.path.join(os.path.dirname(__file__), "index (3).html")

    for index_path in (INDEX_PATH, fallback_index):
        if os.path.exists(index_path):
            with open(index_path, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())

    return HTMLResponse("<h1>index.html not found</h1>", status_code=404)


@app.post("/api/chat-log")
def save_chat_log(payload: ChatLogPayload):
    chat_stack.append(payload.log_id)

    user_name = TEST_USER_NAME

    conn = get_conn()
    cur = conn.cursor()
    try:
        ts_utc = to_utc_datetime(payload.timestamp)
        cur.execute(
            """
            INSERT INTO nexa_chat_logs (log_id, user_name, user_prompt, nexa_response, timestamp_utc, stars)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                user_name = VALUES(user_name),
                user_prompt = VALUES(user_prompt),
                nexa_response = VALUES(nexa_response),
                timestamp_utc = VALUES(timestamp_utc),
                stars = VALUES(stars)
            """,
            (
                payload.log_id,
                user_name,
                payload.user_prompt,
                payload.nexa_response,
                ts_utc.strftime("%Y-%m-%d %H:%M:%S"),
                payload.stars,
            ),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()

    return {"status": "saved", "stack_size": len(chat_stack)}

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="Only PDF files are allowed")

        file_path = os.path.join(UPLOAD_DIR, file.filename)
        
        # Save file
        with open(file_path, "wb") as f:
            f.write(await file.read())

        # === ADD TO RAG VECTORSTORE ===
        if LANGCHAIN_AVAILABLE and vectorstore is not None:
            try:
                loader = PyPDFLoader(file_path)
                new_docs = loader.load()
                text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=300)
                new_splits = text_splitter.split_documents(new_docs)
                
                vectorstore.add_documents(new_splits)
                print(f"✅ Added {len(new_splits)} new chunks from: {file.filename}")
                
                global retriever
                retriever = vectorstore.as_retriever(search_kwargs={"k": 8})  # Increase k a bit
            except Exception as e:
                print(f"⚠️ Failed to add document to vectorstore: {e}")

        return JSONResponse({
            "status": "success",
            "message": f"File '{file.filename}' uploaded and learned successfully!",
            "path": file_path
        })
    except Exception as e:
        print(f"Upload error: {e}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

# ====================== DB HELPERS ======================
def get_conn():
    if mysql_connector is None:
        raise HTTPException(status_code=503, detail="MySQL connector is not installed")
    return mysql_connector.connect(**DB_CONFIG)

def to_utc_datetime(iso_str: str) -> datetime.datetime:
    try:
        parsed = datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid ISO timestamp") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)

def save_chat_to_db(log_id: str, user_prompt: str, nexa_response: str):
    """Save chat to MySQL database"""
    if mysql_connector is None:
        print("⚠️ DB logging skipped: mysql connector not installed")
        return

    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cur.execute(
            """
            INSERT INTO nexa_chat_logs 
            (log_id, user_name, user_prompt, nexa_response, timestamp_utc, stars)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                user_prompt = VALUES(user_prompt),
                nexa_response = VALUES(nexa_response),
                timestamp_utc = VALUES(timestamp_utc)
            """,
            (log_id, TEST_USER_NAME, user_prompt, nexa_response, ts, 0)
        )
        conn.commit()
        print(f"✅ Saved to DB: {log_id}")
    except Exception as e:
        print(f"⚠️ DB Save Error: {e}")
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

@app.post("/api/chat-rating")
def save_rating(payload: RatingPayload):
    conn = get_conn()
    cur = conn.cursor()
    try:
        ts_utc = to_utc_datetime(payload.timestamp)
        cur.execute(
            """
            UPDATE nexa_chat_logs
            SET stars = %s, timestamp_utc = %s
            WHERE log_id = %s
            """,
            (
                payload.stars,
                ts_utc.strftime("%Y-%m-%d %H:%M:%S"),
                payload.log_id,
            ),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()

    return {"status": "rating_saved"}


@app.post("/api/chat-log/pop")
def pop_last_log(payload: PopPayload):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM nexa_chat_logs WHERE log_id = %s", (payload.log_id,))
        conn.commit()
    finally:
        cur.close()
        conn.close()

    # Keep in-memory stack consistent when explicit log_id is removed.
    if payload.log_id in chat_stack:
        chat_stack.remove(payload.log_id)

    return {"status": "popped", "stack_size": len(chat_stack)}

# ====================== CHAT ======================
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    session_id: str
    pdf_url: Optional[str] = None
    image_url: Optional[str] = None
    image_id: Optional[str] = None

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())
    log_id = str(uuid.uuid4())

    try:
        config = {"configurable": {"session_id": session_id}}
        
        if conversational_rag_chain is None:
            answer = "Chat is available, but the curriculum model dependencies are not installed in this workspace."
        else:
            result = conversational_rag_chain.invoke(
                {"input": request.message},
                config=config
            )
            answer = result.get("answer") or "No response"

        pdf_url = None
        image_url = None
        image_id = None

        # ================= PDF GENERATION =================
        if "pdf" in request.message.lower():
            if MarkdownPdf is not None and Section is not None:
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"lesson_{ts}.pdf"
                path = os.path.join(IMAGE_OUTPUT_DIR, filename)
                pdf = MarkdownPdf()
                pdf.add_section(Section(answer))
                pdf.save(path)
                pdf_url = f"/assets/{filename}"

        # ================= IMAGE GENERATION (50 Steps) =================
        if any(k in request.message.lower() for k in ["image", "diagram", "draw", "visual", "picture", "illustration"]):
            if pipe is None:
                answer = "Image generation is not available in this workspace."
            else:
                answer = "🖼️ Generating high-quality image (50 steps)... Please wait 30-60 seconds."
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"image_{ts}.png"
                path = os.path.join(IMAGE_OUTPUT_DIR, filename)
                image_id = ts
                
                enhanced_prompt = f"{request.message}, educational diagram, clear labels, textbook style, high quality, simple background, well organized"

                # Start background generation
                threading.Thread(
                    target=generate_image_task,
                    args=(enhanced_prompt, path, image_id),
                    daemon=True
                ).start()
                
                image_url = f"/assets/{filename}"

        # Safety check
        if not answer or str(answer).strip() == "":
            answer = "Sorry, I couldn't generate a proper response. Please try again."

        # Save conversation to database
        save_chat_to_db(log_id, request.message, answer)

        return ChatResponse(
            response=answer,
            session_id=session_id,
            pdf_url=pdf_url,
            image_url=image_url,
            image_id=image_id
        )

    except Exception as e:
        print("Chat Endpoint Error:", e)
        raise HTTPException(status_code=500, detail="Server error")

@app.get("/image-status/{image_id}")
async def image_status(image_id: str):

    status = IMAGE_STATUS.get(image_id, "processing")

    return {
        "status": status
    }


@app.get("/health")
def health():
    return {"status": "ok"}

# ====================== RUN ======================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
