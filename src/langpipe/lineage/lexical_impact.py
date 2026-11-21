"""Backward compatibility re-exports for lexical revocation impact (WP4.9, WP5.15)."""

from langpipe.lineage.knowledge_impact import RevocationImpact, revocation_impact

__all__ = ["RevocationImpact", "revocation_impact"]
