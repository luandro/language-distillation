from langpipe.domain.models.alignment import SegmentAlignment, TokenAlignmentEdge
from langpipe.domain.models.approval import SourceUseApproval
from langpipe.domain.models.base import DomainModel
from langpipe.domain.models.evidence import EvidenceItem, LineageEdge
from langpipe.domain.models.igt import IGTObservation
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
from langpipe.domain.models.observation import Form, Segment, TokenOccurrence
from langpipe.domain.models.review import ReviewDecision, ReviewTask
from langpipe.domain.models.run import Artifact, ProcessingRun
from langpipe.domain.models.source import Source, SourceManifest, SourceObject, SourcePolicy
from langpipe.evaluation.alignment import GoldAlignment

# AuditEvent and RawBlob are internal and deliberately not schema-exported in M1.
SCHEMA_MODELS: tuple[type[DomainModel], ...] = (
    SourceManifest,
    SourcePolicy,
    Source,
    SourceObject,
    ProcessingRun,
    Artifact,
    Segment,
    TokenOccurrence,
    Form,
    EvidenceItem,
    LineageEdge,
    SegmentAlignment,
    TokenAlignmentEdge,
    GoldAlignment,
    Concept,
    Lexeme,
    FormLexemeLink,
    Sense,
    ReviewTask,
    ReviewDecision,
    # M5 IGT observation and morphology graph (ADR-0017) and approvals (ADR-0018):
    IGTObservation,
    Feature,
    Morpheme,
    Allomorph,
    MorphAnalysis,
    MorphSegment,
    MorphSegmentFeature,
    SourceUseApproval,
    MorphGold,
)
