"""Marúbo (``mzr``) grammatical profile (ADR-0017, M2 WP 2.1).

Defines ergative-absolutive alignment markers, TAM suffixes, and clause structures
attested in Costa (1992, 2000), Soares (2006), and the parallel biblical corpus.
"""

from langpipe.languages.base import GrammarProfile

MZR_GRAMMAR_PROFILE = GrammarProfile(
    alignment_type="ergative_absolutive",
    default_word_order="SOV",
    ergative_suffixes=("-n", "-nin", "-yã"),
    absolutive_suffixes=("",),
    dative_suffixes=("-no", "-kiri", "-ya"),
    genitive_suffixes=("-n",),
    negation_suffixes=("-ma", "-yama"),
    interrogative_suffixes=("-vẽ", "-ka"),
    imperative_suffixes=("-we", "-tani"),
    transitive_tam_suffixes=("-ai", "-kanai", "-katsi", "-akĩ"),
    intransitive_tam_suffixes=("-ai", "-katsi", "-wa"),
)
