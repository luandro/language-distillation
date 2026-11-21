"""Generic tokenizers. Language packages add theirs in ``languages/base.py`` (M2 WP2.6).

This module must not import ``languages``; it only lists generic components.
"""

from langpipe.tokenization.base import Tokenizer
from langpipe.tokenization.whitespace_punct import WhitespacePunctTokenizer

GENERIC_TOKENIZERS: tuple[Tokenizer, ...] = (WhitespacePunctTokenizer(),)
