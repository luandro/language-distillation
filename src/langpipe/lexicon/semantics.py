"""Pivot-Side Grammatical Valence & Semantic Domain Induction (WP 1.2).

Classifies dictionary lemmas into formal grammatical valence categories
(transitive, intransitive, ditransitive, inalienable nominals) and SIL RapidWords
semantic domains based exclusively on contact-language pivot glosses (e.g. Portuguese).

Adheres strictly to:
- Invariant 10 & ADR-0006 (Zero target-language egress to third-party models).
- AGENTS.md language isolation (Language-agnostic generic pipeline code).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class GrammaticalValence(StrEnum):
    """Linguistic valence indicating required argument structure for predicates."""

    TRANSITIVE = "transitive"  # Vt: requires Agent (ERG) + Patient (ABS)
    INTRANSITIVE = "intransitive"  # Vi: requires single Subject (ABS)
    DITRANSITIVE = "ditransitive"  # Vd: requires Agent + Patient + Recipient/Goal
    AMBITRANSITIVE = "ambitransitive"  # Can act as transitive or intransitive
    NON_VERBAL = "non_verbal"  # Nouns, Adjectives, Particles
    UNKNOWN = "unknown"


class NounInalienability(StrEnum):
    """Inherent alienability distinction for nominals (crucial in indigenous typology)."""

    ALIENABLE = "alienable"  # Free goods, artifacts, game
    INALIENABLE_BODY = "inalienable_body"  # Anatomical body parts (obligatorily possessed)
    INALIENABLE_KIN = "inalienable_kin"  # Kinship terms (obligatorily possessed)
    NOT_APPLICABLE = "not_applicable"


class SemanticDomain(StrEnum):
    """Standardized Semantic Domains (adapted from SIL RapidWords taxonomy)."""

    UNIVERSE_NATURE = "universe_nature"  # Sky, weather, river, earth, sun, celestial
    FAUNA = "fauna"  # Animals, mammals, fish, birds, insects
    FLORA = "flora"  # Plants, trees, fruits, cultivars, seeds
    BODY_HEALTH = "body_health"  # Body parts, fluids, sensation, illness
    KINSHIP_SOCIAL = "kinship_social"  # Kinship, community, people, leadership
    ARTIFACTS_TOOLS = "artifacts_tools"  # Canoes, hammocks, weapons, pottery, shelter
    FOOD_SUSTENANCE = "food_sustenance"  # Meat, drinks, culinary preparation
    ACTIONS_MOTION = "actions_motion"  # Locomotion, travel, bodily actions
    PERCEPTION_MIND = "perception_mind"  # Visual, auditory, cognition, emotions
    QUANTITY_STATE = "quantity_state"  # Numerals, dimensions, colors, qualifiers
    GENERAL = "general"


@dataclass
class SemanticProfile:
    """Rich semantic and grammatical classification for a dictionary entry."""

    valence: GrammaticalValence = GrammaticalValence.UNKNOWN
    inalienability: NounInalienability = NounInalienability.NOT_APPLICABLE
    primary_domain: SemanticDomain = SemanticDomain.GENERAL
    subdomains: list[str] = field(default_factory=list)
    confidence: float = 1.0
    rationale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valence": self.valence.value,
            "inalienability": self.inalienability.value,
            "primary_domain": self.primary_domain.value,
            "subdomains": self.subdomains,
            "confidence": self.confidence,
            "rationale": self.rationale,
        }


class PivotSemanticsClassifier:
    """Deterministic, high-precision semantic and valence classifier for pivot glosses."""

    # --- Lexical Wordlists for Portuguese Pivot ---

    INTRANSITIVE_VERBS = frozenset(
        {
            "ir",
            "vir",
            "caminhar",
            "andar",
            "correr",
            "voar",
            "nadar",
            "pular",
            "saltar",
            "cair",
            "tombar",
            "deitar",
            "sentar",
            "levantar",
            "ficar",
            "dormir",
            "acordar",
            "morrer",
            "nascer",
            "chegar",
            "sair",
            "entrar",
            "voltar",
            "partir",
            "descer",
            "subir",
            "parar",
            "chorar",
            "rir",
            "sorrir",
            "gritar",
            "brilhar",
            "secar",
            "queimar",
            "apodrecer",
            "tremer",
            "fugir",
            "viver",
            "existir",
            "cansar",
            "adoecer",
            "sumir",
            "desaparecer",
            "amanhecer",
            "anoitecer",
        }
    )

    DITRANSITIVE_VERBS = frozenset(
        {
            "dar",
            "entregar",
            "mostrar",
            "ensinar",
            "contar",
            "dizer",
            "falar",
            "pedir",
            "oferecer",
            "enviar",
            "mandar",
            "doar",
        }
    )

    TRANSITIVE_VERBS = frozenset(
        {
            "comer",
            "beber",
            "matar",
            "caçar",
            "pescar",
            "ver",
            "enxergar",
            "olhar",
            "ouvir",
            "escutar",
            "pintar",
            "desenhar",
            "fazer",
            "agir",
            "criar",
            "construir",
            "quebrar",
            "cortar",
            "tecer",
            "costurar",
            "cozinhar",
            "assar",
            "ferver",
            "moer",
            "lavar",
            "limpar",
            "morder",
            "mastigar",
            "engolir",
            "carregar",
            "segurar",
            "pegar",
            "apanhar",
            "erguer",
            "puxar",
            "empurrar",
            "soltar",
            "deixar",
            "abrir",
            "fechar",
            "comprar",
            "vender",
            "trocar",
            "esconder",
            "procurar",
            "achar",
            "encontrar",
            "plantar",
            "colher",
            "bater",
            "ferir",
            "roubar",
            "amar",
            "odiar",
            "temer",
        }
    )

    BODY_PARTS = frozenset(
        {
            "cabeça",
            "olho",
            "olhos",
            "orelha",
            "orelhas",
            "nariz",
            "boca",
            "dente",
            "dentes",
            "língua",
            "mão",
            "mãos",
            "braço",
            "braços",
            "perna",
            "pernas",
            "pé",
            "pés",
            "osso",
            "ossos",
            "carne",
            "sangue",
            "pele",
            "casca",
            "unha",
            "unhas",
            "cabelo",
            "cabelos",
            "pelo",
            "pelos",
            "coração",
            "fígado",
            "pulmão",
            "barriga",
            "ventre",
            "costela",
            "pescoço",
            "costas",
            "corpo",
            "rosto",
            "face",
            "joelho",
            "cotovelo",
            "ombro",
            "coxa",
            "garganta",
            "rabo",
            "cauda",
            "asa",
            "asas",
            "bico",
        }
    )

    KINSHIP = frozenset(
        {
            "pai",
            "mãe",
            "filho",
            "filha",
            "irmão",
            "irmã",
            "avô",
            "avó",
            "neto",
            "neta",
            "tio",
            "tia",
            "primo",
            "prima",
            "cunhado",
            "cunhada",
            "sogro",
            "sogra",
            "genro",
            "nora",
            "esposo",
            "esposa",
            "marido",
            "mulher",
            "parente",
            "parentes",
            "clã",
            "família",
            "criança",
            "menino",
            "menina",
            "gente",
            "pessoa",
            "povo",
            "homem",
            "velho",
            "ancião",
            "pajé",
            "xamã",
            "amigo",
            "inimigo",
            "forasteiro",
            "estranho",
        }
    )

    FAUNA = frozenset(
        {
            "onça",
            "jaguar",
            "macaco",
            "coatá",
            "sauim",
            "peixe",
            "jacaré",
            "anta",
            "veado",
            "queixada",
            "caititu",
            "cutia",
            "paca",
            "tatu",
            "preguiça",
            "tamanduá",
            "pássaro",
            "ave",
            "gavião",
            "arara",
            "papagaio",
            "mutum",
            "jacu",
            "cobra",
            "serpente",
            "sucuri",
            "jibóia",
            "sapo",
            "rã",
            "tartaruga",
            "jabuti",
            "aranha",
            "formiga",
            "abelha",
            "vespa",
            "mosquito",
            "borboleta",
            "larva",
            "verme",
            "caracol",
            "cachorro",
            "cão",
            "galinha",
            "galo",
            "porco",
            "rato",
            "morcego",
            "bicho",
            "animal",
        }
    )

    FLORA = frozenset(
        {
            "árvore",
            "madeira",
            "pau",
            "tronco",
            "galho",
            "folha",
            "folhas",
            "flor",
            "flores",
            "fruto",
            "fruta",
            "semente",
            "raíz",
            "raiz",
            "cipó",
            "palmeira",
            "açaí",
            "buriti",
            "pupunha",
            "bacaba",
            "patauá",
            "milho",
            "mandioca",
            "macaxeira",
            "algodão",
            "tabaco",
            "jenipapo",
            "urucum",
            "banana",
            "abacaxi",
            "capim",
            "erva",
            "mato",
            "vegetal",
            "planta",
        }
    )

    ARTIFACTS = frozenset(
        {
            "canoa",
            "barco",
            "remo",
            "rede",
            "arco",
            "flecha",
            "borduna",
            "lança",
            "facão",
            "faca",
            "machado",
            "cuia",
            "tigela",
            "pote",
            "vaso",
            "cesto",
            "panela",
            "casa",
            "maloca",
            "aldeia",
            "choupana",
            "roupa",
            "veste",
            "esteira",
            "banco",
            "cerâmica",
            "miçanga",
            "enfeite",
            "cocada",
            "armadilha",
            "caminho",
            "trilha",
            "porto",
            "ferramenta",
        }
    )

    NATURE = frozenset(
        {
            "rio",
            "igarapé",
            "lago",
            "água",
            "chuva",
            "terra",
            "chão",
            "lama",
            "barro",
            "areia",
            "pedra",
            "rocha",
            "montanha",
            "morro",
            "céu",
            "sol",
            "lua",
            "estrela",
            "estrelas",
            "nuvem",
            "vento",
            "trovão",
            "relâmpago",
            "fogo",
            "brasa",
            "cinza",
            "fumaça",
            "noite",
            "dia",
            "madrugada",
            "luz",
            "escuridão",
            "mata",
            "floresta",
            "selva",
            "praia",
            "barranco",
        }
    )

    FOOD = frozenset(
        {
            "comida",
            "alimento",
            "carne",
            "peixe",
            "farinha",
            "mingau",
            "caissuma",
            "caiçuma",
            "bebida",
            "caldo",
            "sal",
            "pimenta",
            "mel",
            "banquete",
        }
    )

    def classify_entry(self, entry: dict[str, Any]) -> SemanticProfile:
        """Classify grammatical valence and semantic domain from entry glosses and pos."""
        glosses = entry.get("glosses_por", []) or entry.get("glosses", [])
        pos = (entry.get("pos") or "").lower()

        clean_words = []
        for g in glosses:
            tokens = re.findall(r"[\wáéíóúãõâêîôûç]+", g.lower())
            clean_words.extend(tokens)

        valence = GrammaticalValence.UNKNOWN
        inalienability = NounInalienability.NOT_APPLICABLE
        domain = SemanticDomain.GENERAL
        subdomains: list[str] = []
        rationale: list[str] = []

        is_verb = "verb" in pos or any(
            w in self.INTRANSITIVE_VERBS | self.TRANSITIVE_VERBS | self.DITRANSITIVE_VERBS
            for w in clean_words
        )
        is_noun = "noun" in pos or "subst" in pos

        # --- 1. Valence Classification ---
        if is_verb:
            # Check ditransitive first
            if any(w in self.DITRANSITIVE_VERBS for w in clean_words):
                valence = GrammaticalValence.DITRANSITIVE
                rationale.append("Verbo ditransitivo (dar/mostrar/ensinar)")
            # Check intransitive motion/posture/state
            elif any(w in self.INTRANSITIVE_VERBS for w in clean_words):
                valence = GrammaticalValence.INTRANSITIVE
                rationale.append("Verbo intransitivo de movimento/postura/estado")
            # Check transitive action
            elif any(w in self.TRANSITIVE_VERBS for w in clean_words):
                valence = GrammaticalValence.TRANSITIVE
                rationale.append("Verbo transitivo com objeto direto afirmativo")
            else:
                valence = GrammaticalValence.TRANSITIVE
                rationale.append("Verbo genérico com valência transitiva padrão")
        else:
            valence = GrammaticalValence.NON_VERBAL

        # --- 2. Inalienability Classification ---
        if is_noun:
            if any(w in self.BODY_PARTS for w in clean_words):
                inalienability = NounInalienability.INALIENABLE_BODY
                rationale.append("Substantivo inalienável (parte do corpo)")
            elif any(w in self.KINSHIP for w in clean_words):
                inalienability = NounInalienability.INALIENABLE_KIN
                rationale.append("Substantivo inalienável (termo de parentesco)")
            else:
                inalienability = NounInalienability.ALIENABLE

        # --- 3. Semantic Domain Classification ---
        # Evaluate word overlap against domain sets
        scores: dict[SemanticDomain, int] = {
            SemanticDomain.FAUNA: sum(1 for w in clean_words if w in self.FAUNA),
            SemanticDomain.FLORA: sum(1 for w in clean_words if w in self.FLORA),
            SemanticDomain.BODY_HEALTH: sum(1 for w in clean_words if w in self.BODY_PARTS),
            SemanticDomain.KINSHIP_SOCIAL: sum(1 for w in clean_words if w in self.KINSHIP),
            SemanticDomain.ARTIFACTS_TOOLS: sum(1 for w in clean_words if w in self.ARTIFACTS),
            SemanticDomain.UNIVERSE_NATURE: sum(1 for w in clean_words if w in self.NATURE),
            SemanticDomain.FOOD_SUSTENANCE: sum(1 for w in clean_words if w in self.FOOD),
            SemanticDomain.ACTIONS_MOTION: sum(
                1 for w in clean_words if w in self.INTRANSITIVE_VERBS
            ),
            SemanticDomain.PERCEPTION_MIND: sum(
                1
                for w in clean_words
                if w in {"ver", "ouvir", "pensar", "saber", "sonhar", "amar", "temer", "olhar"}
            ),
        }

        # Check for numerals and quantifiers
        if pos in ("num", "card", "ord") or any(
            w in {"um", "dois", "três", "quatro", "muitos", "poucos", "todos"} for w in clean_words
        ):
            domain = SemanticDomain.QUANTITY_STATE
            subdomains.append("numerais_quantificadores")
        else:
            best_domain, max_score = max(scores.items(), key=lambda x: x[1])
            if max_score > 0:
                domain = best_domain
                subdomains = [d.value for d, score in scores.items() if score > 0]
            else:
                domain = SemanticDomain.GENERAL

        return SemanticProfile(
            valence=valence,
            inalienability=inalienability,
            primary_domain=domain,
            subdomains=subdomains,
            confidence=1.0 if rationale else 0.8,
            rationale=rationale,
        )


def enrich_dictionary_with_semantics(dict_data: dict[str, Any]) -> dict[str, Any]:
    """Enrich all entries in dictionary with grammatical valence and semantic domains."""
    classifier = PivotSemanticsClassifier()
    enriched = dict(dict_data)
    entries = list(dict_data.get("lexicon", []))
    new_entries: list[dict[str, Any]] = []

    valence_counts: dict[str, int] = {}
    domain_counts: dict[str, int] = {}

    for e in entries:
        e_copy = dict(e)
        sem_profile = classifier.classify_entry(e_copy)
        e_copy["semantics"] = sem_profile.to_dict()

        # Update POS if POS was unknown or default
        if (not e_copy.get("pos") or e_copy.get("pos") == "noun") and sem_profile.valence in (
            GrammaticalValence.TRANSITIVE,
            GrammaticalValence.INTRANSITIVE,
            GrammaticalValence.DITRANSITIVE,
        ):
            e_copy["pos"] = f"verb_{sem_profile.valence.value}"

        v_val = sem_profile.valence.value
        d_val = sem_profile.primary_domain.value
        valence_counts[v_val] = valence_counts.get(v_val, 0) + 1
        domain_counts[d_val] = domain_counts.get(d_val, 0) + 1

        new_entries.append(e_copy)

    enriched["lexicon"] = new_entries
    enriched["semantics_stats"] = {
        "valence_distribution": valence_counts,
        "domain_distribution": domain_counts,
    }
    return enriched
