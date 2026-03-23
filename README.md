# LORDS AI Agents

AI agents (SDR + Support) for WhatsApp conversations via Chatwoot.

## Quick Start

```bash
# 1. Clone and setup
cd D:\SaaS\lords-ai
python -m venv venv
venv\Scripts\activate  # Windows

# 2. Install
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Edit .env with real values

# 4. Run Redis + ChromaDB
docker run -d --name lords-redis -p 6379:6379 redis:7-alpine
docker run -d --name lords-chromadb -p 8000:8000 chromadb/chroma:latest

# 5. Start
uvicorn app.main:app --reload --port 8100

# 6. Test
curl http://localhost:8100/health
```

## Docker

```bash
docker compose up --build
```

## Tests

```bash
pytest -v
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | Health check |
| POST | /api/v1/process-message | Process incoming message |
| POST | /api/v1/knowledge/upload | Upload knowledge document |
| GET | /api/v1/knowledge/search | Search knowledge base |
| GET | /api/v1/agents/status | Agent status |
| POST | /api/v1/agents/pause | Kill switch |
| POST | /api/v1/agents/resume | Resume agents |
| GET | /api/v1/logs | Conversation logs |
| GET | /api/v1/metrics | Aggregated metrics |
