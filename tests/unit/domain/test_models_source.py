from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from langpipe.domain.enums import AccessClass, Operation, PolicyMode, SourceType
from langpipe.domain.ids import IdPrefix, new_id
from langpipe.domain.models.source import (
    ObjectSpec,
    PolicySpec,
    Provenance,
    RawBlob,
    Source,
    SourceManifest,
    SourceObject,
    SourcePolicy,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
SHA = "a" * 64


def _manifest_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "manifest_version": 1,
        "key": "sample-source",
        "title": "Sample source",
        "source_type": SourceType.PARALLEL_TEXT,
        "languages": ["mzr", "por"],
        "provenance": {"acquired_from": "field notebook"},
        "acquired_at": NOW,
        "policy": {
            "mode": PolicyMode.DISTILL_ONLY,
            "access_class": AccessClass.RESTRICTED,
            "authority": "community council",
        },
        "objects": [
            {"path": "texts/a.txt", "media_type": "text/plain"},
        ],
    }
    data.update(overrides)
    return data


def _source_object(**overrides: object) -> SourceObject:
    data: dict[str, object] = {
        "id": new_id(IdPrefix.SOURCE_OBJECT),
        "source_id": new_id(IdPrefix.SOURCE),
        "original_path": "texts/a.txt",
        "origin_uri": "file:///data/texts/a.txt",
        "sha256": SHA,
        "size_bytes": 12,
        "media_type": "text/plain",
        "access_class": AccessClass.RESTRICTED,
        "registration_run_id": new_id(IdPrefix.RUN),
        "created_at": NOW,
    }
    data.update(overrides)
    return SourceObject.model_validate(data)


def test_source_object_is_frozen() -> None:
    obj = _source_object()
    with pytest.raises(ValidationError):
        obj.size_bytes = 99  # type: ignore[misc]


def test_manifest_rejects_parent_path() -> None:
    with pytest.raises(ValidationError):
        SourceManifest.model_validate(
            _manifest_data(objects=[{"path": "texts/../secret.txt", "media_type": "text/plain"}])
        )


def test_manifest_rejects_absolute_path() -> None:
    with pytest.raises(ValidationError):
        ObjectSpec(path="/etc/passwd", media_type="text/plain")


def test_manifest_rejects_backslash_path() -> None:
    with pytest.raises(ValidationError):
        ObjectSpec(path="texts\\a.txt", media_type="text/plain")


def test_manifest_object_access_class_cannot_be_more_permissive() -> None:
    with pytest.raises(ValidationError):
        SourceManifest.model_validate(
            _manifest_data(
                objects=[
                    {
                        "path": "texts/a.txt",
                        "media_type": "text/plain",
                        "access_class": AccessClass.PUBLIC,
                    }
                ]
            )
        )


def test_manifest_exclude_may_have_no_objects() -> None:
    manifest = SourceManifest.model_validate(
        _manifest_data(
            objects=[],
            policy={
                "mode": PolicyMode.EXCLUDE,
                "access_class": AccessClass.HIGHLY_RESTRICTED,
                "authority": "community council",
            },
        )
    )
    assert manifest.objects == []


def test_manifest_non_exclude_requires_objects() -> None:
    with pytest.raises(ValidationError):
        SourceManifest.model_validate(_manifest_data(objects=[]))


def test_manifest_sha256_stable_under_yaml_key_order() -> None:
    forward = {"b": 2, "a": 1}
    reverse = {"a": 1, "b": 2}
    first = SourceManifest.model_validate(
        _manifest_data(
            policy={
                "mode": PolicyMode.DISTILL_ONLY,
                "access_class": AccessClass.RESTRICTED,
                "authority": "community council",
                "restrictions": forward,
            }
        )
    )
    second = SourceManifest.model_validate(
        _manifest_data(
            policy={
                "mode": PolicyMode.DISTILL_ONLY,
                "access_class": AccessClass.RESTRICTED,
                "authority": "community council",
                "restrictions": reverse,
            }
        )
    )
    assert first.manifest_sha256() == second.manifest_sha256()
    assert len(first.manifest_sha256()) == 64


def test_policy_rejects_allow_of_hard_denied_op() -> None:
    # redistribute_raw is hard-denied under distill_only in the ADR-0007 baseline matrix.
    with pytest.raises(ValidationError):
        PolicySpec(
            mode=PolicyMode.DISTILL_ONLY,
            access_class=AccessClass.RESTRICTED,
            authority="owner",
            allow=[Operation.REDISTRIBUTE_RAW],
        )


def test_policy_lists_sorted_and_deduped() -> None:
    spec = PolicySpec(
        mode=PolicyMode.REVIEW_REQUIRED,
        access_class=AccessClass.RESTRICTED,
        authority="owner",
        allow=[Operation.HUMAN_REVIEW, Operation.EXTRACT, Operation.HUMAN_REVIEW],
        deny=[Operation.THIRD_PARTY_API, Operation.CLOUD_PROCESSING, Operation.THIRD_PARTY_API],
    )
    policy = SourcePolicy(
        id=new_id(IdPrefix.POLICY),
        mode=spec.mode,
        access_class=spec.access_class,
        authority=spec.authority,
        allow=spec.allow,
        deny=spec.deny,
        created_at=NOW,
    )
    assert policy.allow == tuple(sorted({Operation.HUMAN_REVIEW, Operation.EXTRACT}, key=str))
    assert policy.deny == tuple(
        sorted({Operation.THIRD_PARTY_API, Operation.CLOUD_PROCESSING}, key=str)
    )


def test_policy_rejects_allow_of_hard_denied_op_on_model() -> None:
    with pytest.raises(ValidationError):
        SourcePolicy(
            id=new_id(IdPrefix.POLICY),
            mode=PolicyMode.DISTILL_ONLY,
            access_class=AccessClass.RESTRICTED,
            authority="owner",
            allow=(Operation.REDISTRIBUTE_RAW,),
            deny=(),
            created_at=NOW,
        )


def test_languages_accept_und() -> None:
    manifest = SourceManifest.model_validate(_manifest_data(languages=["und", "qaa"]))
    assert manifest.languages == ["und", "qaa"]


def test_manifest_rejects_duplicate_languages() -> None:
    with pytest.raises(ValidationError):
        SourceManifest.model_validate(_manifest_data(languages=["mzr", "mzr"]))


def test_manifest_rejects_naive_acquired_at() -> None:
    with pytest.raises(ValidationError):
        SourceManifest.model_validate(_manifest_data(acquired_at=datetime(2026, 1, 1)))


def test_datetimes_must_be_utc_not_other_offset() -> None:
    offset = timezone(timedelta(hours=2))
    with pytest.raises(ValidationError):
        SourceManifest.model_validate(
            _manifest_data(acquired_at=datetime(2026, 1, 1, tzinfo=offset))
        )


def test_provenance_fields_optional() -> None:
    provenance = Provenance(acquired_from="archive")
    assert provenance.rights_holder is None
    assert provenance.collector is None
    assert provenance.notes is None


def test_source_model_defaults_and_immutability() -> None:
    source = Source(
        id=new_id(IdPrefix.SOURCE),
        key="sample-source",
        title="Sample",
        source_type=SourceType.OTHER,
        languages=("mzr",),
        provenance=Provenance(acquired_from="archive"),
        policy_id=new_id(IdPrefix.POLICY),
        acquired_at=NOW,
        domains=(),
        registers=(),
        manifest_sha256=SHA,
        registration_run_id=new_id(IdPrefix.RUN),
        created_at=NOW,
        updated_at=NOW,
    )
    assert source.status.value == "registered"
    with pytest.raises(ValidationError):
        source.title = "changed"  # type: ignore[misc]


def test_raw_blob_storage_backend_is_local_only() -> None:
    blob = RawBlob(
        sha256=SHA,
        size_bytes=3,
        storage_backend="local",
        stored_at=NOW,
        ingestion_run_id=new_id(IdPrefix.RUN),
    )
    assert blob.storage_backend == "local"
    with pytest.raises(ValidationError):
        RawBlob(
            sha256=SHA,
            size_bytes=3,
            storage_backend="s3",  # type: ignore[arg-type]
            stored_at=NOW,
            ingestion_run_id=new_id(IdPrefix.RUN),
        )


def test_source_object_rejects_negative_size() -> None:
    with pytest.raises(ValidationError):
        _source_object(size_bytes=-1)


def test_manifest_key_pattern_enforced() -> None:
    with pytest.raises(ValidationError):
        SourceManifest.model_validate(_manifest_data(key="Bad_Key"))


def test_source_schema_names() -> None:
    assert SourceObject.SCHEMA_NAME == "source-object"
    assert SourcePolicy.SCHEMA_NAME == "source-policy"
    assert Source.SCHEMA_NAME == "source"
    assert SourceManifest.SCHEMA_NAME == "source-manifest"
