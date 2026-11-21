"""Unit tests for TargetHandler implementations (WP5.13, Gate 42)."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from langpipe.domain.enums import (
    EntityType,
    LifecycleStatus,
    ReviewDecisionKind,
    ReviewTaskType,
)
from langpipe.domain.errors import InvalidTransition, NotFound, SchemaViolation
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.lexical import Lexeme, Sense
from langpipe.domain.models.morphology import MorphAnalysis, Morpheme, MorphSegment
from langpipe.domain.models.observation import Segment, TokenOccurrence
from langpipe.review.targets import (
    ConceptTargetHandler,
    LexemeTargetHandler,
    MorphAnalysisTargetHandler,
    MorphemeTargetHandler,
    SenseTargetHandler,
    get_target_handler,
)
from langpipe.storage.repository import Repository

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_get_target_handler_lookup() -> None:
    assert isinstance(get_target_handler(EntityType.LEXEME), LexemeTargetHandler)
    assert isinstance(get_target_handler(EntityType.SENSE), SenseTargetHandler)
    assert isinstance(get_target_handler(EntityType.CONCEPT), ConceptTargetHandler)
    assert isinstance(get_target_handler(EntityType.MORPHEME), MorphemeTargetHandler)
    assert isinstance(get_target_handler(EntityType.MORPH_ANALYSIS), MorphAnalysisTargetHandler)

    with pytest.raises(NotFound, match="handler"):
        get_target_handler(EntityType.SOURCE)


def test_target_handler_allowed_task_types() -> None:
    assert ReviewTaskType.MORPHEME_FUNCTION in MorphemeTargetHandler.allowed_task_types
    assert ReviewTaskType.MORPHOLOGY_SEGMENTATION not in MorphemeTargetHandler.allowed_task_types
    assert ReviewTaskType.MORPHOLOGY_SEGMENTATION in MorphAnalysisTargetHandler.allowed_task_types
    assert ReviewTaskType.MORPHEME_FUNCTION not in MorphAnalysisTargetHandler.allowed_task_types


def test_concept_target_handler_rules() -> None:
    handler = ConceptTargetHandler()
    repo = MagicMock(spec=Repository)
    cid = new_id(IdPrefix.CONCEPT)
    assert handler.status_of(repo, cid) is None
    assert handler.language_of(repo, cid) == "und"
    assert handler.domain_of(repo, cid) is None
    assert handler.dependents(repo, cid) == ()

    # Queue-only decisions pass
    handler.check_decision_legal(repo, cid, ReviewDecisionKind.UNCERTAIN)
    handler.check_decision_legal(repo, cid, ReviewDecisionKind.DEFER)

    # Lifecycle writes raise SchemaViolation
    with pytest.raises(SchemaViolation):
        handler.check_decision_legal(repo, cid, ReviewDecisionKind.ACCEPT)
    with pytest.raises(SchemaViolation):
        handler.check_decision_legal(repo, cid, ReviewDecisionKind.REJECT)
    with pytest.raises(SchemaViolation):
        handler.check_decision_legal(repo, cid, ReviewDecisionKind.MODIFY)
    with pytest.raises(SchemaViolation):
        handler.set_status(repo, cid, LifecycleStatus.VALIDATED, "und")
    with pytest.raises(SchemaViolation):
        handler.check_successor(repo, cid, new_id(IdPrefix.CONCEPT))


def test_lexeme_target_handler_successor_rules() -> None:
    handler = LexemeTargetHandler()
    repo = MagicMock(spec=Repository)
    run_id = new_id(IdPrefix.RUN)
    target = Lexeme(
        id=new_id(IdPrefix.LEXEME),
        language="qaa",
        domain="botany",
        run_id=run_id,
        created_at=NOW,
    )
    succ_same_lang = Lexeme(
        id=new_id(IdPrefix.LEXEME),
        language="qaa",
        domain="botany",
        run_id=run_id,
        created_at=NOW,
    )
    succ_diff_lang = Lexeme(
        id=new_id(IdPrefix.LEXEME),
        language="por",
        domain="botany",
        run_id=run_id,
        created_at=NOW,
    )

    repo.entity_type_of.side_effect = lambda eid: (
        EntityType.LEXEME if str(eid).startswith("lex_") else None
    )
    repo.get_lexeme.side_effect = lambda eid: {
        target.id: target,
        succ_same_lang.id: succ_same_lang,
        succ_diff_lang.id: succ_diff_lang,
    }[eid]

    # Same language succeeds
    assert handler.check_successor(repo, target.id, succ_same_lang.id) == succ_same_lang

    # Self-supersession fails
    with pytest.raises(SchemaViolation):
        handler.check_successor(repo, target.id, target.id)

    # Different language fails
    with pytest.raises(SchemaViolation):
        handler.check_successor(repo, target.id, succ_diff_lang.id)


def test_sense_target_handler_successor_rules() -> None:
    handler = SenseTargetHandler()
    repo = MagicMock(spec=Repository)
    run_id = new_id(IdPrefix.RUN)
    lex_id = new_id(IdPrefix.LEXEME)
    target = Sense(id=new_id(IdPrefix.SENSE), lexeme_id=lex_id, run_id=run_id, created_at=NOW)
    succ_same_lex = Sense(
        id=new_id(IdPrefix.SENSE), lexeme_id=lex_id, run_id=run_id, created_at=NOW
    )
    succ_diff_lex = Sense(
        id=new_id(IdPrefix.SENSE),
        lexeme_id=new_id(IdPrefix.LEXEME),
        run_id=run_id,
        created_at=NOW,
    )

    repo.entity_type_of.side_effect = lambda eid: (
        EntityType.SENSE if str(eid).startswith("sense_") else None
    )
    repo.get_sense.side_effect = lambda eid: {
        target.id: target,
        succ_same_lex.id: succ_same_lex,
        succ_diff_lex.id: succ_diff_lex,
    }[eid]

    assert handler.check_successor(repo, target.id, succ_same_lex.id) == succ_same_lex
    with pytest.raises(SchemaViolation):
        handler.check_successor(repo, target.id, succ_diff_lex.id)


def test_morpheme_target_handler_rules() -> None:
    handler = MorphemeTargetHandler()
    repo = MagicMock(spec=Repository)
    run_id = new_id(IdPrefix.RUN)
    dummy_key = "a" * 64
    target = Morpheme(
        id=new_id(IdPrefix.MORPHEME),
        language="qaa",
        role="unknown_bound",
        canonical_form="ki",
        form_basis="surface",
        identity_key=dummy_key,
        run_id=run_id,
        created_at=NOW,
    )
    succ_diff_role = Morpheme(
        id=new_id(IdPrefix.MORPHEME),
        language="qaa",
        role="root",
        canonical_form="ki",
        form_basis="surface",
        identity_key=dummy_key,
        run_id=run_id,
        created_at=NOW,
    )
    succ_diff_lang = Morpheme(
        id=new_id(IdPrefix.MORPHEME),
        language="por",
        role="root",
        canonical_form="ki",
        form_basis="surface",
        identity_key=dummy_key,
        run_id=run_id,
        created_at=NOW,
    )

    repo.entity_type_of.side_effect = lambda eid: (
        EntityType.MORPHEME if str(eid).startswith("morph_") else None
    )
    repo.get_morpheme.side_effect = lambda eid: {
        target.id: target,
        succ_diff_role.id: succ_diff_role,
        succ_diff_lang.id: succ_diff_lang,
    }[eid]
    repo.get_morpheme_for_update.side_effect = lambda eid: repo.get_morpheme(eid)

    # Successor with different role but same language is allowed (how role is corrected)
    assert handler.check_successor(repo, target.id, succ_diff_role.id) == succ_diff_role

    # Different language raises SchemaViolation
    with pytest.raises(SchemaViolation):
        handler.check_successor(repo, target.id, succ_diff_lang.id)

    # Dependents returns analyses linking morpheme
    mock_analysis = MagicMock(id=new_id(IdPrefix.MORPH_ANALYSIS))
    repo.list_analyses_linking_morpheme.return_value = [mock_analysis]
    assert handler.dependents(repo, target.id) == [mock_analysis.id]


def test_morph_analysis_target_handler_rules() -> None:
    handler = MorphAnalysisTargetHandler()
    repo = MagicMock(spec=Repository)
    run_id = new_id(IdPrefix.RUN)
    seg_id = new_id(IdPrefix.SEGMENT)
    tok_id = new_id(IdPrefix.TOKEN)

    token = TokenOccurrence(
        id=tok_id,
        segment_id=seg_id,
        run_id=run_id,
        ordinal=0,
        raw_surface="mabi",
        normalized_surface="mabi",
        tokenizer="whitespace_punct@0.1.0",
        created_at=NOW,
    )
    segment = Segment(
        id=seg_id,
        source_id=new_id(IdPrefix.SOURCE),
        source_object_id=new_id(IdPrefix.SOURCE_OBJECT),
        run_id=run_id,
        ordinal=0,
        language="qaa",
        locator={},
        raw_text="mabi",
        normalized_text="mabi",
        normalization_profile="default@0.1.0",
        created_at=NOW,
    )
    sig_1 = "c" * 64
    sig_2 = "d" * 64
    target = MorphAnalysis(
        id=new_id(IdPrefix.MORPH_ANALYSIS),
        target_token_id=tok_id,
        analysis_kind="segmented",
        method="igt_assertion@0.1.0",
        span_representation="raw",
        surface="mabi",
        signature=sig_1,
        run_id=run_id,
        created_at=NOW,
    )
    succ_same_tok_diff_sig = MorphAnalysis(
        id=new_id(IdPrefix.MORPH_ANALYSIS),
        target_token_id=tok_id,
        analysis_kind="segmented",
        method="igt_assertion@0.1.0",
        span_representation="raw",
        surface="mabi",
        signature=sig_2,
        run_id=run_id,
        created_at=NOW,
    )
    succ_same_sig = MorphAnalysis(
        id=new_id(IdPrefix.MORPH_ANALYSIS),
        target_token_id=tok_id,
        analysis_kind="segmented",
        method="igt_assertion@0.1.0",
        span_representation="raw",
        surface="mabi",
        signature=sig_1,
        run_id=run_id,
        created_at=NOW,
    )
    succ_diff_tok = MorphAnalysis(
        id=new_id(IdPrefix.MORPH_ANALYSIS),
        target_token_id=new_id(IdPrefix.TOKEN),
        analysis_kind="segmented",
        method="igt_assertion@0.1.0",
        span_representation="raw",
        surface="mabi",
        signature=sig_2,
        run_id=run_id,
        created_at=NOW,
    )

    repo.get_token.return_value = token
    repo.get_segment.return_value = segment
    repo.list_morph_segments.return_value = []
    repo.entity_type_of.side_effect = lambda eid: (
        EntityType.MORPH_ANALYSIS if str(eid).startswith("ma_") else None
    )
    repo.get_morph_analysis.side_effect = lambda eid: {
        target.id: target,
        succ_same_tok_diff_sig.id: succ_same_tok_diff_sig,
        succ_same_sig.id: succ_same_sig,
        succ_diff_tok.id: succ_diff_tok,
    }[eid]
    repo.get_morph_analysis_for_update.side_effect = lambda eid: repo.get_morph_analysis(eid)
    repo.get_morpheme_for_update.side_effect = lambda eid: repo.get_morpheme(eid)

    assert handler.language_of(repo, target.id) == "qaa"
    assert handler.domain_of(repo, target.id) is None
    assert handler.dependents(repo, target.id) == ()

    # Successor must target same token and differ in signature
    assert (
        handler.check_successor(repo, target.id, succ_same_tok_diff_sig.id)
        == succ_same_tok_diff_sig
    )
    with pytest.raises(SchemaViolation):
        handler.check_successor(repo, target.id, succ_same_sig.id)  # same signature
    with pytest.raises(SchemaViolation):
        handler.check_successor(repo, target.id, succ_diff_tok.id)  # different token


def test_morph_analysis_accept_refuses_rejected_morpheme() -> None:
    handler = MorphAnalysisTargetHandler()
    repo = MagicMock(spec=Repository)
    run_id = new_id(IdPrefix.RUN)
    ana_id = new_id(IdPrefix.MORPH_ANALYSIS)
    dummy_key = "b" * 64

    mph_ok_id = new_id(IdPrefix.MORPHEME)
    mph_bad_id = new_id(IdPrefix.MORPHEME)

    seg_ok = MorphSegment(
        id=new_id(IdPrefix.MORPH_SEGMENT),
        analysis_id=ana_id,
        ordinal=0,
        surface="mabi",
        start=0,
        end=4,
        morpheme_id=mph_ok_id,
        created_at=NOW,
    )
    seg_bad = MorphSegment(
        id=new_id(IdPrefix.MORPH_SEGMENT),
        analysis_id=ana_id,
        ordinal=1,
        surface="ki",
        start=4,
        end=6,
        morpheme_id=mph_bad_id,
        created_at=NOW,
    )

    m_ok = Morpheme(
        id=mph_ok_id,
        language="qaa",
        role="root",
        canonical_form="mabi",
        form_basis="surface",
        identity_key=dummy_key,
        status=LifecycleStatus.CANDIDATE,
        run_id=run_id,
        created_at=NOW,
    )
    m_rej = Morpheme(
        id=mph_bad_id,
        language="qaa",
        role="unknown_bound",
        canonical_form="ki",
        form_basis="surface",
        identity_key=dummy_key,
        status=LifecycleStatus.REJECTED,
        run_id=run_id,
        created_at=NOW,
    )
    m_dep = m_rej.model_copy(update={"status": LifecycleStatus.DEPRECATED})

    repo.get_morpheme.side_effect = lambda eid: {
        mph_ok_id: m_ok,
        mph_bad_id: m_rej,
    }[eid]
    repo.get_morpheme_for_update.side_effect = lambda eid: repo.get_morpheme(eid)

    # Analysis with rejected morpheme raises InvalidTransition on accept
    repo.list_morph_segments.return_value = [seg_ok, seg_bad]
    with pytest.raises(InvalidTransition):
        handler.check_decision_legal(repo, ana_id, ReviewDecisionKind.ACCEPT)

    # Deprecated also raises
    repo.get_morpheme.side_effect = lambda eid: {
        mph_ok_id: m_ok,
        mph_bad_id: m_dep,
    }[eid]
    with pytest.raises(InvalidTransition):
        handler.check_decision_legal(repo, ana_id, ReviewDecisionKind.ACCEPT)

    # Reject or uncertain passes even with rejected morpheme
    handler.check_decision_legal(repo, ana_id, ReviewDecisionKind.REJECT)
    handler.check_decision_legal(repo, ana_id, ReviewDecisionKind.UNCERTAIN)

    # Validated / candidate morphemes pass on accept
    m_val = m_ok.model_copy(update={"status": LifecycleStatus.VALIDATED})
    repo.get_morpheme.side_effect = lambda eid: {
        mph_ok_id: m_ok,
        mph_bad_id: m_val,
    }[eid]
    handler.check_decision_legal(repo, ana_id, ReviewDecisionKind.ACCEPT)
