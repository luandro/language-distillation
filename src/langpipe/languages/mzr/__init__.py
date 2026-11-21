"""Marúbo (``mzr``) language profile stub (M2 WP2.7).

All Marúbo-specific behavior lives in this package. The inventory ships empty and unverified; no
morphology, clitic list or stem inventory is encoded here (AGENTS invariant 9).

The two imports below load the generic registry in ``languages/base.py`` before this package's
profile module, so the ``base``/``profile`` mutual import resolves in either import order.
"""

from langpipe.languages import base as _base  # noqa: F401
from langpipe.languages.mzr import profile as _profile  # noqa: F401
