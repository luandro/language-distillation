"""Leipzig interlinear glossed text (IGT) parser for academic and indigenous papers."""

import re
from datetime import UTC, datetime

from langpipe.domain.enums import IgtFormat, IgtParseStatus
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.igt import IgtMorph, IGTObservation, IgtTierLine, IgtWord


class IgtObservationParser:
    """Parses interlinear glossed text into canonical IGTObservation domain entities."""

    def __init__(self, source_id: str, run_id: str, source_object_id: str):
        self.source_id = source_id
        self.run_id = run_id
        self.source_object_id = source_object_id

    def parse_blocks(self, text: str) -> tuple[list[IGTObservation], list[dict[str, str]]]:
        """Parse text containing (N) formatted IGT blocks into observations and parallel pairs."""
        blocks = re.split(r"\n(?=\([0-9]+\))", text)
        observations: list[IGTObservation] = []
        parallel_pairs: list[dict[str, str]] = []

        now = datetime.now(UTC)
        record_idx = 0

        for b in blocks:
            b_clean = b.strip()
            if not b_clean or not re.match(r"^\([0-9]+\)", b_clean):
                continue

            lines = [
                line.strip()
                for line in b_clean.split("\n")
                if line.strip() and not line.strip().startswith("\x0c")
            ]
            if len(lines) < 3:
                continue

            # Header match
            m = re.match(r"^\(([0-9]+)\)\s*(.*)", lines[0])
            if not m:
                continue

            num_str = m.group(1)
            first_rest = m.group(2).strip()

            # Separate translations (quoted lines) from tier lines
            quote_lines = []
            non_quote_lines = []
            if first_rest:
                non_quote_lines.append(first_rest)

            for line in lines[1:]:
                # Check if it is a footnote number alone
                if re.match(r"^[0-9]+$", line):
                    continue
                # Check for translation quote
                if (line.startswith("‘") or line.startswith("'") or line.startswith('"')) and not (
                    line.endswith("-") or line.endswith("=")
                ):
                    quote_lines.append(line)
                else:
                    # Ignore trailing footnotes
                    if len(quote_lines) >= 2:
                        continue
                    non_quote_lines.append(line)

            if len(quote_lines) < 1 or len(non_quote_lines) < 2:
                continue

            # In typical 4-tier format:
            # non_quote_lines: [vernacular, morphemes, glosses] or [vernacular + morphemes, glosses]
            if len(non_quote_lines) >= 3:
                vernacular_str = non_quote_lines[0]
                morph_str = non_quote_lines[1]
                gloss_str = non_quote_lines[2]
            elif len(non_quote_lines) == 2:
                vernacular_str = non_quote_lines[0]
                morph_str = non_quote_lines[0]
                gloss_str = non_quote_lines[1]
            else:
                continue

            # Clean translations
            en_trans = ""
            pt_trans = ""
            cleaned_quotes = []
            for q in quote_lines:
                # A footnote digit glued after the closing quote (``morrido,’5``) is print
                # apparatus.
                q = re.sub(r"(?<=[’'\"”])[0-9]+$", "", q.strip())
                cq = re.sub(r"^[‘'\"\s]+|[’'\"\s]+$", "", q).strip()
                # Remove trailing footnote digits
                cq = re.sub(r"\s+[0-9]+$", "", cq).strip()
                if cq:
                    cleaned_quotes.append(cq)

            if len(cleaned_quotes) >= 2:
                en_trans = cleaned_quotes[0]
                pt_trans = cleaned_quotes[1]
            elif len(cleaned_quotes) == 1:
                en_trans = cleaned_quotes[0]
                pt_trans = cleaned_quotes[0]

            # Construct tiers
            tiers = [
                IgtTierLine(marker="\\tx", line_number=1, raw=vernacular_str),
                IgtTierLine(marker="\\mb", line_number=2, raw=morph_str),
                IgtTierLine(marker="\\ge", line_number=3, raw=gloss_str),
            ]
            if en_trans:
                tiers.append(IgtTierLine(marker="\\fte", line_number=4, raw=en_trans))
            if pt_trans:
                tiers.append(IgtTierLine(marker="\\ftp", line_number=5, raw=pt_trans))

            # Segment words and morphs
            words: list[IgtWord] = []
            morph_tokens = morph_str.split()
            gloss_tokens = gloss_str.split()

            for w_idx, w_text in enumerate(vernacular_str.split()):
                m_list: list[IgtMorph] = []
                # Attempt to align morphs
                if w_idx < len(morph_tokens):
                    raw_m = morph_tokens[w_idx]
                    raw_g = gloss_tokens[w_idx] if w_idx < len(gloss_tokens) else None
                    sub_morphs = re.split(r"([-=])", raw_m)
                    sub_glosses = re.split(r"([-=])", raw_g) if raw_g else []

                    # Parse sub morphs
                    curr_boundary = None
                    m_ord = 0
                    for token in sub_morphs:
                        if token in ("-", "="):
                            curr_boundary = token
                        elif token:
                            # Match gloss if possible
                            g_text = (
                                sub_glosses[m_ord * 2] if m_ord * 2 < len(sub_glosses) else raw_g
                            )
                            m_list.append(
                                IgtMorph(
                                    ordinal=m_ord,
                                    text=token,
                                    boundary_before=curr_boundary,
                                    gloss=g_text,
                                )
                            )
                            curr_boundary = None
                            m_ord += 1
                else:
                    m_list.append(IgtMorph(ordinal=0, text=w_text, gloss=None))

                words.append(IgtWord(ordinal=w_idx, text=w_text, morphs=m_list))

            translations = {}
            if en_trans:
                translations["eng"] = [en_trans]
            if pt_trans:
                translations["por"] = [pt_trans]

            obs = IGTObservation(
                id=new_id(IdPrefix.IGT_OBSERVATION),
                source_id=self.source_id,
                source_object_id=self.source_object_id,
                run_id=self.run_id,
                record_ordinal=record_idx,
                record_ref=f"({num_str})",
                format=IgtFormat.TOOLBOX,
                locator={"block_num": int(num_str)},
                tiers=tiers,
                words=words,
                translations=translations,
                parse_status=IgtParseStatus.OK,
                created_at=now,
            )
            observations.append(obs)

            if pt_trans and vernacular_str:
                parallel_pairs.append(
                    {
                        "ref": f"Cesarino-2017:({num_str})",
                        "src": vernacular_str,
                        "tgt": pt_trans,
                        "eng": en_trans,
                    }
                )

            record_idx += 1

        return observations, parallel_pairs
