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

## Configuration

### Environment Variables

Key configuration options in `.env`:

```bash
# Organization
ORG_ID=cc000000-0000-0000-0000-000000000001

# Supabase (CRM)
SUPABASE_URL=https://yourproject.supabase.co
SUPABASE_SERVICE_KEY=eyJ...

# Claude API
CLAUDE_API_KEY=sk-ant-xxxxx

# Chatwoot
CHATWOOT_URL=https://chatwoot.yourcompany.com
CHATWOOT_API_TOKEN=xxxxx
CHATWOOT_ACCOUNT_ID=1

# Follow-up Worker (disable automatic follow-ups)
FOLLOWUP_WORKER_ENABLED=true  # Set to false in production to disable
```

### Follow-up Worker

The follow-up worker sends automatic messages (24h, 48h, 7d) when leads don't respond.

- **Default**: Enabled (`FOLLOWUP_WORKER_ENABLED=true`)
- **Production**: Often disabled (`FOLLOWUP_WORKER_ENABLED=false`) for strategic follow-up design
- **Development**: Keep enabled for testing

When disabled, the worker runs in idle mode without processing or sending follow-ups.
