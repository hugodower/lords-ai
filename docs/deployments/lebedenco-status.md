# Lebedenco Agro — Status Deploy Multi-tenant

### Lebedenco Agro — Status Deploy (05/mai/26)

**Estado:** Etapas A-E concluídas. Etapa F (smoke test) pendente.

**Endpoints:**
- App: `https://ai.lebedencoagro.uk` (SSL Let's Encrypt OK)
- Health: `https://ai.lebedencoagro.uk/health` →
  `{"status":"ok","org_id":"31ddcc20-868c-4988-9326-e15d7a27d06f","agents_active":["sdr"],"redis":"connected","chroma":"connected"}`

**Infraestrutura:**
- VPS: Lebedenco (Portainer em `port.lebedencoagro.uk`)
- Stack name: `lords-ai`
- Image: `ghcr.io/hugodower/lords-ai:latest`
- Replicas: 1
- Network: `vps` (Traefik) + `lords-network` (interno)
- Serviços auxiliares: `lords-redis` (redis:7-alpine), `lords-chromadb` (chromadb/chroma:0.5.23)

**Configuração relevante:**
- `SANDBOX_MODE=true`
- `SANDBOX_PHONES`: +5518996010895, +5518981550333, +5518991023817
- `MAX_RESPONSE_TIME_SECONDS=10`
- `CHATWOOT_URL`: `https://chatw.lebedencoagro.uk`
- `CHATWOOT_ACCOUNT_ID`: 1
- `GOOGLE_CLIENT_ID/SECRET`: vazios (Calendar OAuth ainda não configurado)
- `CHATWOOT_WEBHOOK_SECRET`: NÃO configurado (lords-ai não valida HMAC)

**Webhooks Chatwoot Lebedenco (estado atual):**

| # | Nome | URL | Eventos |
|---|---|---|---|
| 1 | CRM LORDS | `https://www.lordsads.com.br/api/webhooks/chatwoot-events?token=...` | Todos |
| 2 | Ana - lords-ai (SDR) | `https://ai.lebedencoagro.uk/api/v1/webhook/chatwoot` | conversation_created, conversation_updated, message_created |

**Bugs corrigidos durante o deploy:**
1. `REDIS_URL` tinha trailing space (`redis://lords-redis:6379 `),
   causando "Port could not be cast to integer" e fallback para in-memory
2. `CLAUDE_API_KEY` estava com valor placeholder literal
   (`COLE_AQUI_A_KEY_NOVA_ROTACIONADA`) — substituída pela key real
3. `SUPABASE_SERVICE_KEY` estava inválida — rotacionada no Supabase Dashboard
   (chave antiga foi exposta inadvertidamente em ambiente de chat)

**Pendências conhecidas:**
- [ ] Etapa F: smoke test end-to-end (Ana respondendo no WhatsApp)
- [ ] Bug "John Doe" persiste — webhook CRM LORDS antigo ainda recebe
      eventos da Lebedenco. Decisão pendente: deletar ou repointar
      para endpoint que processe corretamente o payload
- [ ] Rotacionar `CHATWOOT_API_TOKEN` da Lebedenco (security debt)
- [ ] Configurar Google Calendar OAuth para Lebedenco (Item 3 lords-ai global)

**Diferenças vs. deploy LORDS Ads (referência):**
- Org: Lebedenco usa nome "Ana" (config no Supabase via tabela
  `organization_agents` ou similar — verificar)
- Sandbox phones diferentes
- Mantém webhook legado CRM LORDS ativo (LORDS deploy não tem essa duplicação)