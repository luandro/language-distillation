"""Stage 7b IGT assertion morphology inducer `igt_assertion@0.1.0` (M5-PLAN §7.7, Gate 38).

Per mapped (IGT word, token) pair with `parse_status ok`:
1. Locates morphs left-to-right in token surface (normalized); separators must be boundary marks.
   If impossible -> unmapped underlying, morphemes recorded with form_basis=underlying, no analysis.
2. Role: lexical gloss present -> root; else '=' boundary -> clitic; else '-' -> unknown_bound;
   UNKNOWN gloss -> unknown.
3. Morpheme by identity key; allomorphs; local features local:<lang>:<LABEL>.
4. One segmented MorphAnalysis per word token with one segment per morph, segment-feature rows.
5. Evidence igt_assertion/supports targeting analysis and morphemes; lineage edges.
6. Scores morphemes, allomorphs and analyses using morph-v1 policy.
"""

import unicodedata
from collections import defaultdict
from datetime import UTC, datetime
from typing import ClassVar

from langpipe.domain.enums import (
    AllomorphConditioning,
    AnalysisKind,
    EvidenceKind,
    EvidencePolarity,
    FeatureAssignmentBasis,
    FormBasis,
    LifecycleStatus,
    LineageKind,
    MorphRole,
    SpanRepresentation,
)
from langpipe.domain.ids import IdFactory, IdPrefix, new_id
from langpipe.domain.models.evidence import EvidenceItem, LineageEdge
from langpipe.domain.models.morphology import (
    Allomorph,
    Feature,
    MorphAnalysis,
    Morpheme,
    MorphSegment,
    MorphSegmentFeature,
)
from langpipe.domain.models.observation import TokenOccurrence
from langpipe.igt.gloss import split_gloss
from langpipe.languages.base import MorphologyProfile
from langpipe.morphology.base import (
    MorphAnalysisCandidate,
    MorphologyInducer,
    MorphologyInductionInput,
    MorphologyInductionOutput,
)
from langpipe.morphology.identity import morpheme_identity_key
from langpipe.morphology.scoring import score_analysis, score_morpheme
from langpipe.morphology.spans import check_analysis, segmentation_signature
from langpipe.morphology.word_mapping import map_words


def _default_id(prefix: IdPrefix) -> str:
    return new_id(prefix)


class IgtAssertionInducer(MorphologyInducer):
    """The Stage 7b IGT assertion inducer `igt_assertion@0.1.0`."""

    name: ClassVar[str] = "igt_assertion"
    version: ClassVar[str] = "0.1.0"

    def __init__(self, new_id_factory: IdFactory | None = None) -> None:
        self._new_id: IdFactory = new_id_factory if new_id_factory is not None else _default_id

    @property
    def method_id(self) -> str:
        return f"{self.name}@{self.version}"

    def induce(self, input: MorphologyInductionInput) -> MorphologyInductionOutput:
        now = datetime.now(UTC)
        profile: MorphologyProfile = (
            input.profile
            if input.profile is not None and isinstance(input.profile, MorphologyProfile)
            else MorphologyProfile()
        )
        boundary_marks = tuple(profile.boundary_marks)
        normalizer = getattr(profile, "normalizer", None)

        # 1. Group tokens by segment_id (or ancestor raw segment_id for IGT observations)
        ancestors = input.segment_ancestors or {}
        tokens_by_segment: dict[str, list[TokenOccurrence]] = defaultdict(list)
        for tok in input.tokens:
            seg_id = ancestors.get(tok.segment_id, tok.segment_id)
            tokens_by_segment[seg_id].append(tok)
        for tok_list in tokens_by_segment.values():
            tok_list.sort(key=lambda t: t.ordinal)

        words_mapped = 0
        words_unmapped = {
            "count_mismatch": 0,
            "surface_mismatch": 0,
            "words_unmapped_underlying": 0,
        }

        run_morphemes: dict[str, Morpheme] = {}
        run_allomorphs: dict[tuple[str, str], Allomorph] = {}
        run_features: dict[tuple[str, str], Feature] = {}

        analyses: list[MorphAnalysisCandidate] = []
        evidence_items: list[EvidenceItem] = []
        lineage_edges: list[LineageEdge] = []
        seen_edges: set[tuple[str, str, str]] = set()

        morpheme_evidence: dict[str, list[EvidenceItem]] = defaultdict(list)
        analysis_evidence: dict[str, list[EvidenceItem]] = defaultdict(list)

        def add_edge(
            from_id: str, to_id: str, kind: LineageKind = LineageKind.DERIVED_FROM
        ) -> None:
            key = (from_id, to_id, kind.value)
            if key not in seen_edges:
                seen_edges.add(key)
                lineage_edges.append(
                    LineageEdge(
                        id=self._new_id(IdPrefix.LINEAGE),
                        from_id=from_id,
                        to_id=to_id,
                        kind=kind,
                        run_id=input.run_id,
                        created_at=now,
                    )
                )

        # 2. Iterate through observations
        for obs in input.observations:
            if obs.segment_id is None:
                words_unmapped["count_mismatch"] += len(obs.words)
                continue

            obs_tokens = tokens_by_segment.get(obs.segment_id, [])
            mapping_res = map_words(obs.words, obs_tokens, normalizer=normalizer)
            words_unmapped["count_mismatch"] += mapping_res.unmapped_counts.get("count_mismatch", 0)
            words_unmapped["surface_mismatch"] += mapping_res.unmapped_counts.get(
                "surface_mismatch", 0
            )

            contact_lang = input.contact_language or (
                list(obs.translations.keys())[0] if obs.translations else "por"
            )

            for igt_word, token in mapping_res.mapped:
                tok_surface = (
                    token.normalized_surface
                    if token.normalized_surface is not None
                    else token.raw_surface
                )
                span_rep = (
                    SpanRepresentation.NORMALIZED
                    if token.normalized_surface is not None
                    else SpanRepresentation.RAW
                )

                # Step 1: Locate morphs left-to-right in tok_surface
                curr = 0
                spans: list[tuple[int, int, str]] = []
                loc_ok = True
                for m_idx, morph in enumerate(igt_word.morphs):
                    if (
                        m_idx > 0
                        and curr < len(tok_surface)
                        and tok_surface[curr] in boundary_marks
                    ):
                        curr += 1
                    m_len = len(morph.text)
                    if (
                        curr + m_len <= len(tok_surface)
                        and tok_surface[curr : curr + m_len] == morph.text
                    ):
                        spans.append((curr, curr + m_len, morph.text))
                        curr += m_len
                    else:
                        loc_ok = False
                        break

                if loc_ok and curr == len(tok_surface):
                    is_underlying = False
                    form_basis = FormBasis.SURFACE
                    words_mapped += 1
                else:
                    is_underlying = True
                    form_basis = FormBasis.UNDERLYING
                    words_unmapped["words_unmapped_underlying"] += 1

                # Step 2 & 3: Process each morph
                word_morphemes: list[Morpheme] = []
                word_allomorphs: list[Allomorph] = []
                word_features_per_morph: list[list[Feature]] = []

                for morph in igt_word.morphs:
                    # Role determination
                    lexical_glosses: tuple[str, ...]
                    grammatical_labels: tuple[str, ...]
                    if morph.gloss is None:
                        role = MorphRole.UNKNOWN
                        lexical_glosses = ()
                        grammatical_labels = ()
                    else:
                        sg = split_gloss(morph.gloss, profile)
                        if sg.is_unknown:
                            role = MorphRole.UNKNOWN
                            lexical_glosses = ()
                            grammatical_labels = ()
                        elif sg.lexical_glosses:
                            role = MorphRole.ROOT
                            lexical_glosses = sg.lexical_glosses
                            grammatical_labels = sg.grammatical_labels
                        elif morph.boundary_before == "=":
                            role = MorphRole.CLITIC
                            lexical_glosses = ()
                            grammatical_labels = sg.grammatical_labels
                        elif morph.boundary_before == "-":
                            role = MorphRole.UNKNOWN_BOUND
                            lexical_glosses = ()
                            grammatical_labels = sg.grammatical_labels
                        else:
                            role = MorphRole.UNKNOWN_BOUND
                            lexical_glosses = ()
                            grammatical_labels = sg.grammatical_labels

                    glosses_dict: dict[str, list[str]] = (
                        {contact_lang: list(lexical_glosses)} if lexical_glosses else {}
                    )
                    nfc_form = unicodedata.normalize("NFC", morph.text)
                    id_key = morpheme_identity_key(
                        input.language,
                        role,
                        nfc_form,
                        glosses=glosses_dict,
                        gloss_labels=grammatical_labels,
                    )

                    if id_key not in run_morphemes:
                        morpheme = Morpheme(
                            id=self._new_id(IdPrefix.MORPHEME),
                            language=input.language,
                            role=role,
                            canonical_form=nfc_form,
                            form_basis=form_basis,
                            glosses=glosses_dict,
                            gloss_labels=list(grammatical_labels),
                            identity_key=id_key,
                            status=LifecycleStatus.CANDIDATE,
                            run_id=input.run_id,
                            created_at=now,
                        )
                        run_morphemes[id_key] = morpheme
                    else:
                        morpheme = run_morphemes[id_key]
                    word_morphemes.append(morpheme)

                    a_key = (morpheme.id, nfc_form)
                    if a_key not in run_allomorphs:
                        allomorph = Allomorph(
                            id=self._new_id(IdPrefix.ALLOMORPH),
                            morpheme_id=morpheme.id,
                            form=nfc_form,
                            is_zero=False,
                            form_basis=form_basis,
                            conditioning=AllomorphConditioning.UNKNOWN,
                            status=LifecycleStatus.CANDIDATE,
                            run_id=input.run_id,
                            created_at=now,
                        )
                        run_allomorphs[a_key] = allomorph
                    else:
                        allomorph = run_allomorphs[a_key]
                    word_allomorphs.append(allomorph)

                    # Features
                    morph_feats: list[Feature] = []
                    for label in grammatical_labels:
                        ns = f"local:{input.language}"
                        feat_key = (ns, label)
                        if feat_key not in run_features:
                            feat = Feature(
                                id=self._new_id(IdPrefix.FEATURE),
                                namespace=ns,
                                label=label,
                                definition=f"source gloss label {label}",
                                defined_by="source_gloss_label",
                                run_id=input.run_id,
                                created_at=now,
                            )
                            run_features[feat_key] = feat
                        else:
                            feat = run_features[feat_key]
                        morph_feats.append(feat)
                    word_features_per_morph.append(morph_feats)

                    # Step 5: Evidence for morpheme
                    m_evi = EvidenceItem(
                        id=self._new_id(IdPrefix.EVIDENCE),
                        kind=EvidenceKind.IGT_ASSERTION,
                        polarity=EvidencePolarity.SUPPORTS,
                        target_id=morpheme.id,
                        source_id=obs.source_id,
                        independence_group=obs.source_id,
                        claim={
                            "igt_observation_id": obs.id,
                            "word_ordinal": igt_word.ordinal,
                            "morph_ordinal": morph.ordinal,
                            "role_basis": str(role.value),
                        },
                        run_id=input.run_id,
                        created_at=now,
                    )
                    evidence_items.append(m_evi)
                    morpheme_evidence[morpheme.id].append(m_evi)

                    # Lineage for morpheme and allomorph
                    add_edge(morpheme.id, obs.id)
                    add_edge(morpheme.id, token.id)
                    add_edge(allomorph.id, morpheme.id)
                    add_edge(allomorph.id, token.id)

                # If underlying, no analysis is produced
                if is_underlying:
                    continue

                # Step 4: One segmented MorphAnalysis
                analysis_id = self._new_id(IdPrefix.MORPH_ANALYSIS)
                segments: list[MorphSegment] = []
                seg_features: list[MorphSegmentFeature] = []

                for m_idx, (start, end, morph_text) in enumerate(spans):
                    morph_obj = igt_word.morphs[m_idx]
                    morph_morpheme = word_morphemes[m_idx]
                    morph_allomorph = word_allomorphs[m_idx]
                    seg_id = self._new_id(IdPrefix.MORPH_SEGMENT)

                    segment = MorphSegment(
                        id=seg_id,
                        analysis_id=analysis_id,
                        ordinal=m_idx,
                        start=start,
                        end=end,
                        is_zero=False,
                        surface=morph_text,
                        morpheme_id=morph_morpheme.id,
                        allomorph_id=morph_allomorph.id,
                        role=morph_morpheme.role,
                        source_gloss=morph_obj.gloss,
                        created_at=now,
                    )
                    segments.append(segment)

                    for feat in word_features_per_morph[m_idx]:
                        seg_feat = MorphSegmentFeature(
                            segment_id=segment.id,
                            feature_id=feat.id,
                            basis=FeatureAssignmentBasis.IGT_GLOSS,
                            created_at=now,
                        )
                        seg_features.append(seg_feat)

                sig = segmentation_signature(AnalysisKind.SEGMENTED, segments)

                analysis = MorphAnalysis(
                    id=analysis_id,
                    target_token_id=token.id,
                    analysis_kind=AnalysisKind.SEGMENTED,
                    method=self.method_id,
                    span_representation=span_rep,
                    surface=tok_surface,
                    signature=sig,
                    abstention=None,
                    status=LifecycleStatus.CANDIDATE,
                    score_breakdown=None,
                    run_id=input.run_id,
                    created_at=now,
                )

                check_analysis(analysis, segments, boundary_marks)

                ana_evi = EvidenceItem(
                    id=self._new_id(IdPrefix.EVIDENCE),
                    kind=EvidenceKind.IGT_ASSERTION,
                    polarity=EvidencePolarity.SUPPORTS,
                    target_id=analysis.id,
                    source_id=obs.source_id,
                    independence_group=obs.source_id,
                    claim={
                        "igt_observation_id": obs.id,
                        "word_ordinal": igt_word.ordinal,
                    },
                    run_id=input.run_id,
                    created_at=now,
                )
                evidence_items.append(ana_evi)
                analysis_evidence[analysis.id].append(ana_evi)

                add_edge(analysis.id, obs.id)
                add_edge(analysis.id, token.id)

                analyses.append(
                    MorphAnalysisCandidate(
                        analysis=analysis,
                        segments=segments,
                        features=seg_features,
                    )
                )

        # 3. Score all Morphemes and Allomorphs using morph-v1
        scored_morphemes: dict[str, Morpheme] = {}
        for m_id, morpheme in list(run_morphemes.items()):
            evi_list = morpheme_evidence.get(morpheme.id, [])
            m_status, m_breakdown = score_morpheme(evidence_items=evi_list)
            updated_m = morpheme.model_copy(
                update={"status": m_status, "score_breakdown": m_breakdown}
            )
            scored_morphemes[morpheme.id] = updated_m
            run_morphemes[m_id] = updated_m

        scored_allomorphs: list[Allomorph] = []
        for allomorph in run_allomorphs.values():
            parent_m = scored_morphemes[allomorph.morpheme_id]
            updated_a = allomorph.model_copy(update={"status": parent_m.status})
            scored_allomorphs.append(updated_a)

        # 4. Score all MorphAnalyses using morph-v1
        scored_analyses: list[MorphAnalysisCandidate] = []
        for cand in analyses:
            linked_m = [scored_morphemes[s.morpheme_id] for s in cand.segments if s.morpheme_id]
            cand_evi = analysis_evidence.get(cand.analysis.id, [])
            a_status, a_breakdown = score_analysis(
                method=self.method_id,
                linked_morphemes=linked_m,
                segments=cand.segments,
                evidence_items=cand_evi,
            )
            updated_ana = cand.analysis.model_copy(
                update={"status": a_status, "score_breakdown": a_breakdown}
            )
            scored_analyses.append(
                MorphAnalysisCandidate(
                    analysis=updated_ana,
                    segments=cand.segments,
                    features=cand.features,
                )
            )

        return MorphologyInductionOutput(
            analyses=scored_analyses,
            morphemes=list(run_morphemes.values()),
            allomorphs=scored_allomorphs,
            features=list(run_features.values()),
            evidence_items=evidence_items,
            lineage_edges=lineage_edges,
            abstentions={},
            words_mapped=words_mapped,
            words_unmapped=words_unmapped,
        )


__all__ = ["IgtAssertionInducer"]
