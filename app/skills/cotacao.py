"""
app/skills/cotacao.py  -  skill de cotacao deterministica da Ana (Lebedenco).

Padrao igual ao schedule: a Ana emite action "cotar" com os inputs, esta skill
calcula TUDO e devolve uma mensagem pronta que SUBSTITUI o output.text.
O LLM nunca escreve numero.

Fonte unica de numero. Fiel as Secoes 5/6/7 do prompt + correcoes do Luan.
>>> CONFIRMAR no topo: precos, frete, arroba, custo do ROI de leite <<<
"""
from typing import Optional

# ---- CONFIG (fonte de verdade) ----
DOSE_G_DIA = {"pasto": 10, "semi_confinado": 15, "confinado": 20}
SACOS_PRECO = {20: 540.40, 10: 283.40}
FRETE_GRATIS_MIN_KG = 60
GANHO_KG_DIA = 0.1
RENDIMENTO_CARCACA = 0.5
KG_POR_ARROBA = 15
PRECO_ARROBA_PADRAO = 300.0          # valor que o Luan passou
PRECO_KG_VIVO_RECRIA = 10.0          # R$/kg vivo (recria)
AUMENTO_LEITE = 0.03                 # +3% producao
PRECO_KG_ROI_LEITE = SACOS_PRECO[10] / 10   # 28,34 R$/kg (conservador)
DIAS_MES, DIAS_TESTE = 30, 90

LABEL_SISTEMA = {"pasto": "pasto", "semi_confinado": "semiconfinamento",
                 "confinado": "confinamento"}


# ---- nucleo de calculo ----
def consumo_kg(animais, sistema, dias):
    if sistema not in DOSE_G_DIA:
        raise ValueError("sistema invalido")
    if animais <= 0 or dias <= 0:
        raise ValueError("animais e dias > 0")
    return (DOSE_G_DIA[sistema] * dias * animais) / 1000.0


def montar_sacos(kg):
    if kg <= 0:
        raise ValueError("kg > 0")
    melhor = None
    for n20 in range(int(kg // 20) + 2 + 1):
        falta = kg - n20 * 20
        n10_ini = max(0, int(-(-falta // 10))) if falta > 0 else 0
        for n10 in range(n10_ini, n10_ini + 2):
            total = n20 * 20 + n10 * 10
            if total < kg or total == 0:
                continue
            preco = round(n20 * SACOS_PRECO[20] + n10 * SACOS_PRECO[10], 2)
            if melhor is None or (total, preco) < (melhor["total_kg"], melhor["preco"]):
                comb = [(n, k) for n, k in ((n20, 20), (n10, 10)) if n]
                melhor = {"total_kg": total, "preco": preco, "combinacao": comb}
    melhor["sobra_kg"] = round(melhor["total_kg"] - kg, 2)
    melhor["frete_gratis"] = melhor["total_kg"] >= FRETE_GRATIS_MIN_KG
    return melhor


def _ganho_recria(animais, dias):
    kg = GANHO_KG_DIA * dias * animais
    return {"receita": round(kg * PRECO_KG_VIVO_RECRIA, 2), "kg_vivo_extra": round(kg, 2)}


def _ganho_engorda(animais, dias, preco_arroba):
    kg = GANHO_KG_DIA * dias * animais
    arrobas = kg * RENDIMENTO_CARCACA / KG_POR_ARROBA
    return {"receita": round(arrobas * preco_arroba, 2), "arrobas": round(arrobas, 2),
            "kg_vivo_extra": round(kg, 2)}


def _ganho_leite(vacas, producao_L_dia, preco_leite_L, sistema, dias):
    dose = DOSE_G_DIA[sistema]
    receita = producao_L_dia * AUMENTO_LEITE * preco_leite_L * dias
    custo = (PRECO_KG_ROI_LEITE / 1000) * dose * dias
    lucro = round(receita - custo, 2)
    return {"receita_vaca_mes": round(receita, 2), "custo_vaca_mes": round(custo, 2),
            "lucro_vaca_mes": lucro, "lucro_rebanho_mes": round(lucro * vacas, 2)}


def cotacao(animais, sistema, fase, dias=DIAS_TESTE, preco_arroba=None,
            preco_leite_L=None, producao_L_dia=None):
    kg = consumo_kg(animais, sistema, dias)
    sacos = montar_sacos(kg)
    out = {"animais": animais, "sistema": sistema, "fase": fase, "dias": dias,
           "consumo_kg": round(kg, 2), "sacos": sacos,
           "investimento": sacos["preco"], "frete_gratis": sacos["frete_gratis"],
           "custo_animal_dia": round(sacos["preco"] / animais / dias, 2)}
    if fase == "recria":
        g = _ganho_recria(animais, dias)
        g["lucro_ciclo"] = round(g["receita"] - sacos["preco"], 2)
        out["ganho"] = g
    elif fase == "engorda":
        g = _ganho_engorda(animais, dias, preco_arroba or PRECO_ARROBA_PADRAO)
        g["lucro_ciclo"] = round(g["receita"] - sacos["preco"], 2)
        out["ganho"] = g
    elif fase == "leite":
        if producao_L_dia is None or preco_leite_L is None:
            raise ValueError("leite exige producao_L_dia e preco_leite_L")
        out["ganho"] = _ganho_leite(animais, producao_L_dia, preco_leite_L, sistema, dias)
    else:
        raise ValueError("fase invalida")
    return out


# ---- formatacao da mensagem (o que volta pro cliente) ----
def _r(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _sacos_label(comb):
    return " + ".join(f"{n} saco{'s' if n > 1 else ''} de {k}kg" for n, k in comb)


def _msg_corte(c):
    s, g = c["sacos"], c["ganho"]
    frete = " com frete grátis" if c["frete_gratis"] else ""
    sobra = f" Sobram {s['sobra_kg']:.0f}kg que já adiantam o próximo período." if s["sobra_kg"] else ""
    det = (f"{g['arrobas']:.0f} arrobas a mais" if c["fase"] == "engorda"
           else f"{g['kg_vivo_extra']:.0f}kg de peso vivo a mais")
    return (f"Pras suas {c['animais']} cabeças em {LABEL_SISTEMA[c['sistema']]}, a dose é "
            f"{DOSE_G_DIA[c['sistema']]}g por cabeça/dia. No protocolo de {c['dias']} dias dá "
            f"{c['consumo_kg']:.0f}kg de Multiplicação, que fecha em {_sacos_label(s['combinacao'])} "
            f"= R${_r(c['investimento'])}{frete}.{sobra} No ciclo, isso representa em torno de "
            f"R${_r(g['receita'])} de retorno ({det}), contra os R${_r(c['investimento'])} do "
            f"protocolo. Saldo de cerca de R${_r(g['lucro_ciclo'])} a favor.")


def _msg_leite(c):
    s, g = c["sacos"], c["ganho"]
    frete = " com frete grátis" if c["frete_gratis"] else ""
    sobra = f" Sobram {s['sobra_kg']:.0f}kg pro mês seguinte." if s["sobra_kg"] else ""
    return (f"Pras suas {c['animais']} vacas em {LABEL_SISTEMA[c['sistema']]}, a dose é "
            f"{DOSE_G_DIA[c['sistema']]}g por vaca/dia. Por mês dá {c['consumo_kg']:.0f}kg, que fecha "
            f"em {_sacos_label(s['combinacao'])} = R${_r(c['investimento'])}{frete}.{sobra} No retorno, "
            f"cada vaca rende em torno de R${_r(g['lucro_vaca_mes'])}/mês de lucro líquido (com o "
            f"aumento de até 3% na produção), o que dá R${_r(g['lucro_rebanho_mes'])}/mês no rebanho.")


# ---- ponto de entrada chamado pelo BaseAgent ----
def executar_cotacao(animais=None, sistema=None, fase=None, dias=90, preco_arroba=None,
                     preco_leite_L=None, producao_L_dia=None) -> dict:
    """Retorna {success, cotacao_message, dados, erro}. Erro -> action vira 'continue'."""
    if not animais or sistema not in DOSE_G_DIA or fase not in ("recria", "engorda", "leite"):
        return {"success": False, "dados": None, "cotacao_message": None,
                "erro": ("Pra fechar o número certinho, me confirma: quantos animais, qual o sistema "
                         "(pasto, semiconfinamento ou confinamento) e a fase (recria, engorda ou leite)?")}
    if fase == "leite" and (not producao_L_dia or not preco_leite_L):
        return {"success": False, "dados": None, "cotacao_message": None,
                "erro": ("Pra calcular o retorno do leite, me passa 2 coisas: quantos litros cada vaca "
                         "produz por dia hoje, e por quanto você vende o litro.")}
    try:
        c = cotacao(animais, sistema, fase, dias, preco_arroba, preco_leite_L, producao_L_dia)
    except ValueError as e:
        return {"success": False, "dados": None, "cotacao_message": None,
                "erro": f"Não consegui montar a conta ({e}). Me confirma os dados?"}
    msg = _msg_leite(c) if fase == "leite" else _msg_corte(c)
    return {"success": True, "cotacao_message": msg, "dados": c, "erro": None}


if __name__ == "__main__":
    for kwargs in [
        dict(animais=40, sistema="semi_confinado", fase="recria", dias=90),
        dict(animais=50, sistema="confinado", fase="engorda", dias=90),
        dict(animais=30, sistema="semi_confinado", fase="leite", dias=30, producao_L_dia=20, preco_leite_L=2.80),
        dict(animais=30, sistema="semi_confinado", fase="leite", dias=30),  # faltando dados
    ]:
        r = executar_cotacao(**kwargs)
        print(("OK  " if r["success"] else "ASK ") + (r["cotacao_message"] or r["erro"]))
        print()