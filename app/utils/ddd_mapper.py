"""Map Brazilian phone DDDs to city/state/country."""
from __future__ import annotations

import re

# All 67 Brazilian DDDs → main city, state, country
DDD_MAP: dict[str, dict[str, str]] = {
    # São Paulo
    "11": {"city": "São Paulo", "state": "SP", "country": "Brasil"},
    "12": {"city": "São José dos Campos", "state": "SP", "country": "Brasil"},
    "13": {"city": "Santos", "state": "SP", "country": "Brasil"},
    "14": {"city": "Bauru", "state": "SP", "country": "Brasil"},
    "15": {"city": "Sorocaba", "state": "SP", "country": "Brasil"},
    "16": {"city": "Ribeirão Preto", "state": "SP", "country": "Brasil"},
    "17": {"city": "São José do Rio Preto", "state": "SP", "country": "Brasil"},
    "18": {"city": "Presidente Prudente", "state": "SP", "country": "Brasil"},
    "19": {"city": "Campinas", "state": "SP", "country": "Brasil"},
    # Rio de Janeiro
    "21": {"city": "Rio de Janeiro", "state": "RJ", "country": "Brasil"},
    "22": {"city": "Campos dos Goytacazes", "state": "RJ", "country": "Brasil"},
    "24": {"city": "Volta Redonda", "state": "RJ", "country": "Brasil"},
    # Espírito Santo
    "27": {"city": "Vitória", "state": "ES", "country": "Brasil"},
    "28": {"city": "Cachoeiro de Itapemirim", "state": "ES", "country": "Brasil"},
    # Minas Gerais
    "31": {"city": "Belo Horizonte", "state": "MG", "country": "Brasil"},
    "32": {"city": "Juiz de Fora", "state": "MG", "country": "Brasil"},
    "33": {"city": "Governador Valadares", "state": "MG", "country": "Brasil"},
    "34": {"city": "Uberlândia", "state": "MG", "country": "Brasil"},
    "35": {"city": "Poços de Caldas", "state": "MG", "country": "Brasil"},
    "37": {"city": "Divinópolis", "state": "MG", "country": "Brasil"},
    "38": {"city": "Montes Claros", "state": "MG", "country": "Brasil"},
    # Paraná
    "41": {"city": "Curitiba", "state": "PR", "country": "Brasil"},
    "42": {"city": "Ponta Grossa", "state": "PR", "country": "Brasil"},
    "43": {"city": "Londrina", "state": "PR", "country": "Brasil"},
    "44": {"city": "Maringá", "state": "PR", "country": "Brasil"},
    "45": {"city": "Foz do Iguaçu", "state": "PR", "country": "Brasil"},
    "46": {"city": "Francisco Beltrão", "state": "PR", "country": "Brasil"},
    # Santa Catarina
    "47": {"city": "Joinville", "state": "SC", "country": "Brasil"},
    "48": {"city": "Florianópolis", "state": "SC", "country": "Brasil"},
    "49": {"city": "Chapecó", "state": "SC", "country": "Brasil"},
    # Rio Grande do Sul
    "51": {"city": "Porto Alegre", "state": "RS", "country": "Brasil"},
    "53": {"city": "Pelotas", "state": "RS", "country": "Brasil"},
    "54": {"city": "Caxias do Sul", "state": "RS", "country": "Brasil"},
    "55": {"city": "Santa Maria", "state": "RS", "country": "Brasil"},
    # Distrito Federal / Goiás
    "61": {"city": "Brasília", "state": "DF", "country": "Brasil"},
    "62": {"city": "Goiânia", "state": "GO", "country": "Brasil"},
    "64": {"city": "Rio Verde", "state": "GO", "country": "Brasil"},
    # Tocantins
    "63": {"city": "Palmas", "state": "TO", "country": "Brasil"},
    # Mato Grosso do Sul
    "67": {"city": "Campo Grande", "state": "MS", "country": "Brasil"},
    # Mato Grosso
    "65": {"city": "Cuiabá", "state": "MT", "country": "Brasil"},
    "66": {"city": "Rondonópolis", "state": "MT", "country": "Brasil"},
    # Acre
    "68": {"city": "Rio Branco", "state": "AC", "country": "Brasil"},
    # Rondônia
    "69": {"city": "Porto Velho", "state": "RO", "country": "Brasil"},
    # Amazonas
    "92": {"city": "Manaus", "state": "AM", "country": "Brasil"},
    "97": {"city": "Coari", "state": "AM", "country": "Brasil"},
    # Roraima
    "95": {"city": "Boa Vista", "state": "RR", "country": "Brasil"},
    # Pará
    "91": {"city": "Belém", "state": "PA", "country": "Brasil"},
    "93": {"city": "Santarém", "state": "PA", "country": "Brasil"},
    "94": {"city": "Marabá", "state": "PA", "country": "Brasil"},
    # Amapá
    "96": {"city": "Macapá", "state": "AP", "country": "Brasil"},
    # Maranhão
    "98": {"city": "São Luís", "state": "MA", "country": "Brasil"},
    "99": {"city": "Imperatriz", "state": "MA", "country": "Brasil"},
    # Piauí
    "86": {"city": "Teresina", "state": "PI", "country": "Brasil"},
    "89": {"city": "Picos", "state": "PI", "country": "Brasil"},
    # Ceará
    "85": {"city": "Fortaleza", "state": "CE", "country": "Brasil"},
    "88": {"city": "Juazeiro do Norte", "state": "CE", "country": "Brasil"},
    # Rio Grande do Norte
    "84": {"city": "Natal", "state": "RN", "country": "Brasil"},
    # Paraíba
    "83": {"city": "João Pessoa", "state": "PB", "country": "Brasil"},
    # Pernambuco
    "81": {"city": "Recife", "state": "PE", "country": "Brasil"},
    "87": {"city": "Petrolina", "state": "PE", "country": "Brasil"},
    # Alagoas
    "82": {"city": "Maceió", "state": "AL", "country": "Brasil"},
    # Sergipe
    "79": {"city": "Aracaju", "state": "SE", "country": "Brasil"},
    # Bahia
    "71": {"city": "Salvador", "state": "BA", "country": "Brasil"},
    "73": {"city": "Ilhéus", "state": "BA", "country": "Brasil"},
    "74": {"city": "Juazeiro", "state": "BA", "country": "Brasil"},
    "75": {"city": "Feira de Santana", "state": "BA", "country": "Brasil"},
    "77": {"city": "Vitória da Conquista", "state": "BA", "country": "Brasil"},
}


def get_location_from_phone(phone: str) -> dict[str, str] | None:
    """Extract DDD from a Brazilian phone and return location info.

    Handles: "5518996597391", "+5518996597391", "18996597391"
    Returns: {"city": "...", "state": "...", "country": "Brasil"} or None
    """
    if not phone:
        return None

    digits = re.sub(r"\D", "", phone)
    if not digits:
        return None

    # Remove country code 55
    if digits.startswith("55") and len(digits) >= 12:
        digits = digits[2:]

    # DDD (2 digits) + number (8-9 digits) = 10-11 digits
    if len(digits) >= 10:
        ddd = digits[:2]
        return DDD_MAP.get(ddd)

    return None
