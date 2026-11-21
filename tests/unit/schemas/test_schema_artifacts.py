import json
from datetime import UTC, datetime
from pathlib import Path

from langpipe.domain.enums import (
    AccessClass,
    AlignmentDirection,
    AlignmentMode,
    AlignmentStatus,
    AllomorphConditioning,
    AnalysisKind,
    ApprovalAction,
    ArtifactKind,
    EvidenceKind,
    EvidencePolarity,
    FeatureAssignmentBasis,
    FormBasis,
    IgtFormat,
    IgtParseStatus,
    LineageKind,
    MorphRole,
    Operation,
    PolicyMode,
    ReviewDecisionKind,
    ReviewTaskType,
    RunStage,
    RunStatus,
    SourceType,
    SpanRepresentation,
    Symmetrization,
)
from langpipe.domain.hashing import config_hash
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.alignment import SegmentAlignment, TokenAlignmentEdge
from langpipe.domain.models.approval import SourceUseApproval
from langpipe.domain.models.base import DomainModel
from langpipe.domain.models.evidence import EvidenceItem, LineageEdge
from langpipe.domain.models.igt import IgtMorph, IGTObservation, IgtTierLine, IgtWord
from langpipe.domain.models.lexical import Concept, FormLexemeLink, Lexeme, Sense
from langpipe.domain.models.morphology import (
    Allomorph,
    Feature,
    MorphAnalysis,
    Morpheme,
    MorphGold,
    MorphSegment,
    MorphSegmentFeature,
)
from langpipe.domain.models.observation import Form, Segment, Span, TokenOccurrence
from langpipe.domain.models.review import ReviewDecision, ReviewTask
from langpipe.domain.models.run import Artifact, ProcessingRun
from langpipe.domain.models.source import (
    PolicySpec,
    Provenance,
    Source,
    SourceManifest,
    SourceObject,
    SourcePolicy,
)
from langpipe.evaluation.alignment import (
    GoldAlignment,
    GoldGroup,
    GoldGroupLocatorSelector,
    GoldTokenSelector,
)
from langpipe.schemas.generate import check, generate, render_schema, schema_filename
from langpipe.schemas.registry import SCHEMA_MODELS

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_DIR = REPO_ROOT / "schemas"
NOW = datetime(2026, 1, 1, tzinfo=UTC)
SHA = "a" * 64


def _samples() -> dict[type[DomainModel], DomainModel]:
    run_id = new_id(IdPrefix.RUN)
    source_id = new_id(IdPrefix.SOURCE)
    source_object_id = new_id(IdPrefix.SOURCE_OBJECT)
    form_id = new_id(IdPrefix.FORM)
    lexeme_id = new_id(IdPrefix.LEXEME)
    sense_id = new_id(IdPrefix.SENSE)
    task_id = new_id(IdPrefix.REVIEW_TASK)
    segment = Segment(
        id=new_id(IdPrefix.SEGMENT),
        source_id=source_id,
        source_object_id=source_object_id,
        run_id=run_id,
        ordinal=0,
        language="mzr",
        raw_text="abc",
        created_at=NOW,
    )
    config: dict[str, str] = {"profile": "sample"}
    return {
        SourceManifest: SourceManifest(
            manifest_version=1,
            key="sample-source",
            title="Sample source",
            source_type=SourceType.PARALLEL_TEXT,
            languages=["mzr", "por"],
            provenance=Provenance(acquired_from="field notebook"),
            acquired_at=NOW,
            policy=PolicySpec(
                mode=PolicyMode.DISTILL_ONLY,
                access_class=AccessClass.RESTRICTED,
                authority="community council",
            ),
            objects=[{"path": "texts/a.txt", "media_type": "text/plain"}],
        ),
        SourcePolicy: SourcePolicy(
            id=new_id(IdPrefix.POLICY),
            mode=PolicyMode.DISTILL_ONLY,
            access_class=AccessClass.RESTRICTED,
            authority="community council",
            allow=(),
            deny=(),
            created_at=NOW,
        ),
        Source: Source(
            id=source_id,
            key="sample-source",
            title="Sample source",
            source_type=SourceType.PARALLEL_TEXT,
            languages=("mzr", "por"),
            provenance=Provenance(acquired_from="field notebook"),
            policy_id=new_id(IdPrefix.POLICY),
            acquired_at=NOW,
            domains=(),
            registers=(),
            manifest_sha256=SHA,
            registration_run_id=run_id,
            created_at=NOW,
            updated_at=NOW,
        ),
        SourceObject: SourceObject(
            id=source_object_id,
            source_id=source_id,
            original_path="texts/a.txt",
            origin_uri="file:///data/texts/a.txt",
            sha256=SHA,
            size_bytes=12,
            media_type="text/plain",
            access_class=AccessClass.RESTRICTED,
            registration_run_id=run_id,
            created_at=NOW,
        ),
        ProcessingRun: ProcessingRun(
            id=run_id,
            stage=RunStage.RAW_INGESTION,
            tool_name="langpipe",
            tool_version="0.1.0",
            config=config,
            config_hash=config_hash(config),
            code_revision="dev",
            run_key=SHA,
            status=RunStatus.SUCCEEDED,
            started_at=NOW,
            finished_at=NOW,
        ),
        Artifact: Artifact(
            id=new_id(IdPrefix.ARTIFACT),
            run_id=run_id,
            kind=ArtifactKind.OTHER,
            media_type="application/json",
            sha256=SHA,
            size_bytes=0,
            access_class=AccessClass.RESTRICTED,
            created_at=NOW,
        ),
        Segment: segment,
        TokenOccurrence: TokenOccurrence(
            id=new_id(IdPrefix.TOKEN),
            segment_id=segment.id,
            run_id=run_id,
            ordinal=0,
            raw_surface="ab",
            raw_span=Span(representation=SpanRepresentation.RAW, start=0, end=2),
            tokenizer="whitespace@1.0",
            created_at=NOW,
        ),
        Form: Form(
            id=new_id(IdPrefix.FORM),
            language="mzr",
            orthography_profile="mzr-nfc@1.0",
            text="abc",
            run_id=run_id,
            created_at=NOW,
        ),
        Concept: Concept(
            id=new_id(IdPrefix.CONCEPT),
            canonical_label="canoa",
            run_id=run_id,
            created_at=NOW,
        ),
        Lexeme: Lexeme(
            id=lexeme_id,
            language="mzr",
            register="neutral",
            run_id=run_id,
            created_at=NOW,
        ),
        FormLexemeLink: FormLexemeLink(
            id=new_id(IdPrefix.FORM_LEXEME),
            form_id=form_id,
            lexeme_id=lexeme_id,
            run_id=run_id,
            created_at=NOW,
        ),
        Sense: Sense(
            id=sense_id,
            lexeme_id=lexeme_id,
            glosses={"por": ["canoa"]},
            register="neutral",
            run_id=run_id,
            created_at=NOW,
        ),
        EvidenceItem: EvidenceItem(
            id=new_id(IdPrefix.EVIDENCE),
            kind=EvidenceKind.TOKEN_ALIGNMENT,
            polarity=EvidencePolarity.SUPPORTS,
            target_id=new_id(IdPrefix.TOKEN),
            run_id=run_id,
            created_at=NOW,
        ),
        LineageEdge: LineageEdge(
            id=new_id(IdPrefix.LINEAGE),
            from_id=segment.id,
            to_id=source_object_id,
            kind=LineageKind.DERIVED_FROM,
            run_id=run_id,
            created_at=NOW,
        ),
        SegmentAlignment: SegmentAlignment(
            id=new_id(IdPrefix.SEGMENT_ALIGNMENT),
            source_segment_ids=(segment.id,),
            target_segment_ids=(new_id(IdPrefix.SEGMENT),),
            method="canonical_locator@0.1.0",
            mode=AlignmentMode.CANONICAL,
            status=AlignmentStatus.STRUCTURAL,
            group_key=SHA,
            run_id=run_id,
            created_at=NOW,
        ),
        GoldAlignment: GoldAlignment(
            groups=(
                GoldGroup(
                    id="sample-gold",
                    locator_selector=GoldGroupLocatorSelector(
                        namespace="refs",
                        source_members=(
                            {"source_object_path": "texts/source.tsv", "locator": {"ref": "T.1"}},
                        ),
                        target_members=(
                            {"source_object_path": "texts/target.tsv", "locator": {"ref": "T.1"}},
                        ),
                    ),
                    source_normalization_version="norm@1",
                    target_normalization_version="norm@1",
                    source_tokenizer_version="tok@1",
                    target_tokenizer_version="tok@1",
                    source_tokens=(GoldTokenSelector(member=0, ordinal=0),),
                    target_tokens=(GoldTokenSelector(member=0, ordinal=0),),
                    sure_links=((0, 0),),
                    possible_links=((0, 0),),
                    authority="sample",
                ),
            )
        ),
        TokenAlignmentEdge: TokenAlignmentEdge(
            id=new_id(IdPrefix.TOKEN_ALIGNMENT),
            segment_alignment_id=new_id(IdPrefix.SEGMENT_ALIGNMENT),
            source_token_id=new_id(IdPrefix.TOKEN),
            target_token_id=new_id(IdPrefix.TOKEN),
            direction=AlignmentDirection.SYMMETRIZED,
            algorithm="eflomal@0.1.0",
            symmetrization=Symmetrization.INTERSECTION,
            run_id=run_id,
            created_at=NOW,
        ),
        ReviewTask: ReviewTask(
            id=task_id,
            task_type=ReviewTaskType.LEXICAL_SENSE,
            target_id=sense_id,
            required_role="community_linguist",
            priority=0.75,
            reason="competing_glosses",
            creator_run_id=run_id,
            created_at=NOW,
        ),
        ReviewDecision: ReviewDecision(
            id=new_id(IdPrefix.REVIEW_DECISION),
            task_id=task_id,
            target_id=sense_id,
            decision=ReviewDecisionKind.ACCEPT,
            reviewer_id="reviewer-maria",
            reviewer_role="community_linguist",
            created_at=NOW,
        ),
        IGTObservation: IGTObservation(
            id=new_id(IdPrefix.IGT_OBSERVATION),
            source_id=source_id,
            source_object_id=source_object_id,
            run_id=run_id,
            record_ordinal=0,
            format=IgtFormat.TOOLBOX,
            locator={"ref": "T.1"},
            tiers=[
                IgtTierLine(marker="\\tx", line_number=1, raw="\\tx sample-token"),
                IgtTierLine(marker="\\ge", line_number=3, raw="\\ge SAMPLE-GLOSS"),
            ],
            words=[
                IgtWord(
                    ordinal=0,
                    text="sample-token",
                    morphs=[IgtMorph(ordinal=0, text="sample-token")],
                )
            ],
            parse_status=IgtParseStatus.OK,
            created_at=NOW,
        ),
        Feature: Feature(
            id=new_id(IdPrefix.FEATURE),
            namespace="local:mzr",
            label="SAMPLELABEL",
            definition="source gloss label SAMPLELABEL",
            defined_by="source_gloss_label",
            run_id=run_id,
            created_at=NOW,
        ),
        Morpheme: Morpheme(
            id=new_id(IdPrefix.MORPHEME),
            language="mzr",
            role=MorphRole.ROOT,
            canonical_form="sample",
            form_basis=FormBasis.SURFACE,
            gloss_labels=["SAMPLELABEL"],
            identity_key=SHA,
            run_id=run_id,
            created_at=NOW,
        ),
        Allomorph: Allomorph(
            id=new_id(IdPrefix.ALLOMORPH),
            morpheme_id=new_id(IdPrefix.MORPHEME),
            form="sample",
            form_basis=FormBasis.SURFACE,
            conditioning=AllomorphConditioning.LEXICAL,
            run_id=run_id,
            created_at=NOW,
        ),
        MorphAnalysis: MorphAnalysis(
            id=new_id(IdPrefix.MORPH_ANALYSIS),
            target_token_id=new_id(IdPrefix.TOKEN),
            analysis_kind=AnalysisKind.SEGMENTED,
            method="igt_assertion@0.1.0",
            span_representation=SpanRepresentation.NORMALIZED,
            surface="sample-token",
            signature=SHA,
            run_id=run_id,
            created_at=NOW,
        ),
        MorphSegment: MorphSegment(
            id=new_id(IdPrefix.MORPH_SEGMENT),
            analysis_id=new_id(IdPrefix.MORPH_ANALYSIS),
            ordinal=0,
            start=0,
            end=6,
            surface="sample",
            created_at=NOW,
        ),
        MorphSegmentFeature: MorphSegmentFeature(
            segment_id=new_id(IdPrefix.MORPH_SEGMENT),
            feature_id=new_id(IdPrefix.FEATURE),
            basis=FeatureAssignmentBasis.IGT_GLOSS,
            created_at=NOW,
        ),
        SourceUseApproval: SourceUseApproval(
            id=new_id(IdPrefix.SOURCE_USE_APPROVAL),
            source_id=source_id,
            operation=Operation.EXTRACT,
            action=ApprovalAction.GRANT,
            approver_id="steward-sample",
            approver_role="governance_steward",
            basis="sample consent record",
            run_id=run_id,
            created_at=NOW,
        ),
        MorphGold: MorphGold(
            gold_id="sample-gold",
            language="mzr",
            items=[
                {
                    "selector": {"igt_ref": "1"},
                    "surface": "sample-token",
                    "segments": [[0, 6], [7, 12]],
                }
            ],
            provenance={"origin": "held-out igt records"},
        ),
    }


def test_committed_schemas_match_generated() -> None:
    assert check(SCHEMA_DIR) == []


def test_every_schema_model_has_unique_name() -> None:
    names = [model.SCHEMA_NAME for model in SCHEMA_MODELS]
    assert all(name is not None for name in names)
    assert len(names) == 29
    assert len(set(names)) == len(names)


def test_schema_has_id_and_version() -> None:
    for model in SCHEMA_MODELS:
        document = json.loads(render_schema(model))
        assert document["$id"] == f"urn:langpipe:schema:{model.SCHEMA_NAME}:{model.SCHEMA_VERSION}"
        assert document["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert document["x-schema-name"] == model.SCHEMA_NAME
        assert document["x-schema-version"] == model.SCHEMA_VERSION
        assert schema_filename(model) == f"{model.SCHEMA_NAME}.v{model.SCHEMA_VERSION}.schema.json"


def test_check_reports_unexpected_file(tmp_path: Path) -> None:
    generate(tmp_path)
    (tmp_path / "stray.schema.json").write_text("{}\n", encoding="utf-8")
    assert check(tmp_path) == ["stray.schema.json"]


def test_check_reports_missing_and_changed_files(tmp_path: Path) -> None:
    generate(tmp_path)
    missing = schema_filename(SCHEMA_MODELS[0])
    changed = schema_filename(SCHEMA_MODELS[1])
    (tmp_path / missing).unlink()
    (tmp_path / changed).write_text("{}\n", encoding="utf-8")
    assert check(tmp_path) == sorted([missing, changed])


def test_check_of_fresh_generation_is_clean(tmp_path: Path) -> None:
    generate(tmp_path)
    assert check(tmp_path) == []


def test_render_is_deterministic(tmp_path: Path) -> None:
    for model in SCHEMA_MODELS:
        assert render_schema(model) == render_schema(model)
    first = tmp_path / "first"
    second = tmp_path / "second"
    generate(first)
    generate(second)
    for model in SCHEMA_MODELS:
        name = schema_filename(model)
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_serialization_roundtrip_for_all_schema_models() -> None:
    samples = _samples()
    assert set(samples) == set(SCHEMA_MODELS)
    for model_type, instance in samples.items():
        restored = model_type.model_validate_json(instance.model_dump_json())
        assert restored == instance
