# Welfog Custom AI Voice Calling Agent

A production-grade, real-time AI voice calling server built from scratch for **Welfog Internet Private Limited**.

The system connects live telephony calls through **TeleCMI / PIOPIY**, establishes real-time bidirectional streaming with **Google Gemini Multimodal Live API**, and performs customer-authenticated live order tracking, status lookups, refund checks, and **Qdrant RAG** knowledge base retrievals.

---

## 1. Architecture Overview

```
                        WELFOG
                           │
                     Order Trigger
                           │
                           ▼
                        TELECMI (PIOPIY)
                           │
                     Customer Phone Call
                           │
                           ▼
                        CUSTOMER
                           ↕ (PCM 16-bit 16kHz Audio)
                   FASTAPI WEBSOCKET (/ws/telecmi)
                           ↕ (Audio Resampler & Adapter)
                  GEMINI MULTIMODAL LIVE API
                         /           \
                        /             \
                       ▼               ▼
                 QDRANT RAG      WELFOG ORDER APIs
               Company Policies   History, Details,
                 FAQs & Rules     Tracking, Refunds
                       \               /
                        \             /
                         ▼           ▼
                      GEMINI VOICE RESPONSE
                           │
                           ▼
                        TELECMI
                           │
                           ▼
                        CUSTOMER
```

---

## 2. Key Components & Responsibilities

| Component | Responsibility |
|---|---|
| **Voice Orchestrator** (`app/services/voice_orchestrator.py`) | Coordinates call lifecycles, creates sessions, handles WebSockets, dispatches tool calls, and reports structured outcomes. |
| **Gemini Live Service** (`app/services/gemini_service.py`) | Connects to Google GenAI Multimodal Live API (`google-genai`), manages Hindi/Hinglish system persona, audio modalities, and function calling definitions. |
| **TeleCMI Service** (`app/services/telecmi_service.py`) | Manages TeleCMI JWT authentication (`/v2/token`), user logins (`/v2/user/login`), and PCMO outbound calls (`/v2/global_pcmo_make_call`) with `stream` action. |
| **Welfog API Service** (`app/services/welfog_service.py`) | Connects to external Welfog live endpoints with connection pooling and enforces strict customer order ownership validation. |
| **Qdrant RAG Service** (`app/services/qdrant_service.py`) | Interfaces with Welfog's vector knowledge base for return/refund policy queries and FAQs without hallucination. |
| **Audio Adapter** (`app/utils/audio.py`) | Bidirectional conversion and resampling between TeleCMI telephony audio (8kHz/16kHz linear PCM or µ-law) and Gemini Live API (16kHz in, 24kHz out). |
| **Security & Logging** (`app/utils/`) | Automatic Indian phone number normalization (`9876543210` → `919876543210`), credential masking, IDOR prevention, and structured JSON logs. |

---

## 3. Prerequisites & Requirements

- **Python**: `3.11` or `3.12` (Tested on Python 3.12.7)
- **FastAPI** `0.115+`
- **Google GenAI SDK**: `google-genai` `1.0+`
- **TeleCMI / PIOPIY Account** with active SIP trunk / App ID
- **Welfog External APIs** (Already live and accessible)
- **Public Domain or Tunnel** (e.g. `ngrok`) for TeleCMI WebSocket callbacks during local development

---

## 4. Installation & Environment Setup

### Step 1: Clone & Setup Python Virtual Environment

```bash
cd "voice calling agent"
python -m venv .venv

# On Windows (PowerShell):
.\.venv\Scripts\Activate.ps1

# On Linux / macOS:
source .venv/bin/activate
```

### Step 2: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 3: Configure `.env`

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Populate `.env` with your actual credentials:

```ini
# Gemini Configuration (Get key from Google AI Studio: https://aistudio.google.com/)
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_LIVE_MODEL=models/gemini-2.5-flash-native-audio-latest
GEMINI_VOICE_NAME=Aoede

# TeleCMI / PIOPIY Configuration
TELECMI_APP_ID=your_telecmi_app_id_here
TELECMI_APP_SECRET=your_telecmi_app_secret_here
TELECMI_SBC=sbcind.telecmi.com
TELECMI_USER_ID=your_telecmi_user_id_here
TELECMI_USER_PASSWORD=your_telecmi_user_password_here
TELECMI_REST_BASE=https://rest.telecmi.com
TELECMI_CALLER_ID=your_telecmi_caller_id_here

# Welfog Existing Order APIs
WELFOG_API_BASE=https://welfogapi.welfog.com
SUPPLIER_SERVICE_BASE=https://supplierservice.welfog.com

# Welfog Knowledge Base (Qdrant Vector DB or API)
WELFOG_KNOWLEDGE_API_URL=https://aidata.welfog.com/api/search
WELFOG_KNOWLEDGE_API_KEY=your_welfog_knowledge_api_key_here
QDRANT_URL=https://your-qdrant-cluster.qdrant.tech
QDRANT_API_KEY=your_qdrant_api_key_here
QDRANT_COLLECTION=company_knowledge

# Server & Streaming Configuration
HOST=0.0.0.0
PORT=8000
VOICE_SERVER_PUBLIC_URL=https://your-domain.ngrok-free.app
TELECMI_WEBSOCKET_URL=wss://your-domain.ngrok-free.app/ws/telecmi

ENVIRONMENT=development
LOG_LEVEL=INFO
```

---

## 5. Running the FastAPI Server

Start the development server with live reload:

```bash
.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 6. Testing Integrations & Health

### 1. Basic Liveness Check
```bash
curl http://localhost:8000/health
```
Response:
```json
{"status": "ok"}
```

### 2. Comprehensive Integrations Diagnostic
```bash
curl http://localhost:8000/health/integrations
```
Response:
```json
{
  "status": "ok",
  "integrations": {
    "telecmi": {
      "status": "connected",
      "app_id": 33338876,
      "sbc": "sbcind.telecmi.com"
    },
    "welfog_api": {
      "status": "connected",
      "base_url": "https://welfogapi.welfog.com"
    },
    "qdrant": {
      "status": "unconfigured",
      "message": "QDRANT_URL is not set"
    },
    "gemini": {
      "status": "configured",
      "live_model": "gemini-2.0-flash-exp",
      "voice": "Aoede"
    }
  }
}
```

### 3. Run Automated Pytest Suite
```bash
.venv\Scripts\pytest -v
```
Runs 20 automated unit and live integration tests covering:
- Resampling & audio encoding (PCM 16-bit 8k/16k/24k, G.711 µ-law)
- Indian phone number normalization (`9876543210` → `919876543210`)
- Order ownership security verification
- TeleCMI Token & agent login
- Welfog Purchase History & Live Order Tracking
- Controlled tool dispatching & call lifecycle state machine

---

## 7. Starting a Test Outbound Call

Ensure your server is exposed publicly (e.g. via `ngrok http 8000`) and `TELECMI_WEBSOCKET_URL` in `.env` points to `wss://<your-ngrok-subdomain>/ws/telecmi`.

Send a POST request to trigger an outbound call:

```bash
curl -X POST http://localhost:8000/api/calls/outbound \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": 1,
    "customer_phone": "9876543210",
    "order_id": "ORD100",
    "language": "Hindi"
  }'
```

Response:
```json
{
  "status": "initiated",
  "call_id": "welfog_call_3f5a2b8e90cd",
  "customer_phone": "919876543210",
  "order_id": "ORD100",
  "telecmi_call_id": "cmi_98765"
}
```

### Check Call Session & Outcome:
```bash
# In-flight session status and tool call log:
curl http://localhost:8000/api/calls/welfog_call_3f5a2b8e90cd

# Final call outcome:
curl http://localhost:8000/api/calls/welfog_call_3f5a2b8e90cd/outcome
```

---

## 8. WebSocket Audio Architecture

TeleCMI dials the customer and executes the PCMO `stream` action pointing to `/ws/telecmi?call_id=<id>`.

1. **Customer Speech**: Customer speaks on phone → TeleCMI captures audio → sends raw PCM 16-bit / µ-law audio chunks over WebSocket to FastAPI server.
2. **Audio Adapter**: Resamples audio to 16,000 Hz 16-bit linear PCM Little-Endian mono.
3. **Gemini Live**: Pushes real-time audio chunk to `gemini_session.send_realtime_input()`.
4. **AI Reasoning & Tool Calls**:
   - If customer asks *"Mera order kaha hai?"*, Gemini initiates tool call `get_order_tracking(order_id)`.
   - Backend enforces customer session context (`user_id`), calls `welfog_service.get_order_tracking()`, and returns safe structured JSON.
5. **Gemini Speech**: Gemini streams back 24,000 Hz PCM audio.
6. **Customer Audio**: Audio Adapter resamples back to TeleCMI telephony format and streams audio to customer in real-time.

---

## 9. Security & Customer Data Isolation

1. **No Arbitrary Requests**: Gemini does not have direct HTTP/network access. It can only invoke strictly defined backend tools.
2. **Order Ownership Enforcement**: Before invoice or refund details are retrieved, `verify_order_ownership` validates that the requesting `user_id` matches the order owner.
3. **Credential Masking**: All logs automatically strip sensitive keywords (`password`, `secret`, `token`, `api_key`).
4. **Phone Normalization**: Numbers are validated and normalized to strict E.164-compatible `91XXXXXXXXXX` format.

---

## 10. Production Deployment Guidelines

- **Containerization**: Deploy FastAPI behind an ASGI server (`uvicorn` with multiple workers or `gunicorn -k uvicorn.workers.UvicornWorker`).
- **TLS/WSS**: Always terminate SSL at an Application Load Balancer or reverse proxy (Nginx / Cloudflare) so TeleCMI connects via secure `wss://`.
- **Monitoring**: Structured JSON logs are emitted on stdout for seamless aggregation in Datadog, CloudWatch, or ELK.
