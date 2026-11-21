"""CLI commands for autonomous indigenous resource harvesting."""

from typing import Annotated

import typer

from langpipe.harvest.models import HarvesterTarget, HarvestStatus
from langpipe.harvest.registry import UniversalSourceRegistry
from langpipe.harvest.service import HarvestService

harvest_app = typer.Typer(
    name="harvest",
    help="Autonomous web harvesting, deep research, and cross-language repository indexing.",
)


@harvest_app.command("search")
def search_language(
    lang: Annotated[
        str,
        typer.Option("--lang", "-l", help="ISO 639-3 language code (e.g. mzr, tca, mcf, cul)"),
    ],
    name: Annotated[
        str | None,
        typer.Option("--name", "-n", help="Language name (e.g. Tikuna, Matsés)"),
    ] = None,
    family: Annotated[
        str | None,
        typer.Option("--family", "-f", help="Language family (e.g. Pano, Ticuna-Yurí, Arawa)"),
    ] = None,
    glotto: Annotated[
        str | None,
        typer.Option("--glotto", "-g", help="Glottocode (e.g. ticu1245, maru1252)"),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Max results per spider")] = 10,
) -> None:
    """Scour open web archives, scholarly APIs, and thesis repositories for a language."""
    registry = UniversalSourceRegistry()
    target = registry.get_target(lang)

    if not target:
        # Construct target on the fly if not yet registered
        target_name = name or lang.upper()
        target_family = family or "Indigenous"
        target = HarvesterTarget(
            iso639_3=lang,
            language_name=target_name,
            family=target_family,
            glottocode=glotto,
        )
        registry.register_target(target)

    typer.echo(
        f"🔍 Launching Autonomous Deep Harvest for {target.language_name} "
        f"({target.iso639_3}) [Family: {target.family}]..."
    )
    service = HarvestService(registry=registry)
    discovered = service.discover(target, limit_per_spider=limit)

    typer.echo(
        f"\n✅ Discovery complete! Found {len(discovered)} resources across web repositories.\n"
    )
    for idx, r in enumerate(discovered, 1):
        oa_mark = "🔓 OA" if r.download_url else "📄 REF"
        typer.echo(
            f" {idx:2d}. [{r.repository_id.upper()}] {oa_mark} {r.title} ({r.year or 'n.d.'})"
        )
        if r.download_url:
            typer.echo(f"     Download: {r.download_url}")
        else:
            typer.echo(f"     URL: {r.url}")

    # Cross-language recommendations
    recs = registry.get_cross_language_recommendations(lang)
    if recs:
        typer.echo(
            f"\n🌐 Cross-Language Discovery Triggered: Recommended next languages to crawl: "
            f"{', '.join(recs)}"
        )


@harvest_app.command("list")
def list_catalog(
    lang: Annotated[
        str | None,
        typer.Option("--lang", "-l", help="Filter by ISO 639-3 code"),
    ] = None,
    status: Annotated[
        str | None,
        typer.Option("--status", "-s", help="Filter by status (indexed, downloaded)"),
    ] = None,
) -> None:
    """List all indexed resources in the Universal Indigenous Resource Registry."""
    registry = UniversalSourceRegistry()
    status_enum = HarvestStatus(status) if status else None
    resources = registry.list_resources(language_code=lang, status=status_enum)

    typer.echo(f"📚 Universal Indigenous Resource Registry ({len(resources)} entries):\n")
    for idx, r in enumerate(resources, 1):
        stat_icon = "💾" if r.status == HarvestStatus.DOWNLOADED else "⏳"
        typer.echo(
            f" {idx:2d}. {stat_icon} [{r.language_code}] [{r.repository_id.upper()}] {r.title}"
        )
        typer.echo(f"     Policy: {r.policy.value} | Status: {r.status.value}")
        if r.local_path:
            typer.echo(
                f"     Local: {r.local_path} (SHA: {r.sha256[:12] if r.sha256 else 'none'}...)"
            )


@harvest_app.command("download")
def download_asset(
    source_id: Annotated[str, typer.Option("--source-id", "-s", help="Source ID to download")],
) -> None:
    """Download a discovered asset to immutable storage and verify its SHA-256 hash."""
    registry = UniversalSourceRegistry()
    resources = [r for r in registry.list_resources() if r.source_id == source_id]
    if not resources:
        typer.echo(f"❌ Error: source_id '{source_id}' not found in registry.")
        raise typer.Exit(code=1)

    res = resources[0]
    if not res.download_url:
        typer.echo(f"❌ Error: resource '{source_id}' has no direct download URL.")
        raise typer.Exit(code=1)

    typer.echo(f"⬇️ Downloading {res.title} from {res.download_url}...")
    service = HarvestService(registry=registry)
    updated = service.download_resource(res)
    typer.echo(f"✅ Downloaded to {updated.local_path} ({updated.file_size_bytes} bytes)")
    typer.echo(f"🔒 SHA-256: {updated.sha256}")
