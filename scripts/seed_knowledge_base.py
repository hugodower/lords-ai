#!/usr/bin/env python3
"""
Seed ChromaDB knowledge base for Lords Ads (Aurora SDR).

Usage:
  # Local (ChromaDB at localhost:8000):
  python scripts/seed_knowledge_base.py

  # Custom ChromaDB URL:
  CHROMA_URL=http://lords-chromadb:8000 python scripts/seed_knowledge_base.py

  # Inside Docker (via docker exec):
  docker exec -it <container> python scripts/seed_knowledge_base.py
"""
from __future__ import annotations

import os
import sys

# ── Config ──────────────────────────────────────────────────────────
ORG_ID = "cc000000-0000-0000-0000-000000000001"
CHROMA_URL = os.environ.get("CHROMA_URL", "http://localhost:8000")

# ── Documents ───────────────────────────────────────────────────────
DOCUMENTS: list[dict] = [
    # ── SERVIÇOS ────────────────────────────────────────────────────
    {
        "name": "servico_central_multiatendimento",
        "category": "servicos",
        "content": (
            "Central de Multiatendimento — A Lords Ads oferece uma Central de "
            "Multiatendimento completa com CRM integrado ao WhatsApp oficial "
            "(API Cloud), Instagram, Messenger e chat do site. Cada cliente "
            "recebe sua própria infraestrutura dedicada, nada compartilhado. "
            "Inclui pipeline de vendas, gestão de contatos, automações e "
            "relatórios. Ideal para empresas que atendem muitos clientes pelo "
            "WhatsApp e precisam organizar o atendimento com múltiplos atendentes."
        ),
    },
    {
        "name": "servico_trafego_pago",
        "category": "servicos",
        "content": (
            "Gestão de Tráfego Pago — Gerenciamento profissional de campanhas "
            "no Meta Ads (Facebook e Instagram) e Google Ads. Estratégias "
            "personalizadas para cada negócio, com otimização contínua baseada "
            "em dados reais. Foco em geração de leads qualificados e ROI "
            "mensurável."
        ),
    },
    {
        "name": "servico_landing_pages",
        "category": "servicos",
        "content": (
            "Landing Pages Otimizadas — Criação de páginas de captura e vendas "
            "otimizadas para conversão. Design profissional, responsivo, com "
            "formulários integrados e rastreamento de conversões. Feitas sob "
            "medida para cada campanha e segmento."
        ),
    },
    {
        "name": "servico_ia_aurora",
        "category": "servicos",
        "content": (
            "IA Aurora (SDR Automatizado) — Assistente virtual inteligente que "
            "atende leads 24/7 no WhatsApp. Qualifica leads automaticamente, "
            "responde dúvidas, e agenda reuniões. Funciona como uma "
            "pré-vendedora incansável que nunca perde um lead."
        ),
    },
    {
        "name": "servico_disparos_massa",
        "category": "servicos",
        "content": (
            "Disparos em Massa — Envio de mensagens em massa pelo WhatsApp "
            "oficial (API Cloud da Meta), sem risco de bloqueio. Templates "
            "aprovados pela Meta, segmentação por público, e relatórios de "
            "entrega. Ideal para campanhas promocionais, avisos e reativação "
            "de base."
        ),
    },
    {
        "name": "servico_aplicativos",
        "category": "servicos",
        "content": (
            "Criação de Aplicativos — Desenvolvimento de aplicativos e sistemas "
            "web personalizados. Desde ERPs para nichos específicos até "
            "plataformas SaaS completas. Tecnologia moderna com foco em "
            "usabilidade e performance."
        ),
    },
    {
        "name": "servico_consultoria_b2b",
        "category": "servicos",
        "content": (
            "Consultoria B2B — Consultoria estratégica para empresas que querem "
            "estruturar seus processos de vendas, marketing digital e "
            "atendimento ao cliente. Diagnóstico completo e plano de ação "
            "personalizado."
        ),
    },
    {
        "name": "servico_automacoes",
        "category": "servicos",
        "content": (
            "Automações Personalizadas — Criação de fluxos automatizados sob "
            "medida usando integrações entre ferramentas (CRM, WhatsApp, "
            "e-mail, planilhas, etc). Elimina trabalho manual repetitivo e "
            "aumenta a eficiência operacional."
        ),
    },
    # ── DIFERENCIAIS ────────────────────────────────────────────────
    {
        "name": "diferencial_personalizado",
        "category": "diferenciais",
        "content": (
            "Tudo personalizado, nada genérico — A Lords Ads não trabalha com "
            "soluções de prateleira. Cada cliente recebe uma estratégia única, "
            "infraestrutura dedicada e atendimento exclusivo. Não usamos "
            "ferramentas compartilhadas — cada empresa tem seu próprio ambiente."
        ),
    },
    {
        "name": "diferencial_tecnologia_propria",
        "category": "diferenciais",
        "content": (
            "Tecnologia própria — Desenvolvemos nossas próprias ferramentas "
            "(CRM, IA, automações). Isso nos dá total controle para adaptar a "
            "solução exatamente ao que o cliente precisa."
        ),
    },
    {
        "name": "diferencial_infraestrutura_dedicada",
        "category": "diferenciais",
        "content": (
            "Infraestrutura dedicada — Diferente de concorrentes que colocam "
            "todos os clientes no mesmo sistema, cada cliente Lords Ads tem "
            "seu próprio servidor, sua própria instância. Mais segurança, mais "
            "performance, mais exclusividade."
        ),
    },
    # ── OBJEÇÕES ────────────────────────────────────────────────────
    {
        "name": "objecao_preco_caro",
        "category": "objecoes",
        "content": (
            "Objeção: está caro, o preço é alto — Resposta: Entendo sua "
            "preocupação com o investimento! O valor varia bastante dependendo "
            "da solução que faz mais sentido pro seu negócio. Na reunião de "
            "diagnóstico o Hugo vai entender sua situação e montar uma "
            "proposta personalizada que caiba no seu orçamento. Muitos clientes "
            "ficam surpresos com o custo-benefício quando veem tudo que está "
            "incluso. Posso agendar esse bate-papo pra você?"
        ),
    },
    {
        "name": "objecao_ja_usa_outra",
        "category": "objecoes",
        "content": (
            "Objeção: já uso outra ferramenta — Resposta: Que bom que você já "
            "usa alguma solução! O diferencial da Lords Ads é que tudo é "
            "personalizado pro seu negócio — nada genérico. Na reunião de "
            "diagnóstico o Hugo pode avaliar o que você usa hoje e mostrar "
            "como podemos complementar ou até melhorar o que você já tem, sem "
            "necessariamente trocar tudo. Vale a conversa?"
        ),
    },
    {
        "name": "objecao_nao_sei_se_funciona",
        "category": "objecoes",
        "content": (
            "Objeção: não sei se funciona pro meu negócio — Resposta: Essa é "
            "uma preocupação válida! Por isso a reunião de diagnóstico é tão "
            "importante — o Hugo vai analisar seu negócio específico e só "
            "recomendar o que realmente faz sentido pra você. Não empurramos "
            "soluções, a gente constrói junto. Que tal agendar pra tirar "
            "essa dúvida?"
        ),
    },
    {
        "name": "objecao_consultar_socio",
        "category": "objecoes",
        "content": (
            "Objeção: preciso consultar meu sócio/parceiro — Resposta: Claro, "
            "é importante tomar essa decisão junto! Que tal já agendarmos a "
            "reunião de diagnóstico com seu sócio junto? Assim os dois escutam "
            "direto do Hugo como podemos ajudar e decidem juntos. Qual seria "
            "o melhor horário pra vocês dois?"
        ),
    },
    # ── POLÍTICA DE PREÇOS ──────────────────────────────────────────
    {
        "name": "politica_precos",
        "category": "precos",
        "content": (
            "Política de preços — A Aurora NUNCA deve informar preços "
            "específicos. Quando perguntarem sobre valores, custos, preços, "
            "quanto custa, qual o investimento, ou qualquer variação, a Aurora "
            "deve responder algo como: O investimento varia de acordo com a "
            "solução ideal pro seu negócio. Na reunião de diagnóstico o Hugo "
            "faz uma análise completa e monta uma proposta personalizada pra "
            "você. Posso agendar?"
        ),
    },
    # ── FAQ ──────────────────────────────────────────────────────────
    {
        "name": "faq_como_funciona",
        "category": "faq",
        "content": (
            "Como funciona o atendimento? — Primeiro fazemos uma reunião de "
            "diagnóstico gratuita para entender suas necessidades. Depois "
            "montamos uma proposta personalizada. Após aprovação, a "
            "implementação começa imediatamente com acompanhamento próximo."
        ),
    },
    {
        "name": "faq_contrato",
        "category": "faq",
        "content": (
            "Tem contrato de fidelidade? — Os detalhes sobre contrato e "
            "condições são discutidos na reunião de diagnóstico com o Hugo, "
            "pois variam de acordo com o serviço contratado."
        ),
    },
    {
        "name": "faq_prazo",
        "category": "faq",
        "content": (
            "Quanto tempo leva para implementar? — O prazo depende da "
            "complexidade da solução. Na reunião de diagnóstico o Hugo "
            "consegue dar uma estimativa precisa para o seu caso."
        ),
    },
    {
        "name": "faq_regiao",
        "category": "faq",
        "content": (
            "Atendem qual região? — A Lords Ads atende empresas de todo o "
            "Brasil. Nossos serviços são 100% digitais, então não importa "
            "onde você esteja."
        ),
    },
    {
        "name": "faq_contato",
        "category": "faq",
        "content": (
            "Como entro em contato? — Você pode falar comigo aqui pelo "
            "WhatsApp mesmo! Se preferir, posso agendar uma reunião com o "
            "Hugo para um atendimento mais aprofundado."
        ),
    },
]


def main():
    import chromadb

    # Parse host/port from URL
    url = CHROMA_URL.rstrip("/")
    host = url.replace("http://", "").replace("https://", "")
    port = 8000
    if ":" in host:
        host, port_str = host.rsplit(":", 1)
        port = int(port_str)

    print(f"[SEED] Connecting to ChromaDB at {host}:{port} ...")
    client = chromadb.HttpClient(host=host, port=port)
    client.heartbeat()
    print("[SEED] ChromaDB connected OK")

    # Collection name follows rag.py convention
    safe_org = ORG_ID.replace("-", "_")
    collection_name = f"org_{safe_org}"

    # Fresh start — delete existing collection
    try:
        client.delete_collection(name=collection_name)
        print(f"[SEED] Deleted existing collection '{collection_name}'")
    except Exception:
        print(f"[SEED] No existing collection '{collection_name}' (fresh)")

    collection = client.get_or_create_collection(name=collection_name)
    print(f"[SEED] Created collection '{collection_name}'")

    # Chunk and insert each document
    total_chunks = 0
    for doc in DOCUMENTS:
        name = doc["name"]
        category = doc["category"]
        content = doc["content"]

        # Chunk using same logic as embeddings.py (500 chars, 50 overlap)
        chunks = []
        start = 0
        chunk_size = 500
        overlap = 50
        while start < len(content):
            end = start + chunk_size
            chunk = content[start:end].strip()
            if chunk:
                chunks.append(chunk)
            start = end - overlap

        if not chunks:
            print(f"  [SKIP] {name} — empty content")
            continue

        ids = [f"{name}_{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "source": name,
                "org_id": ORG_ID,
                "category": category,
                "chunk": i,
            }
            for i in range(len(chunks))
        ]

        collection.upsert(ids=ids, documents=chunks, metadatas=metadatas)
        total_chunks += len(chunks)
        print(f"  [OK] {name} ({category}) — {len(chunks)} chunk(s)")

    print(f"\n[SEED] Done! Inserted {total_chunks} chunks across {len(DOCUMENTS)} documents.")
    print(f"[SEED] Collection '{collection_name}' now has {collection.count()} items.\n")

    # ── Smoke test ──────────────────────────────────────────────────
    print("[TEST] Semantic search: 'quanto custa'")
    results = collection.query(query_texts=["quanto custa"], n_results=3)
    for i, doc in enumerate(results["documents"][0]):
        meta = results["metadatas"][0][i]
        dist = results["distances"][0][i] if results.get("distances") else "?"
        print(f"  #{i+1} [{meta.get('category')}] {meta.get('source')} (dist={dist:.4f})")
        print(f"       {doc[:120]}...")

    print("\n[TEST] Semantic search: 'vocês fazem site'")
    results = collection.query(query_texts=["vocês fazem site"], n_results=3)
    for i, doc in enumerate(results["documents"][0]):
        meta = results["metadatas"][0][i]
        dist = results["distances"][0][i] if results.get("distances") else "?"
        print(f"  #{i+1} [{meta.get('category')}] {meta.get('source')} (dist={dist:.4f})")
        print(f"       {doc[:120]}...")

    print("\n[TEST] Semantic search: 'já uso outro sistema'")
    results = collection.query(query_texts=["já uso outro sistema"], n_results=3)
    for i, doc in enumerate(results["documents"][0]):
        meta = results["metadatas"][0][i]
        dist = results["distances"][0][i] if results.get("distances") else "?"
        print(f"  #{i+1} [{meta.get('category')}] {meta.get('source')} (dist={dist:.4f})")
        print(f"       {doc[:120]}...")

    print("\n[SEED] All done! Knowledge base ready for Aurora.")


if __name__ == "__main__":
    main()
