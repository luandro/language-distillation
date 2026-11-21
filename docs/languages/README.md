# Language Profile Contract

Language-specific behavior belongs here rather than generic pipeline code.

## Required sections

A language profile SHOULD define identifiers, names, orthographies, normalization rules, tokenization assumptions, character inventory where useful, registers/domains, typological working information, local features, related-language policy, G2P if used, challenge-set priorities and governance references.

## Evidence status

Facts must be labeled:

```text
documented
community_validated
working_assumption
open
```

A working assumption may configure an experiment but does not become validated knowledge automatically.

## Adapter interface

Generic stages may ask the profile for deterministic transformations/metadata such as:

```text
normalize(text, orthography_profile)
tokenize(text)
allowed_characters()
domain_taxonomy()
register_taxonomy()
feature_namespace()
g2p(form)   # optional
```

Adapters MUST NOT perform hidden persistence.

## Related languages

Each relation defines allowed/denied uses. Related-language information may generate hypotheses, not automatic lexical/morphological truth.

## Adding a language

1. create `docs/languages/<iso>.md`;
2. create runtime profile config;
3. add normalization/tokenization tests;
4. create language-specific evaluation fixtures;
5. modify generic semantics only if truly cross-language.
