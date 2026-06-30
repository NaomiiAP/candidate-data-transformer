"""
Command-line interface for the Candidate Data Transformer pipeline.

Usage:
    candidate-transformer --csv recruiter.csv --json ats.json --output result.json
    candidate-transformer --csv data.csv --linkedin profile.json -v
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import click

from candidate_transformer import __version__
from candidate_transformer.pipeline import run_pipeline
from candidate_transformer.projection import ProjectionConfig

BANNER = r"""
=============================================================
  C A N D I D A T E   D A T A   T R A N S F O R M E R
=============================================================
  Multi-Source Candidate Profile Pipeline | v{version}
=============================================================
"""

logger = logging.getLogger("candidate_transformer")


def _print_banner(version: str) -> None:
    """Display the startup banner."""
    click.echo(click.style(BANNER.format(version=version), fg="cyan", bold=True), err=True)


def _configure_logging(verbose: bool) -> None:
    """Set up structured logging with appropriate level."""
    level = logging.DEBUG if verbose else logging.WARNING
    fmt = "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    logging.basicConfig(level=level, format=fmt, datefmt=datefmt, stream=sys.stderr)


def _build_sources(
    csv_file: str | None,
    json_file: str | None,
    github_source: str | None,
    linkedin_file: str | None,
    resume_pdf: str | None,
    resume_docx: str | None,
    notes_file: str | None,
) -> dict[str, str]:
    """Build the sources dictionary from CLI arguments."""
    sources: dict[str, str] = {}

    if csv_file:
        sources["recruiter_csv"] = csv_file
    if json_file:
        sources["ats_json"] = json_file
    if github_source:
        sources["github"] = github_source
    if linkedin_file:
        sources["linkedin"] = linkedin_file
    if resume_pdf:
        sources["resume_pdf"] = resume_pdf
    if resume_docx:
        sources["resume_docx"] = resume_docx
    if notes_file:
        sources["recruiter_notes"] = notes_file

    return sources


def _load_projection_config(config_file: str | None) -> ProjectionConfig | None:
    """Load and validate projection configuration from a JSON file."""
    if not config_file:
        return None

    path = Path(config_file)
    try:
        config_data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise click.BadParameter(
            f"Config file '{config_file}' contains invalid JSON: {exc}",
            param_hint="'--config'",
        )
    except OSError as exc:
        raise click.BadParameter(
            f"Cannot read config file '{config_file}': {exc}",
            param_hint="'--config'",
        )

    try:
        config = ProjectionConfig(**config_data)
    except (TypeError, ValueError) as exc:
        raise click.BadParameter(
            f"Invalid projection config structure: {exc}",
            param_hint="'--config'",
        )

    logger.info("Loaded projection config from %s", config_file)
    return config


class ColoredHelpFormatter(click.HelpFormatter):
    """Custom Click HelpFormatter to add ANSI color highlighting."""

    def write_heading(self, heading: str) -> None:
        colored = click.style(heading, fg="cyan", bold=True)
        super().write_heading(colored)

    def write_usage(self, prog: str, args: str = "", prefix: str = "Usage: ") -> None:
        colored_prefix = click.style(prefix, fg="yellow", bold=True)
        colored_prog = click.style(prog, fg="green", bold=True)
        super().write_usage(colored_prog, args, prefix=colored_prefix)

    def write_dl(self, rows: list[tuple[str, str]], col_max: int = 30, col_spacing: int = 2) -> None:
        colored_rows = []
        for term, detail in rows:
            colored_term = click.style(term, fg="green")
            colored_rows.append((colored_term, detail))
        super().write_dl(colored_rows, col_max, col_spacing)


class ColoredHelpCommand(click.Command):
    """Custom Click Command to intercept help generation and inject ColoredHelpFormatter."""

    def get_help(self, ctx: click.Context) -> str:
        formatter = ColoredHelpFormatter(
            width=ctx.terminal_width, max_width=ctx.max_content_width
        )
        self.format_help(ctx, formatter)
        return formatter.getvalue().rstrip("\n")


@click.command(cls=ColoredHelpCommand, context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--csv",
    "csv_file",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to recruiter CSV file.",
)
@click.option(
    "--json",
    "json_file",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to ATS JSON file.",
)
@click.option(
    "--github",
    "github_source",
    type=str,
    help="GitHub username, URL, or path to cached JSON file.",
)
@click.option(
    "--linkedin",
    "linkedin_file",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to LinkedIn profile JSON file.",
)
@click.option(
    "--resume-pdf",
    "resume_pdf",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to resume PDF file.",
)
@click.option(
    "--resume-docx",
    "resume_docx",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to resume DOCX file.",
)
@click.option(
    "--notes",
    "notes_file",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to recruiter notes TXT file.",
)
@click.option(
    "--config",
    "config_file",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to projection config JSON (controls output shape).",
)
@click.option(
    "--output",
    "output_file",
    type=click.Path(dir_okay=False, writable=True),
    help="Output file path. Defaults to stdout if omitted.",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Enable verbose (DEBUG-level) logging to stderr.",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    default=False,
    help="Suppress the startup banner.",
)
@click.option(
    "--ui",
    is_flag=True,
    default=False,
    help="Launch the interactive web UI dashboard.",
)
@click.version_option(version=__version__, prog_name="candidate-transformer")
def main(
    csv_file: str | None,
    json_file: str | None,
    github_source: str | None,
    linkedin_file: str | None,
    resume_pdf: str | None,
    resume_docx: str | None,
    notes_file: str | None,
    config_file: str | None,
    output_file: str | None,
    verbose: bool,
    quiet: bool,
    ui: bool,
) -> None:
    """Multi-Source Candidate Data Transformer

    Ingests candidate data from multiple sources (CSV, JSON, GitHub, LinkedIn,
    resumes, recruiter notes), normalizes fields, resolves entity matches,
    merges records with conflict resolution, and outputs a unified canonical
    profile with provenance tracking and confidence scores.

    \b
    Examples:
        # Single CSV source
        candidate-transformer --csv recruiter.csv

    \b
        # Multiple sources with custom output
        candidate-transformer --csv data.csv --json ats.json --output result.json

    \b
        # All sources with projection config
        candidate-transformer --csv data.csv --json ats.json \\
            --github octocat --linkedin profile.json \\
            --notes notes.txt --config projection.json -v

    \b
        # Pipe output to jq for pretty formatting
        candidate-transformer --csv data.csv | jq '.candidates[0].full_name'
    """
    _configure_logging(verbose)

    if ui:
        from candidate_transformer.web_ui import start_ui
        start_ui()
        sys.exit(0)

    if not quiet:
        _print_banner(__version__)

    # Build sources from CLI arguments
    sources = _build_sources(
        csv_file, json_file, github_source, linkedin_file,
        resume_pdf, resume_docx, notes_file,
    )

    if not sources:
        click.echo(
            click.style(
                "Error: At least one data source must be provided.\n"
                "Run 'candidate-transformer --help' for available options.",
                fg="red",
            ),
            err=True,
        )
        sys.exit(1)

    # Load optional projection config first
    config = _load_projection_config(config_file)

    t_start = time.perf_counter()

    if not quiet:
        click.echo(
            click.style("\n[1/4] Ingesting and Normalizing Sources...", fg="cyan", bold=True),
            err=True,
        )
        for s_type, s_path in sorted(sources.items()):
            click.echo(
                click.style("  * Ingesting ", fg="white")
                + click.style(f"{s_type:<16}", fg="yellow")
                + click.style(f" from '{s_path}'...", fg="white"),
                err=True,
            )
        if config:
            click.echo(
                click.style("  * Projection ", fg="white")
                + click.style("custom config loaded", fg="magenta"),
                err=True,
            )

    try:
        results = run_pipeline(sources, config)
    except FileNotFoundError as exc:
        click.echo(
            click.style(f"Error: Source file not found - {exc}", fg="red"),
            err=True,
        )
        sys.exit(1)
    except ValueError as exc:
        click.echo(
            click.style(f"Error: Invalid input data - {exc}", fg="red"),
            err=True,
        )
        sys.exit(1)
    except Exception as exc:
        click.echo(
            click.style(f"Error: Pipeline failed - {exc}", fg="red"),
            err=True,
        )
        logger.exception("Unhandled pipeline error")
        sys.exit(1)

    # Extract candidates list from results
    candidates: list[dict] = []
    if isinstance(results, dict) and "candidates" in results:
        candidates = results["candidates"]
    elif isinstance(results, list):
        candidates = results
    elif isinstance(results, dict):
        candidates = [results]

    if not quiet:
        click.echo(
            click.style("\n[2/4] Resolving Entities and Matching Profiles...", fg="cyan", bold=True),
            err=True,
        )
        click.echo(
            click.style("  * Grouped into ", fg="white")
            + click.style(f"{len(candidates)}", fg="green", bold=True)
            + click.style(" unified candidate profile(s).", fg="white"),
            err=True,
        )

        click.echo(
            click.style("\n[3/4] Merging Records and Computing Confidence...", fg="cyan", bold=True),
            err=True,
        )
        for idx, candidate in enumerate(candidates, 1):
            name = candidate.get("full_name") or "Unknown Candidate"
            
            # Respect include_confidence setting
            show_conf = True
            if config and not config.include_confidence:
                show_conf = False
                
            if show_conf:
                conf = (candidate.get("overall_confidence") if candidate.get("overall_confidence") is not None else candidate.get("_overall_confidence", 0.0)) * 100
                conf_str = f"{conf:>5.1f}%"
            else:
                conf_str = "  N/A"
            
            # Respect include_provenance setting
            show_prov = True
            if config and not config.include_provenance:
                show_prov = False

            sources_str = "N/A"
            if show_prov:
                prov = candidate.get("provenance", [])
                if prov:
                    sources_merged = sorted(list(set(p.get("source") for p in prov if p.get("source"))))
                else:
                    sources_merged = candidate.get("_sources", [])
                if sources_merged:
                    sources_str = ", ".join(sources_merged)

            click.echo(
                click.style(f"  * Profile #{idx}: ", fg="white")
                + click.style(f"{name:<25}", fg="green", bold=True)
                + click.style(f" | Confidence: ", fg="white")
                + click.style(conf_str, fg="yellow", bold=True)
                + click.style(f" | Sources: {sources_str}", fg="white"),
                err=True,
            )

        click.echo(
            click.style("\n[4/4] Projecting Fields & Validating Schema...", fg="cyan", bold=True),
            err=True,
        )
        
        # Check if validation passed or failed
        validation_passed = True
        all_errors = []
        for candidate in candidates:
            errors = candidate.get("_validation_errors", [])
            if errors:
                validation_passed = False
                all_errors.extend(errors)
        
        if validation_passed:
            click.echo(
                click.style("  * Output schema validation: ", fg="white")
                + click.style("PASSED", fg="green", bold=True),
                err=True,
            )
        else:
            click.echo(
                click.style("  * Output schema validation: ", fg="white")
                + click.style("WARNING", fg="red", bold=True)
                + click.style(f" ({len(all_errors)} schema issues detected)", fg="red"),
                err=True,
            )

    elapsed = time.perf_counter() - t_start
    logger.info("Pipeline completed in %.3fs", elapsed)

    # Clean private helper properties before serialization
    if isinstance(results, dict):
        if "candidates" in results:
            for cand in results["candidates"]:
                cand.pop("_sources", None)
                cand.pop("_overall_confidence", None)
        else:
            results.pop("_sources", None)
            results.pop("_overall_confidence", None)

    # Serialize output
    output_json = json.dumps(results, indent=2, ensure_ascii=False, default=str)

    # Write or print
    if output_file:
        out_path = Path(output_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_json, encoding="utf-8")
        if not quiet:
            click.echo(
                click.style("\n  [OK] Output written to ", fg="green", bold=True)
                + click.style(str(out_path), fg="cyan"),
                err=True,
            )
    else:
        click.echo(output_json)

    # Summary box
    if not quiet:
        summary_border = "=" * 65
        click.echo(click.style(f"\n{summary_border}", fg="cyan"), err=True)
        click.echo(
            click.style("  Transformation Summary:", fg="white", bold=True),
            err=True,
        )
        click.echo(
            click.style(f"    - Input Sources   : {len(sources)} source file(s)", fg="white"),
            err=True,
        )
        click.echo(
            click.style(f"    - Unified Profiles: {len(candidates)} profile(s) generated", fg="white"),
            err=True,
        )
        click.echo(
            click.style(f"    - Execution Time  : {elapsed:.3f} seconds", fg="white"),
            err=True,
        )
        if output_file:
            click.echo(
                click.style(f"    - Output File     : {output_file}", fg="cyan"),
                err=True,
            )
        click.echo(click.style(f"{summary_border}\n", fg="cyan"), err=True)


if __name__ == "__main__":
    main()
