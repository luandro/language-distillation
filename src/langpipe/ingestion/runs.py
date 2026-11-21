from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from pydantic import JsonValue

from langpipe import __version__
from langpipe.app_context import AppContext
from langpipe.domain.enums import LineageKind, RunIoRole, RunStage, RunStatus
from langpipe.domain.errors import InvalidLineage
from langpipe.domain.hashing import config_hash
from langpipe.domain.ids import IdPrefix
from langpipe.domain.models.evidence import LineageEdge
from langpipe.domain.models.run import Artifact, ProcessingRun

TOOL_VERSION = __version__


@dataclass(frozen=True)
class RunOutcome:
    run: ProcessingRun
    reused: bool


class RunRecorder:
    """Owns processing-run rows. Status changes go through the repository's run methods."""

    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx

    def find_reusable(
        self,
        stage: RunStage,
        tool_name: str,
        config: Mapping[str, JsonValue],
        input_ids: Iterable[str],
    ) -> ProcessingRun | None:
        _, run_key = _identity(stage, tool_name, config, input_ids)
        return self._ctx.repo.find_succeeded_run(run_key)

    def start(
        self,
        stage: RunStage,
        tool_name: str,
        config: Mapping[str, JsonValue],
        input_ids: Iterable[str],
    ) -> ProcessingRun:
        digest, run_key = _identity(stage, tool_name, config, input_ids)
        run = ProcessingRun(
            id=self._ctx.new_id(IdPrefix.RUN),
            stage=stage,
            tool_name=tool_name,
            tool_version=TOOL_VERSION,
            config=dict(config),
            config_hash=digest,
            code_revision=self._ctx.code_revision,
            run_key=run_key,
            status=RunStatus.RUNNING,
            started_at=self._ctx.clock(),
        )
        # Committed on its own so that a failed semantic transaction can still record the failure.
        with self._ctx.repo.transaction():
            self._ctx.repo.add_run(run)
        return run

    def succeed(self, run_id: str) -> ProcessingRun:
        # Must be called inside the caller's semantic transaction.
        return self._ctx.repo.finish_run(run_id, RunStatus.SUCCEEDED, self._ctx.clock())

    def fail(
        self,
        run_id: str,
        error: BaseException,
        artifact: Artifact | None = None,
        artifact_inputs: Sequence[str] = (),
    ) -> ProcessingRun:
        # Persists only the exception type; messages may contain restricted content.
        if artifact is not None and artifact.run_id != run_id:
            # An artifact carries exactly one creating run (DOMAIN-MODEL / invariant 4).
            raise InvalidLineage()
        with self._ctx.repo.transaction():
            failed = self._ctx.repo.finish_run(
                run_id,
                RunStatus.FAILED,
                self._ctx.clock(),
                error_type=type(error).__name__,
                error_message=None,
            )
            if artifact is not None:
                self._ctx.repo.add_artifact(artifact)
                self._ctx.repo.add_run_io(run_id, artifact.id, RunIoRole.OUTPUT)
                for input_id in artifact_inputs:
                    self._ctx.repo.add_lineage_edge(
                        LineageEdge(
                            id=self._ctx.new_id(IdPrefix.LINEAGE),
                            from_id=artifact.id,
                            to_id=input_id,
                            kind=LineageKind.DERIVED_FROM,
                            run_id=run_id,
                            created_at=self._ctx.clock(),
                        )
                    )
            return failed


def _identity(
    stage: RunStage,
    tool_name: str,
    config: Mapping[str, JsonValue],
    input_ids: Iterable[str],
) -> tuple[str, str]:
    digest = config_hash(config)
    run_key = ProcessingRun.compute_run_key(stage, tool_name, TOOL_VERSION, digest, input_ids)
    return digest, run_key
