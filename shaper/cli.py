"""
Signalis Framework

Command-line interface for transforming messy data into clean CSVs.
Standalone data preparation tool.
"""

import warnings
warnings.filterwarnings('ignore', module='urllib3')

import click
import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

from rich.prompt import Prompt, Confirm
from rich.panel import Panel

from core import __version__
from .banner import (
    show_banner, show_step, show_success, show_error,
    show_warning, show_info, show_preview_table, create_progress, console
)
from .loaders import ApifyLoader, CSVLoader
from .mappers import AutoMapper, InteractiveMapper
from .signals import SignalProcessor
from .normalizers import normalize_domain, normalize_field, split_name
from .exporters import CSVExporter

# Load .env file if it exists (loads APIFY_API_TOKEN, EXA_API_KEY, etc.)
load_dotenv()

# Connector integration (optional — requires pip install -e ".[connector]" or ".[all]")
try:
    from connector.cli import cli as connector_cli
    _has_connector = True
except ImportError:
    connector_cli = None
    _has_connector = False


@click.group(invoke_without_command=True)
@click.pass_context
@click.version_option(version=__version__)
def cli(ctx):
    """
    Signalis Framework - Transform raw data into outreach-ready CSVs

    Run without arguments for interactive mode, or use:
      signalis interactive  - Interactive guided workflow
      signalis connect      - Match supply & demand, enrich contacts, generate intros
      signalis update       - Pull the latest version from GitHub
    """
    # If no subcommand provided, run interactive mode
    if ctx.invoked_subcommand is None:
        ctx.invoke(interactive)


# Register connector as subgroup if available
if _has_connector:
    cli.add_command(connector_cli, name='connect')


@cli.command()
@click.option('--no-banner', is_flag=True, help='Skip banner display')
def interactive(no_banner: bool):
    """
    Interactive mode - Guided workflow for data transformation.

    This is the default mode when running 'signalis' with no arguments.
    """
    show_banner()

    try:
        while True:  # top-level restart loop

            # ── Top-level menu ─────────────────────────────────────────────
            while True:
                has_exa = bool(os.getenv('EXA_API_KEY'))
                has_ai = bool(os.getenv('OPENAI_API_KEY') or os.getenv('ANTHROPIC_API_KEY'))

                if not has_exa or not has_ai:
                    missing = []
                    if not has_exa:
                        missing.append("EXA_API_KEY")
                    if not has_ai:
                        missing.append("AI key")
                    console.print(
                        f"[yellow]▲ Not configured: {', '.join(missing)} — "
                        f"press [bold]3[/bold] to set up[/yellow]\n"
                    )

                console.print("[bold cyan]What would you like to do?[/bold cyan]\n")
                console.print("  [cyan]1[/cyan]  [bold]⚗  Shaper[/bold]      [dim]Transform raw data into outreach-ready CSVs[/dim]")
                console.print("  [cyan]2[/cyan]  [bold]⚯  Connector[/bold]   [dim]Match supply & demand · enrich contacts · generate intros[/dim]")
                console.print("  [cyan]3[/cyan]  ◈  Settings    [dim]Configure API keys[/dim]")
                console.print("  [cyan]4[/cyan]  ⟶  Update      [dim]Pull latest version from GitHub[/dim]")
                console.print("  [cyan]0[/cyan]  ⊗  Exit\n")

                top_choice = Prompt.ask(
                    "Select option",
                    choices=["0", "1", "2", "3", "4"],
                    default="1"
                )

                if top_choice == "3":
                    _do_setup()
                    continue

                if top_choice == "4":
                    click.get_current_context().invoke(update)
                    continue

                if top_choice == "0":
                    console.print("\n[yellow]⊗ Exiting Signalis Framework...[/yellow]\n")
                    return

                break

            # ── Connector ──────────────────────────────────────────────────
            if top_choice == "2":
                if not _has_connector:
                    show_error("Connector not installed.")
                    show_info("Run: pip install -e \".[all]\"")
                else:
                    click.get_current_context().invoke(connector_cli)
                continue

            # ── Shaper — sub-menu ──────────────────────────────────────────
            while True:
                console.print("\n[bold cyan]⚗  Shaper — What do you want to process?[/bold cyan]\n")
                console.print("  [cyan]1[/cyan]  ⚗  Supply data only      [dim]Recruiters, vendors, partners[/dim]")
                console.print("  [cyan]2[/cyan]  ⟶  Demand data only      [dim]Companies hiring, buyers[/dim]")
                console.print("  [cyan]3[/cyan]  ⚯  Both supply & demand  [dim]Full shaping workflow[/dim]")
                console.print("  [cyan]0[/cyan]  ☾  Back                  [dim]Return to main menu[/dim]\n")

                process_choice = Prompt.ask(
                    "Select option",
                    choices=["0", "1", "2", "3"],
                    default="3"
                )

                if process_choice == "0":
                    break  # back to top-level menu

                break

            if process_choice == "0":
                continue  # restart at top-level menu

            datasets_to_process = []

            if process_choice == "1":
                datasets_to_process = ["supply"]
            elif process_choice == "2":
                datasets_to_process = ["demand"]
            else:
                datasets_to_process = ["supply", "demand"]

            # Process each dataset type
            results = {}
            go_back = False

            for idx, data_type in enumerate(datasets_to_process, 1):
                console.print(f"\n[bold cyan]{'='*60}[/bold cyan]")
                console.print(f"[bold green]Processing {data_type.upper()} Data[/bold green]")
                console.print(f"[bold cyan]{'='*60}[/bold cyan]\n")

                n = len(datasets_to_process)

                # Step 2: Choose source for this dataset
                show_step(2 if n == 1 else f"2.{idx}", f"Choose {data_type.upper()} Data Source")
                console.print("\n  [cyan]1[/cyan]  Apify Dataset  [dim](Load via dataset ID)[/dim]")
                console.print("  [cyan]2[/cyan]  CSV File       [dim](Upload local file)[/dim]")
                console.print("  [cyan]0[/cyan]  Back           [dim](Return to main menu)[/dim]\n")

                source_choice = Prompt.ask(
                    f"Select {data_type} source",
                    choices=["0", "1", "2"],
                    default="1"
                )

                # Handle back — return to main menu
                if source_choice == "0":
                    console.print("\n[yellow]↶  Going back...[/yellow]\n")
                    go_back = True
                    break

                # Load data based on source
                if source_choice == "1":
                    records, headers = _interactive_apify_load()
                else:
                    records, headers = _interactive_csv_load()

                # Step 3: Preview data
                show_step(3 if n == 1 else f"3.{idx}", f"{data_type.upper()} Data Preview")
                preview_headers = headers[:5]  # Show first 5 columns
                show_preview_table(records, preview_headers, limit=5)
                show_info(f"Loaded {len(records)} records with {len(headers)} fields")

                # Step 4: Field mapping
                show_step(4 if n == 1 else f"4.{idx}", f"{data_type.upper()} Field Mapping")

                # Auto-detect mappings (data_type-aware: demand includes job_title as signal)
                auto_mapper = AutoMapper(data_type=data_type)
                auto_mapping = auto_mapper.auto_map(records[0])
                confidence = auto_mapper.get_mapping_confidence(auto_mapping)

                if confidence >= 0.8 and auto_mapping.is_complete():
                    show_success(f"Auto-mapping confidence: {confidence*100:.0f}%")

                    # Show detected mappings (signal + context always handled in Step 5)
                    mapping_summary = auto_mapper.get_mapping_summary(auto_mapping)
                    field_to_csv = {
                        'full_name': 'Full Name',
                        'company_name': 'Company Name',
                        'domain': 'Domain',
                        'email': 'Email',
                    }
                    for target, source in mapping_summary.items():
                        csv_name = field_to_csv.get(target, target)
                        show_info(f"  {csv_name}: {source}")

                    # Ask if user wants to use auto-mapping
                    if Confirm.ask("\nUse auto-detected mapping?", default=True):
                        mapping = auto_mapping
                    else:
                        interactive_mapper = InteractiveMapper(headers, records[:5])
                        mapping = interactive_mapper.map(auto_mapping)
                else:
                    if confidence < 0.8:
                        show_warning(f"Auto-mapping confidence low: {confidence*100:.0f}%")

                    interactive_mapper = InteractiveMapper(headers, records[:5])
                    mapping = interactive_mapper.map(auto_mapping)

                # Check if mapping is complete (need at least domain or company_name)
                if not mapping.is_complete():
                    show_error("Need at least one identifier: domain OR company name")
                    show_error("Cannot proceed without any way to identify companies.")
                    raise click.Abort()

                # Warn about missing fields that enrichment will fill
                if not mapping.domain and mapping.company_name:
                    if bool(os.getenv('EXA_API_KEY')):
                        show_warning("No domain mapped — Exa will resolve from company names at Step 7")
                    else:
                        show_warning("No domain mapped and EXA_API_KEY not set — domains will be empty")

                # Step 5: Signal & Context sources
                show_step(5 if n == 1 else f"5.{idx}", f"{data_type.upper()} Signal & Context")

                # ── Column reference list (used by both signal and context pickers) ──
                console.print("\n[dim]Available columns:[/dim]")
                for i, col in enumerate(headers, 1):
                    sample_val = str(records[0].get(col, ''))[:60] if records else ''
                    console.print(f"  [cyan]{i:2}[/cyan]  {col}  [dim]{sample_val}[/dim]")

                def _resolve_col(raw: str):
                    s = raw.strip()
                    if not s:
                        return None
                    if s.isdigit():
                        i = int(s) - 1
                        return headers[i] if 0 <= i < len(headers) else None
                    return s if s in headers else None

                # ── Signal ────────────────────────────────────────────────────
                #
                # Manual source: column OR global text (mutually exclusive).
                # Exa is independent — can run alongside either, or alone.
                #
                #   column only      → per-record signal from data, blank rows stay blank
                #   column + Exa     → per-record from column; Exa fills blank rows
                #   global text only → same signal on every record
                #   global + Exa     → global sets the default; Exa overrides per-company
                #   Exa only         → fully AI-generated per company
                #   none             → signal column left blank

                console.print(f"\n[bold]Signal[/bold]  [dim](what makes each company worth reaching out to)[/dim]")
                if data_type == "supply":
                    console.print("[dim]Example: 'Places senior sales talent in B2B SaaS companies'[/dim]")
                else:
                    console.print("[dim]Example: 'Hiring 3 sales engineers' or 'Raised Series B'[/dim]")
                console.print()

                # 1. Column picker
                sig_col_input = Prompt.ask(
                    "Signal column — number or name (Enter to skip)",
                    default=""
                )
                chosen_sig_col = _resolve_col(sig_col_input)
                if sig_col_input.strip() and not chosen_sig_col:
                    show_warning(f"Column '{sig_col_input.strip()}' not found — skipping")
                if chosen_sig_col:
                    mapping.signal = chosen_sig_col
                    show_success(f"Signal column: {chosen_sig_col}")

                # 2. Global text — only asked when no column (they're mutually exclusive)
                global_signal = ""
                if not chosen_sig_col:
                    global_signal = Prompt.ask(
                        "Global signal — same for all records (Enter to skip)",
                        default=""
                    )

                # 3. Signal prefix — applies to whatever signal source is used
                signal_prefix = ""
                if chosen_sig_col or global_signal:
                    signal_prefix = Prompt.ask(
                        "Signal prefix — prepended to every signal (Enter to skip)",
                        default=""
                    )

                # 4. Exa for signal
                use_exa_signal = False
                if has_exa:
                    if chosen_sig_col:
                        console.print("[dim]Exa fills signal for records where the column is empty[/dim]")
                    elif global_signal:
                        console.print("[dim]Exa overrides the global signal with a per-company signal[/dim]")
                    else:
                        console.print("[dim]Exa generates a signal per company[/dim]")
                    use_exa_signal = Confirm.ask(
                        "Generate signals with Exa?",
                        default=not bool(chosen_sig_col or global_signal)
                    )

                # ── Context ───────────────────────────────────────────────────
                #
                #   column only      → per-record context from data, blank rows stay blank
                #   column + Exa     → per-record from column; Exa fills blank rows
                #   Exa only         → fully AI-generated per company
                #   none             → context column left blank

                console.print(f"\n[bold]Context[/bold]  [dim](1-2 sentence company description)[/dim]")
                console.print()

                ctx_col_input = Prompt.ask(
                    "Context column — number or name (Enter to skip)",
                    default=""
                )
                chosen_col = _resolve_col(ctx_col_input)
                if ctx_col_input.strip() and not chosen_col:
                    show_warning(f"Column '{ctx_col_input.strip()}' not found — skipping")
                if chosen_col:
                    mapping.company_description = chosen_col
                    show_success(f"Context column: {chosen_col}")

                use_exa_context = False
                if has_exa:
                    if chosen_col:
                        console.print("[dim]Exa fills context for records where the column is empty[/dim]")
                    else:
                        console.print("[dim]Exa generates context for all records[/dim]")
                    use_exa_context = Confirm.ask("Generate context with Exa?", default=True)

                # ── Step 5 summary ────────────────────────────────────────────
                def _src_label(col, text, exa):
                    parts = []
                    if col:  parts.append(f"column: [cyan]{col}[/cyan]")
                    if text: parts.append(f"global: [cyan]\"{text}\"[/cyan]")
                    if exa:  parts.append("[cyan]Exa[/cyan]")
                    return "  ·  ".join(parts) if parts else "[dim]none[/dim]"

                console.print()
                console.print(Panel(
                    f"  [bold]Signal:[/bold]   {_src_label(chosen_sig_col, global_signal, use_exa_signal)}\n"
                    f"  [bold]Context:[/bold]  {_src_label(chosen_col, None, use_exa_context)}",
                    title="[bold cyan]◈ Step 5 — Sources[/bold cyan]",
                    border_style="cyan",
                    padding=(0, 1),
                ))

                # Step 6: Process records
                show_step(6 if n == 1 else f"6.{idx}", f"Processing {data_type.upper()} Records")

                processed_records = _process_records(
                    records=records,
                    mapping=mapping,
                    global_signal=global_signal or None,
                    signal_prefix=signal_prefix or None
                )

                show_success(f"Processed {len(processed_records)} records")

                # Show signal stats
                signal_processor = SignalProcessor(global_signal or None, signal_prefix or None)
                signal_stats = signal_processor.get_stats(processed_records, 'signal')
                show_info(f"Signal fill rate: {signal_stats['fill_rate']:.0f}% ({signal_stats['with_signal']}/{signal_stats['total']})")

                # Steps 7 & 8: pre-define step numbers (avoids mutation and wrong labels)
                enrich_step = 7 if n == 1 else f"7.{idx}"
                export_step = 8 if n == 1 else f"8.{idx}"

                has_exa = bool(os.getenv('EXA_API_KEY'))

                if has_exa:
                    show_step(enrich_step, "Enrichment (Optional)")

                    # 7a: Domain resolution (runs FIRST — signals and context need domain)
                    missing_domain_count = sum(
                        1 for r in processed_records
                        if not r.get('domain') and (r.get('company_name') or r.get('company'))
                    )
                    if missing_domain_count > 0:
                        use_domain_resolver = Confirm.ask(
                            f"\n[cyan]Resolve {missing_domain_count} missing domains with Exa?[/cyan]\n"
                            f"[dim]Looks up company websites from company names[/dim]",
                            default=True
                        )
                        if use_domain_resolver:
                            try:
                                from .services.exa_domain import ExaDomainResolver

                                resolver = ExaDomainResolver.from_env()
                                processed_records = resolver.resolve_batch(processed_records)

                                stats = resolver.get_stats()
                                show_success(
                                    f"Domains resolved: {stats['resolved']}, "
                                    f"Failed: {stats['failed']}"
                                )
                                if stats['cache_hits'] > 0:
                                    show_info(f"Cache hits: {stats['cache_hits']}")
                            except Exception as e:
                                show_warning(f"Domain resolution failed: {type(e).__name__}: {e}")
                                show_info("Check that your EXA_API_KEY is valid (run: signalis setup)")
                                show_info("Continuing without domain resolution...")

                    # 7b: Exa enrichment — signals + context in one pass
                    signal_count = sum(1 for r in processed_records if r.get('signal'))
                    missing_ctx_count = sum(1 for r in processed_records if not r.get('company_description'))
                    empty_signal_count = len(processed_records) - signal_count

                    needs_enrichment = (
                        (use_exa_signal and (data_type == 'supply' or empty_signal_count > 0 or signal_count > 0))
                        or (use_exa_context and missing_ctx_count > 0)
                    )

                    if needs_enrichment:
                        parts = []
                        if use_exa_signal:
                            label = f"signals ({empty_signal_count} missing)" if empty_signal_count > 0 else "signals"
                            parts.append(label)
                        if use_exa_context and missing_ctx_count > 0:
                            parts.append(f"context ({missing_ctx_count} missing)")

                        use_exa = Confirm.ask(
                            f"\n[cyan]Enrich with Exa?[/cyan]\n"
                            f"[dim]Researches each company — generates {' + '.join(parts)}[/dim]",
                            default=True
                        )

                        if use_exa:
                            overwrite_signal = False
                            if use_exa_signal and signal_count > 0:
                                overwrite_signal = Confirm.ask(
                                    f"[yellow]{signal_count} records already have signals. Overwrite?[/yellow]",
                                    default=False
                                )

                            try:
                                from .services.exa_signal import ExaSignalGenerator

                                generator = ExaSignalGenerator.from_env()
                                processed_records = generator.enrich_batch(
                                    processed_records, data_type,
                                    overwrite_signal=overwrite_signal,
                                    generate_signal=use_exa_signal,
                                    generate_context=use_exa_context,
                                )

                                stats = generator.get_stats()
                                show_success(
                                    f"Exa enrichment done! "
                                    f"Searches: {stats['exa_searches']}, "
                                    f"AI calls: {stats['ai_calls']}"
                                )
                                if stats['failed'] > 0:
                                    show_warning(f"{stats['failed']} companies could not be enriched")
                                    for err in generator.get_errors()[:5]:
                                        show_warning(f"  ↳ {err}")

                                signal_stats = signal_processor.get_stats(processed_records, 'signal')
                                show_info(f"Signal fill rate: {signal_stats['fill_rate']:.0f}% ({signal_stats['with_signal']}/{signal_stats['total']})")
                            except Exception as e:
                                show_warning(f"Exa enrichment failed: {e}")
                                show_info("Check that your EXA_API_KEY and AI provider key are valid (run: signalis setup)")
                                show_info("Continuing with export...")
                    else:
                        show_info(f"All {signal_count} records already have signals and context")

                # Step 8: Export
                show_step(export_step, f"Export {data_type.upper()}")

                # Generate timestamped filename
                exporter = CSVExporter()
                output_path = exporter.generate_filename(data_type)

                # Export (always use standard format - the 6 required fields)
                count = exporter.export_standard(processed_records, output_path)

                show_success(f"☉ Exported {count} {data_type} records")
                show_info(f"  File: [cyan]{output_path}[/cyan]")

                # Store result
                results[data_type] = {
                    'count': count,
                    'path': str(Path(output_path).resolve())
                }

            if go_back:
                continue  # restart — return to main menu

            # Final success summary
            console.print()

            if not results:
                console.print("[yellow]↶ Returned without exporting[/yellow]\n")
            elif len(results) == 1:
                data_type = list(results.keys())[0]
                result = results[data_type]
                panel = Panel(
                    f"[bold green]☉ Export Complete![/bold green]\n\n"
                    f"≡ Records exported: [white]{result['count']}[/white]\n"
                    f"▣ Output file: [cyan]{result['path']}[/cyan]\n\n"
                    f"[bold]☾ Next Steps:[/bold]\n"
                    f"  • Process more data: [cyan]signalis[/cyan]\n"
                    f"  • Import CSV into your tools\n",
                    border_style="green",
                    padding=(1, 2),
                    title="✦ Success!"
                )
                console.print(panel)
            else:
                supply = results.get('supply', {})
                demand = results.get('demand', {})

                panel = Panel(
                    f"[bold green]☉ Both Datasets Exported![/bold green]\n\n"
                    f"[bold cyan]⚗ Supply:[/bold cyan]\n"
                    f"  Records: [white]{supply.get('count', 0)}[/white]\n"
                    f"  File: [cyan]{supply.get('path', 'N/A')}[/cyan]\n\n"
                    f"[bold cyan]⟶ Demand:[/bold cyan]\n"
                    f"  Records: [white]{demand.get('count', 0)}[/white]\n"
                    f"  File: [cyan]{demand.get('path', 'N/A')}[/cyan]\n\n"
                    f"[bold]☾ Next Steps:[/bold]\n"
                    f"  • Process more data: [cyan]signalis[/cyan]\n"
                    f"  • Import CSVs into your tools\n",
                    border_style="green",
                    padding=(1, 2),
                    title="✦ Success!"
                )
                console.print(panel)

            break  # done — exit the restart loop

    except KeyboardInterrupt:
        console.print("\n\n[yellow]▲  Operation cancelled by user[/yellow]")
        raise click.Abort()
    except Exception as e:
        show_error(f"Error: {str(e)}")
        raise click.Abort()


def _interactive_apify_load():
    """Interactive Apify dataset loading."""
    console.print("\n[bold]Apify Dataset Loading[/bold]\n")

    dataset_id = Prompt.ask("Enter Apify dataset ID")

    # Optional API token
    api_token = os.getenv('APIFY_API_TOKEN')
    if not api_token:
        has_token = Confirm.ask("Do you have an API token for private datasets?", default=False)
        if has_token:
            console.print("\n[yellow]Tip: You can also set APIFY_API_TOKEN environment variable[/yellow]")
            console.print("[yellow]Paste is supported - just paste and press Enter[/yellow]\n")

            api_token = Prompt.ask("Enter API token (paste-friendly)")

            if api_token:
                api_token = api_token.strip()

    # Load dataset
    try:
        with create_progress() as progress:
            task = progress.add_task("Fetching from Apify API...", total=None)
            loader = ApifyLoader(dataset_id=dataset_id, api_token=api_token)
            records, headers = loader.load()
            progress.update(task, completed=True)

        return records, headers
    except Exception as e:
        error_msg = str(e)

        if "401" in error_msg or "Unauthorized" in error_msg:
            show_error("Authentication failed - Invalid API token")
            show_info("To fix:")
            show_info("  1. Get your API token from https://console.apify.com/account/integrations")
            show_info("  2. Set it: export APIFY_API_TOKEN='your_token_here'")
            show_info("  3. Or paste it when prompted (paste works!)")
        elif "404" in error_msg or "Not Found" in error_msg:
            show_error(f"Dataset not found: {dataset_id}")
            show_info("Check the dataset ID at https://console.apify.com/storage/datasets")
        else:
            show_error(f"Failed to load Apify dataset: {error_msg}")

        raise


def _interactive_csv_load():
    """Interactive CSV file loading."""
    console.print("\n[bold]CSV File Loading[/bold]\n")

    while True:
        file_path = Prompt.ask("Enter CSV file path")

        # Expand user path
        file_path = os.path.expanduser(file_path)

        if not Path(file_path).exists():
            show_error(f"File not found: {file_path}")
            if not Confirm.ask("Try again?", default=True):
                raise click.Abort()
            continue

        try:
            with create_progress() as progress:
                task = progress.add_task("Loading CSV file...", total=None)
                loader = CSVLoader(file_path)
                records, headers = loader.load()
                progress.update(task, completed=True)

            # Show file info
            info = loader.get_info()
            show_info(f"File size: {info['file_size'] / 1024:.1f} KB")
            show_info(f"Delimiter: '{info['delimiter']}'")
            show_info(f"Encoding: {info['encoding']}")

            return records, headers

        except Exception as e:
            show_error(f"Failed to load CSV: {str(e)}")
            if not Confirm.ask("Try another file?", default=True):
                raise click.Abort()


def _process_records(records, mapping, global_signal=None, signal_prefix=None):
    """Process records with field mapping and normalization."""
    processed_records = []
    signal_processor = SignalProcessor(
        global_signal=global_signal,
        signal_prefix=signal_prefix
    )

    with create_progress() as progress:
        task = progress.add_task("Normalizing data...", total=len(records))

        for record in records:
            processed = {}

            # Full name
            full_name_field = mapping.full_name
            if full_name_field:
                full_name = normalize_field(record.get(full_name_field, ''), 'name')
                processed['full_name'] = full_name

                first, last = split_name(full_name)
                processed['first_name'] = first
                processed['last_name'] = last

            # Company
            company_field = mapping.company_name
            if company_field:
                processed['company'] = normalize_field(record.get(company_field, ''), 'text')
                processed['company_name'] = processed['company']

            # Domain
            domain_field = mapping.domain
            if domain_field:
                raw_domain = record.get(domain_field, '')
                processed['domain'] = normalize_domain(raw_domain)

            # Email
            email_field = mapping.email
            if email_field:
                processed['email'] = normalize_field(record.get(email_field, ''), 'email')

            # Company description (maps to Context)
            desc_field = mapping.company_description
            if desc_field:
                processed['company_description'] = normalize_field(record.get(desc_field, ''), 'text')

            # Signal (with global signal + prefix support)
            signal_field = mapping.signal
            row_signal = record.get(signal_field, '') if signal_field else ''
            processed['signal'] = signal_processor.process(row_signal)

            # Preserve raw record for enrichment steps (domain resolution, etc.)
            processed['_raw'] = record

            processed_records.append(processed)
            progress.update(task, advance=1)

    return processed_records


@cli.command()
def version():
    """Show version information"""
    click.echo(f"Signalis Framework v{__version__}")
    click.echo("Transform raw data into outreach-ready CSVs")


@cli.command()
def config():
    """Show current configuration status"""
    from core.config import get_config

    cfg = get_config()
    status = cfg.get_config_status()

    console.print("\n[bold cyan]⚗ Signalis Framework Configuration[/bold cyan]\n")

    from rich.table import Table
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Feature", style="dim")
    table.add_column("Status")

    table.add_row(
        "Apify (Data Loading)",
        "[green]☉ Configured[/green]" if status['shaper']['apify'] else "[red]☿ Not configured[/red]"
    )
    table.add_row(
        "Exa (Signals + Domains)",
        "[green]☉ Configured[/green]" if status['shaper']['exa_signals'] else "[red]☿ Not configured[/red]"
    )
    table.add_row(
        "AI Provider (Signal Synthesis)",
        "[green]☉ Configured[/green]" if status['shaper']['ai_provider'] else "[red]☿ Not configured[/red]"
    )
    console.print(table)

    console.print(f"\n[dim]Output directory: {cfg.output_dir}[/dim]")
    console.print(f"[dim]Config file: {cfg.root_dir / '.env'}[/dim]\n")


def _do_setup():
    """Shared setup logic — prompts for API keys and writes to .env."""
    from pathlib import Path

    root = Path(__file__).parent.parent
    env_path = root / '.env'
    example_path = root / '.env.example'

    existing: dict = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, _, v = line.partition('=')
                existing[k.strip()] = v.strip()

    def _masked(val: str) -> str:
        if not val:
            return "[red]Not set[/red]"
        if len(val) <= 8:
            return "[yellow]•••[/yellow]"
        return f"[yellow]{val[:4]}···{val[-3:]}[/yellow]"

    def _prompt_key(key: str, label: str, hint: str = '') -> str:
        current = existing.get(key, '')
        console.print(f"\n  [bold]{label}[/bold]  {_masked(current)}")
        if hint:
            console.print(f"  [dim]{hint}[/dim]")
        if current:
            new_val = Prompt.ask("  New value (Enter to keep)", default='')
            return new_val.strip() if new_val.strip() else current
        else:
            val = Prompt.ask("  Value (Enter to skip)", default='')
            return val.strip()

    console.print("\n[bold cyan]⚗ Settings — API Keys[/bold cyan]")
    console.print("[dim]Paste-friendly. Press Enter to keep an existing key.[/dim]")

    updates: dict = dict(existing)

    console.print("\n[bold]Data Loading[/bold]")
    val = _prompt_key(
        'APIFY_API_TOKEN', 'Apify API Token',
        'Only needed for private Apify datasets  ·  apify.com/account/integrations'
    )
    if val:
        updates['APIFY_API_TOKEN'] = val
    elif 'APIFY_API_TOKEN' in updates:
        updates['APIFY_API_TOKEN'] = ''

    console.print("\n[bold]Exa (Signals + Domains + Context)[/bold]")
    val = _prompt_key(
        'EXA_API_KEY', 'Exa API Key',
        'Powers domain resolution, signals, and context  ·  dashboard.exa.ai/api-keys'
    )
    if val:
        updates['EXA_API_KEY'] = val
    elif 'EXA_API_KEY' in updates:
        updates['EXA_API_KEY'] = ''

    console.print("\n[bold]AI Provider (Signal Synthesis)[/bold]")
    current_provider = existing.get('AI_PROVIDER', 'openai')
    console.print(f"\n  [bold]Provider[/bold]  [yellow]{current_provider}[/yellow]")
    provider = Prompt.ask(
        "  Choose provider",
        choices=['openai', 'anthropic'],
        default=current_provider,
    )
    updates['AI_PROVIDER'] = provider

    if provider == 'openai':
        val = _prompt_key(
            'OPENAI_API_KEY', 'OpenAI API Key',
            'platform.openai.com/api-keys'
        )
        if val:
            updates['OPENAI_API_KEY'] = val
    else:
        val = _prompt_key(
            'ANTHROPIC_API_KEY', 'Anthropic API Key',
            'console.anthropic.com/settings/keys'
        )
        if val:
            updates['ANTHROPIC_API_KEY'] = val

    # ── Connector keys (optional section) ─────────────────────────────────────
    console.print("\n[bold]Connector — Email Enrichment & Sending[/bold]")
    console.print("[dim]Optional. Needed for matching + enrichment + intro generation.[/dim]")

    setup_connector = Confirm.ask("\n  Configure Connector keys?", default=False)
    if setup_connector:
        val = _prompt_key(
            'APOLLO_API_KEY', 'Apollo API Key',
            'Contact enrichment (finds missing emails)  ·  app.apollo.io/settings/integrations/api'
        )
        if val:
            updates['APOLLO_API_KEY'] = val

        val = _prompt_key(
            'ANYMAIL_API_KEY', 'Anymail Finder API Key',
            'Email fallback enrichment  ·  anymailfinder.com/account'
        )
        if val:
            updates['ANYMAIL_API_KEY'] = val

        val = _prompt_key(
            'SSM_API_KEY', 'SSM API Key',
            'Sales System Mastery enrichment (members only)  ·  skool.com/ssmasters'
        )
        if val:
            updates['SSM_API_KEY'] = val

        console.print("\n  [bold]Email Sending[/bold]  [dim](optional — skip if not sending campaigns)[/dim]")
        sending_provider = Prompt.ask(
            "  Sending platform",
            choices=['instantly', 'plusvibe', 'skip'],
            default='skip',
        )
        if sending_provider == 'instantly':
            val = _prompt_key(
                'INSTANTLY_API_KEY', 'Instantly.ai API Key',
                'app.instantly.ai → Settings → Integrations'
            )
            if val:
                updates['INSTANTLY_API_KEY'] = val
                updates['SENDING_PROVIDER'] = 'instantly'

            val = _prompt_key('DEMAND_CAMPAIGN_ID', 'Demand Campaign ID', 'Campaign ID from Instantly dashboard')
            if val:
                updates['DEMAND_CAMPAIGN_ID'] = val

            val = _prompt_key('SUPPLY_CAMPAIGN_ID', 'Supply Campaign ID', 'Campaign ID from Instantly dashboard')
            if val:
                updates['SUPPLY_CAMPAIGN_ID'] = val

        elif sending_provider == 'plusvibe':
            val = _prompt_key(
                'PLUSVIBE_API_KEY', 'PlusVibe API Key',
                'app.plusvibe.io → Settings'
            )
            if val:
                updates['PLUSVIBE_API_KEY'] = val
                updates['SENDING_PROVIDER'] = 'plusvibe'

            val = _prompt_key('PLUSVIBE_WORKSPACE_ID', 'PlusVibe Workspace ID', '')
            if val:
                updates['PLUSVIBE_WORKSPACE_ID'] = val

            val = _prompt_key('DEMAND_CAMPAIGN_ID', 'Demand Campaign ID', '')
            if val:
                updates['DEMAND_CAMPAIGN_ID'] = val

            val = _prompt_key('SUPPLY_CAMPAIGN_ID', 'Supply Campaign ID', '')
            if val:
                updates['SUPPLY_CAMPAIGN_ID'] = val

    if example_path.exists():
        template_lines = example_path.read_text().splitlines()
        output_lines = []
        written: set = set()
        for line in template_lines:
            stripped = line.strip()
            if stripped and not stripped.startswith('#') and '=' in stripped:
                k = stripped.split('=', 1)[0].strip()
                output_lines.append(f"{k}={updates.get(k, '')}")
                written.add(k)
            else:
                output_lines.append(line)
        for k, v in updates.items():
            if k not in written and v:
                output_lines.append(f"{k}={v}")
    else:
        output_lines = [f"{k}={v}" for k, v in updates.items() if v]

    env_path.write_text('\n'.join(output_lines) + '\n')

    # Reload env so rest of session picks up new keys
    load_dotenv(env_path, override=True)

    show_success(f"Saved → {env_path}\n")


@cli.command()
def setup():
    """Configure API keys — writes values to .env"""
    _do_setup()


@cli.command()
def update():
    """Pull the latest version from GitHub and reinstall dependencies."""
    import subprocess
    import sys

    root = Path(__file__).parent.parent

    console.print("\n[bold cyan]⟶ Updating Signalis...[/bold cyan]\n")

    # Verify this is a git repo
    if not (root / '.git').exists():
        show_error("Cannot update — installation is not a git repository.")
        show_info("Re-install from: https://github.com/ChatsuboDigital/signalis-framework.git")
        return

    # git pull
    show_info("Pulling latest changes from GitHub...")
    try:
        result = subprocess.run(
            ['git', 'pull'],
            cwd=root,
            capture_output=True,
            text=True
        )
    except FileNotFoundError:
        show_error("git not found — please install Git and ensure it is on your PATH.")
        show_info("  macOS:   brew install git")
        show_info("  Linux:   sudo apt install git")
        show_info("  Windows: https://git-scm.com/download/win")
        return

    if result.returncode != 0:
        show_error("Update failed:")
        console.print(f"[dim]{result.stderr.strip()}[/dim]")
        show_info("Check your internet connection, or re-clone the repo.")
        return

    output = result.stdout.strip()

    if 'Already up to date' in output:
        show_success("Already on the latest version.")
        return

    console.print(f"[dim]{output}[/dim]\n")

    # Reinstall using the same Python that is running this command —
    # works correctly on macOS, Linux, and Windows regardless of venv path
    show_info("Installing new dependencies...")
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '-e', '.[all]', '--quiet'],
            cwd=root,
            capture_output=True,
            text=True
        )
    except FileNotFoundError:
        show_warning("pip not found — run the installer again to update dependencies.")
        show_success("Signalis code updated successfully.")
        return

    if result.returncode != 0:
        show_warning("Dependency install had issues:")
        console.print(f"[dim]{result.stderr.strip()}[/dim]")
        show_info("Try running the installer again: install.sh / install.bat")
    else:
        show_success("Signalis updated successfully.")

    console.print("[dim]Run [cyan]signalis[/cyan] to start.[/dim]\n")


def main():
    """Main entry point"""
    try:
        cli()
    except KeyboardInterrupt:
        console.print("\n\n[yellow]▲  Operation cancelled by user[/yellow]")
        import sys
        sys.exit(0)
    except click.Abort:
        import sys
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[red]☿ Unexpected error: {e}[/red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        import sys
        sys.exit(1)


if __name__ == '__main__':
    main()
