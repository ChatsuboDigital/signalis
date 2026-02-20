"""
Connector — Matching, Enrichment & AI Intros

Accessed via 'signalis connector' from the main CLI.
"""

import warnings
# Suppress urllib3 OpenSSL warning for clean UI
warnings.filterwarnings('ignore', module='urllib3')

import os
import sys
import time
import uuid
from pathlib import Path
import click
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from core import __version__
from .config import ConnectorConfig
from .csv_normalizer import load_and_normalize_csv
from .matcher import match_records
from .enrichment import enrich_batch, EnrichmentConfig
from .intro_generator import generate_intros_ai, IntroAIConfig
from .senders import (
    resolve_sender, build_sender_config, get_limiter,
    SendLeadParams, SenderId
)
from .models import DemandRecord, SupplyRecord, Edge, NormalizedRecord
from .banner import (
    show_banner, show_welcome, show_step, show_success,
    show_error, show_warning, show_info, show_results_summary, console
)
from .interactive import (
    run_interactive_setup, check_first_run, show_quick_tips
)


@click.group(invoke_without_command=True)
@click.pass_context
@click.version_option(version=__version__)
def cli(ctx):
    """
    ⚯ Connector — CSV Matching, Enrichment & AI Intros

    Run 'signalis connector' for interactive mode,
    or use 'signalis connector run' with options for direct execution.
    """
    # Simple header (no ASCII art - only main Signalis has that)
    # If no subcommand, run interactive mode
    if ctx.invoked_subcommand is None:
        console.print("\n[bold cyan]⚯ Connector[/bold cyan]")
        console.print("[dim]Match supply to demand and automate campaign delivery[/dim]\n")

        # Show home menu
        console.print("[bold cyan]What would you like to do?[/bold cyan]\n")
        console.print("  [cyan]1[/cyan]   Start Matching      [dim](Match supply to demand based on signals)[/dim]")
        console.print("  [cyan]2[/cyan]   View Quick Tips     [dim](Learn how Connector works)[/dim]")
        console.print("  [cyan]0[/cyan]   Exit                [dim](Return to main menu)[/dim]\n")

        from rich.prompt import Prompt
        choice = Prompt.ask("Select option", choices=["0", "1", "2"], default="1")

        if choice == "0":
            console.print("\n[yellow]⊗ Exiting Connector...[/yellow]\n")
            return

        if choice == "2":
            show_quick_tips()
            console.print("\n[dim]Press Enter to continue...[/dim]")
            input()
            console.clear()
            console.print("\n[bold cyan]⚯ Connector[/bold cyan]")
            console.print("[dim]Match supply to demand and automate campaign delivery[/dim]\n")

        # Check first run
        if not check_first_run():
            console.print("\n[dim]Press Enter to return to menu...[/dim]")
            input()
            return

        # Run interactive setup
        config = run_interactive_setup()
        if not config:
            console.print("\n[yellow]▲  Setup cancelled[/yellow]")
            console.print("[dim]Press Enter to return to menu...[/dim]")
            input()
            return

        # Run the flow with interactive config
        ctx.invoke(
            run,
            demand=config['demand'],
            supply=config['supply'],
            output_dir=config['output_dir'],
            min_score=config['min_score'],
            enrich=config['enrich'],
            ai_intros=config['ai_intros'],
            send_emails=config.get('enable_sending', False),
            format=config['format'],
            ai_model=config.get('ai_model'),
            interactive=True
        )


def safe_extract_first_name(first_name: str, full_name: str) -> str:
    """Safely extract first name, handling edge cases"""
    if first_name and first_name.strip():
        return first_name.strip()

    if full_name and full_name.strip():
        parts = full_name.strip().split()
        return parts[0] if parts else 'Contact'

    return 'Contact'


def safe_extract_last_name(last_name: str, full_name: str) -> str:
    """Safely extract last name, handling edge cases"""
    if last_name and last_name.strip():
        return last_name.strip()

    if full_name and full_name.strip():
        parts = full_name.strip().split()
        return ' '.join(parts[1:]) if len(parts) > 1 else ''

    return ''


def normalized_to_demand_record(record: NormalizedRecord) -> DemandRecord:
    """Convert NormalizedRecord to DemandRecord for matching"""
    return DemandRecord(
        domain=record.domain,
        company=record.company,
        contact=record.full_name,
        email=record.email or '',
        title=record.title or '',
        industry=record.industry or '',
        signals=[],
        metadata={
            'companyDescription': record.company_description,
            'description': record.company_description,
        }
    )


def normalized_to_supply_record(record: NormalizedRecord) -> SupplyRecord:
    """Convert NormalizedRecord to SupplyRecord for matching"""
    return SupplyRecord(
        domain=record.domain,
        company=record.company,
        contact=record.full_name,
        email=record.email or '',
        title=record.title or '',
        industry=record.industry or '',
        capability=record.signal,
        metadata={
            'companyDescription': record.company_description,
            'description': record.company_description,
        }
    )


@cli.command()
@click.option('--demand', '-d', help='Path to demand CSV file', type=click.Path(exists=True))
@click.option('--supply', '-s', help='Path to supply CSV file', type=click.Path(exists=True))
@click.option('--output-dir', '-o', default='./output', help='Output directory', type=click.Path())
@click.option('--min-score', default=30, help='Minimum match score (0-100)', type=float)
@click.option('--best-match-only', is_flag=True, default=False, help='Return only best match per demand (default: all matches)')
@click.option('--enrich/--no-enrich', default=True, help='Enable email enrichment')
@click.option('--ai-intros/--no-ai-intros', default=True, help='Enable AI intro generation')
@click.option('--generate-intros-for',
              type=click.Choice(['all', 'best', 'none']),
              default='best',
              help='Which matches to generate intros for: all (costly), best (recommended), none (skip)')
@click.option('--send-emails/--no-send-emails', default=False, help='Send emails to campaign platform')
@click.option('--format', type=click.Choice(['csv', 'json', 'both']), default='csv', help='Output format')
@click.option('--ai-model', help='AI model to use (e.g., gpt-4o-mini, claude-3-haiku)')
@click.option('--interactive', is_flag=True, hidden=True)
def run(demand, supply, output_dir, min_score, best_match_only, enrich, ai_intros, generate_intros_for, send_emails, format, ai_model, interactive):
    """
    Run the complete flow: match, enrich, and generate AI intros

    Example:
        signalis connector run --demand demand.csv --supply supply.csv
    """
    # If not interactive and missing required args, show error
    if not interactive and (not demand or not supply):
        show_error("Missing required arguments: --demand and --supply")
        console.print("\n[dim]Run 'signalis connector' (no arguments) for interactive mode[/dim]")
        console.print("[dim]Or use: signalis connector run --demand FILE --supply FILE[/dim]\n")
        raise click.Abort()

    # Load configuration
    config = ConnectorConfig.from_env()
    config.min_match_score = min_score
    config.enable_enrichment = enrich
    config.enable_ai_intros = ai_intros
    config.enable_sending = send_emails
    config.output_format = format
    config.output_dir = output_dir
    if ai_model:
        config.ai_model = ai_model

    # Validate config
    try:
        config.validate()
    except ValueError as e:
        show_error(f"Configuration error: {e}")
        raise click.Abort()

    # Email sending requires AI intros to be enabled
    if config.enable_sending and not config.enable_ai_intros:
        show_error("Email sending requires AI intro generation to be enabled")
        show_info("Enable AI intros with --ai-intros flag or in interactive mode")
        raise click.Abort()

    # Create output directory
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Generate upload ID
    upload_id = str(uuid.uuid4())[:8]

    # =========================================================================
    # STEP 1: Load and Normalize CSVs
    # =========================================================================
    if not interactive:
        console.print()
    show_step(1, "Loading CSV Files", "Reading and normalizing your data...")

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Loading demand CSV...", total=None)
            demand_records, demand_keys = load_and_normalize_csv(demand, 'demand', upload_id)
            progress.update(task, completed=True)

            task = progress.add_task("Loading supply CSV...", total=None)
            supply_records, supply_keys = load_and_normalize_csv(supply, 'supply', upload_id)
            progress.update(task, completed=True)

        show_success(f"Loaded {len(demand_records)} demand records")
        show_success(f"Loaded {len(supply_records)} supply records")
    except Exception as e:
        show_error(f"Error loading CSVs: {e}")
        raise click.Abort()

    # =========================================================================
    # STEP 2: Matching
    # =========================================================================
    console.print()
    show_step(2, "Matching", "Finding connections between demand and supply...")

    start_time = time.time()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    ) as progress:
        task = progress.add_task(
            f"Scoring {len(demand_records)} × {len(supply_records)} pairs...",
            total=len(demand_records)
        )

        def _on_match_progress(curr, total):
            progress.update(task, completed=curr)

        result = match_records(
            demand_records,
            supply_records,
            min_score=int(min_score),
            best_match_only=best_match_only,
            on_progress=_on_match_progress,
        )

    elapsed = time.time() - start_time

    # Enhanced reporting showing total matches vs unique demands
    unique_demands = result.stats.get('unique_demands_matched', 0)
    total_matches = len(result.demand_matches)
    avg_per_demand = total_matches / unique_demands if unique_demands > 0 else 0

    show_success(f"Found {total_matches} total matches in {elapsed:.1f}s")
    if not best_match_only and unique_demands > 0:
        show_info(f"  • {unique_demands} demands matched")
        show_info(f"  • {avg_per_demand:.1f} avg matches per demand")
    show_info(f"  • Average match score: {result.stats['avg_score']}/100")

    if len(result.demand_matches) == 0:
        show_warning("No matches found. Try lowering --min-score")
        # Return early - no matches to process
        return

    # =========================================================================
    # STEP 3: Enrichment (Optional)
    # =========================================================================
    if config.enable_enrichment:
        console.print()
        show_step(3, "Email Enrichment", "Finding missing contact emails...")

        enrichment_config = EnrichmentConfig(
            apollo_api_key=config.apollo_api_key,
            anymail_api_key=config.anymail_api_key,
            ssm_api_key=config.ssm_api_key,
        )

        # Collect all unique records that need enrichment
        records_to_enrich = []
        for match in result.demand_matches:
            if not match.demand.email:
                records_to_enrich.append(match.demand)
            if not match.supply.email:
                records_to_enrich.append(match.supply)

        if records_to_enrich:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console
            ) as progress:
                task = progress.add_task("Enriching contacts...", total=len(records_to_enrich))

                def update_progress(curr, total):
                    progress.update(task, completed=curr)

                enrichment_results = enrich_batch(
                    records_to_enrich,
                    enrichment_config,
                    on_progress=update_progress
                )

            # Count results by source
            enriched_count = sum(
                1 for r in enrichment_results.values()
                if r.outcome == 'ENRICHED'
            )
            cached_count = sum(
                1 for r in enrichment_results.values()
                if r.inputs_present.get('cached', False)
            )
            api_count = enriched_count - cached_count

            show_success(f"Enriched {enriched_count}/{len(records_to_enrich)} records")
            if cached_count > 0:
                show_info(f"⊡ {cached_count} from cache (saved {cached_count} API calls!)")
            if api_count > 0:
                show_info(f"⊛ {api_count} new API calls")
        else:
            show_info("All records already have emails - skipping enrichment")

    # =========================================================================
    # STEP 4: AI Intro Generation (Optional)
    # =========================================================================
    if config.enable_ai_intros and generate_intros_for != 'none':
        console.print()
        show_step(4, "AI Intro Generation", "Creating personalized email introductions...")

        if not config.ai_api_key:
            show_warning("Skipping AI intros - no API key configured")
        else:
            # Filter matches based on intro scope
            if generate_intros_for == 'best':
                # Get best match per demand for intro generation
                from connector.matcher import get_best_match_per_demand
                intro_matches = get_best_match_per_demand(result.demand_matches)
                scope_msg = f"{len(intro_matches)} matches (best match per demand)"
            elif generate_intros_for == 'all':
                intro_matches = result.demand_matches
                scope_msg = f"{len(intro_matches)} matches (all above threshold)"
            else:  # Should not reach here due to flag validation
                intro_matches = []
                scope_msg = "0 matches"

            show_info(f"Generating intros for {scope_msg}")

            # Filter out matches with missing emails (saves API calls)
            valid_for_intro = [
                match for match in intro_matches
                if match.demand.email and match.supply.email
            ]

            skipped_no_email = len(intro_matches) - len(valid_for_intro)
            if skipped_no_email > 0:
                show_warning(f"Skipped {skipped_no_email} matches (missing emails)")

            ai_config = IntroAIConfig(
                provider=config.ai_provider,
                api_key=config.ai_api_key,
                model=config.ai_model,
                azure_endpoint=config.azure_endpoint,
                azure_deployment=config.azure_deployment,
                openai_api_key_fallback=config.openai_fallback_key,
            )

            intros_generated = 0
            intros_failed = 0
            intros_fallback = 0

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console
            ) as progress:
                task = progress.add_task("Generating intros...", total=len(valid_for_intro))

                for i, match in enumerate(valid_for_intro):
                    try:
                        demand_rec = normalized_to_demand_record(match.demand)
                        supply_rec = normalized_to_supply_record(match.supply)
                        edge = Edge(
                            evidence=match.tier_reason,
                            confidence=match.score / 100,
                            signals=match.reasons
                        )

                        intros = generate_intros_ai(ai_config, demand_rec, supply_rec, edge)

                        # Check if fallback was used
                        if hasattr(intros, 'source') and intros.source == 'fallback':
                            intros_fallback += 1

                        # Store intros in match metadata
                        match.demand.raw['generated_intro'] = intros.demand_intro
                        match.supply.raw['generated_intro'] = intros.supply_intro

                        intros_generated += 1
                    except Exception as e:
                        intros_failed += 1
                        # Store empty intro on complete failure
                        match.demand.raw['generated_intro'] = ''
                        match.supply.raw['generated_intro'] = ''

                    progress.update(task, completed=i + 1)

            show_success(f"Generated {intros_generated} intro pairs")
            if intros_fallback > 0:
                show_warning(f"{intros_fallback} intros used fallback templates")
            if intros_failed > 0:
                show_warning(f"Failed to generate {intros_failed} intros")
    elif config.enable_ai_intros and generate_intros_for == 'none':
        console.print()
        show_info("Skipping intro generation (--generate-intros-for none)")

    # =========================================================================
    # STEP 5: Send Emails (Optional)
    # =========================================================================
    if config.enable_sending:
        console.print()
        show_step(5, "Sending Emails", "Routing intros to campaign platform...")

        # Resolve sender
        sender_id = config.sending_provider
        sender = resolve_sender(sender_id)

        # Build config
        sender_config = build_sender_config(
            sending_provider=sender_id,
            instantly_api_key=config.instantly_api_key,
            plusvibe_api_key=config.plusvibe_api_key,
            plusvibe_workspace_id=config.plusvibe_workspace_id,
            demand_campaign_id=config.demand_campaign_id,
            supply_campaign_id=config.supply_campaign_id,
        )

        # Validate config
        config_error = sender.validate_config(sender_config)
        if config_error:
            show_error(f"Sender configuration error: {config_error}")
            show_warning("Skipping email sending - check your .env settings")
        else:
            # Build send queue
            send_queue = []
            skipped_no_campaign = {'demand': 0, 'supply': 0}
            skipped_no_intro = {'demand': 0, 'supply': 0}

            for match in result.demand_matches:
                # Send to demand contact (they get the supply intro)
                if match.demand.email:
                    if sender_config.demand_campaign_id:
                        intro_text = match.demand.raw.get('generated_intro', '')
                        if intro_text:
                            send_queue.append({
                                'type': 'DEMAND',
                                'campaign_id': sender_config.demand_campaign_id,
                                'email': match.demand.email,
                                'first_name': safe_extract_first_name(match.demand.first_name, match.demand.full_name),
                                'last_name': safe_extract_last_name(match.demand.last_name, match.demand.full_name),
                                'company_name': match.demand.company,
                                'company_domain': match.demand.domain,
                                'intro_text': intro_text,
                                'contact_title': match.demand.title,
                                'signal_metadata': match.demand.raw.get('signal_metadata'),
                            })
                        else:
                            skipped_no_intro['demand'] += 1
                    else:
                        skipped_no_campaign['demand'] += 1

                # Send to supply contact (they get the demand intro)
                if match.supply.email:
                    if sender_config.supply_campaign_id:
                        intro_text = match.supply.raw.get('generated_intro', '')
                        if intro_text:
                            send_queue.append({
                                'type': 'SUPPLY',
                                'campaign_id': sender_config.supply_campaign_id,
                                'email': match.supply.email,
                                'first_name': safe_extract_first_name(match.supply.first_name, match.supply.full_name),
                                'last_name': safe_extract_last_name(match.supply.last_name, match.supply.full_name),
                                'company_name': match.supply.company,
                                'company_domain': match.supply.domain,
                                'intro_text': intro_text,
                                'contact_title': match.supply.title,
                                'signal_metadata': match.supply.raw.get('signal_metadata'),
                            })
                        else:
                            skipped_no_intro['supply'] += 1
                    else:
                        skipped_no_campaign['supply'] += 1

            # Show what's in the send queue
            console.print(f"\n[cyan]⟶ Send queue: {len(send_queue)} emails prepared[/cyan]")
            if skipped_no_campaign['demand'] > 0:
                show_warning(f"Skipped {skipped_no_campaign['demand']} demand contacts (no DEMAND_CAMPAIGN_ID configured)")
            if skipped_no_campaign['supply'] > 0:
                show_warning(f"Skipped {skipped_no_campaign['supply']} supply contacts (no SUPPLY_CAMPAIGN_ID configured)")
            if skipped_no_intro['demand'] > 0 or skipped_no_intro['supply'] > 0:
                total_no_intro = skipped_no_intro['demand'] + skipped_no_intro['supply']
                show_warning(f"Skipped {total_no_intro} contacts (no intro generated)")

            if not send_queue:
                show_warning("No emails to send - check campaign IDs and intro generation")
            else:
                # Get rate limiter
                limiter = get_limiter(sender_id)

                # Track results
                send_results = {'new': 0, 'existing': 0, 'needs_attention': 0, 'failed': 0}
                error_details = []  # Track error details for debugging

                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    console=console
                ) as progress:
                    task = progress.add_task(f"Sending to {sender.name}...", total=len(send_queue))

                    for i, item in enumerate(send_queue):
                        try:
                            # Rate limit
                            limiter.wait_for_token()

                            # Send
                            params = SendLeadParams(**item)
                            result_obj = sender.send_lead(sender_config, params)

                            # Track result
                            if result_obj.success:
                                send_results[result_obj.status] += 1
                                # Collect error details for needs_attention cases
                                if result_obj.status == 'needs_attention' and result_obj.detail and len(error_details) < 3:
                                    error_details.append(result_obj.detail)
                            else:
                                send_results['failed'] += 1
                                if result_obj.detail and len(error_details) < 3:
                                    error_details.append(result_obj.detail)

                        except Exception as e:
                            send_results['failed'] += 1
                            if len(error_details) < 3:
                                error_details.append(str(e))
                        finally:
                            limiter.release()
                            progress.update(task, completed=i + 1)

                # Show clean summary
                console.print()
                console.print("[bold cyan]⟶ Sending Summary:[/bold cyan]")
                console.print(f"  Total processed: [white]{len(send_queue)}[/white] leads")

                if send_results['new'] > 0:
                    console.print(f"  ☉ [green]{send_results['new']} new[/green] leads added to campaigns")

                if send_results['existing'] > 0:
                    console.print(f"  ◈ [blue]{send_results['existing']} skipped[/blue] (already in workspace)")
                    console.print(f"    [dim]These contacts were previously uploaded to Plusvibe[/dim]")

                if send_results['needs_attention'] > 0:
                    console.print(f"  ▲ [yellow]{send_results['needs_attention']} need attention[/yellow]")
                    if error_details:
                        console.print("    [dim]Reasons:[/dim]")
                        for detail in error_details[:3]:
                            console.print(f"      • {detail}")

                if send_results['failed'] > 0:
                    console.print(f"  ☿ [red]{send_results['failed']} failed[/red]")
                    if error_details:
                        console.print("    [dim]Errors:[/dim]")
                        for detail in error_details[:3]:
                            console.print(f"      • {detail}")

                # Show campaign info
                console.print()
                if sender_config.demand_campaign_id:
                    console.print(f"  [dim]Demand campaign: {sender_config.demand_campaign_id}[/dim]")
                if sender_config.supply_campaign_id:
                    console.print(f"  [dim]Supply campaign: {sender_config.supply_campaign_id}[/dim]")
                console.print()

    # =========================================================================
    # STEP 6: Export Results
    # =========================================================================
    console.print()
    show_step(6, "Exporting Results", "Saving your matched data...")

    export_results(result, config)

    show_success(f"Results saved to {output_dir}/")

    # Show summary
    show_results_summary(result.stats)

    # If interactive mode, show next steps and wait
    if interactive:
        console.print()
        console.print("[bold]☾ Next Steps:[/bold]")
        console.print(f"  • Review matches in [cyan]{output_dir}/demand_matches.csv[/cyan]")
        console.print(f"  • Check supplier aggregates in [cyan]{output_dir}/supply_aggregates.csv[/cyan]")
        console.print("  • Run more matches: [cyan]signalis connector[/cyan]")
        console.print("  • Process new data: [cyan]signalis[/cyan]\n")
        console.print("[dim]Press Enter to return to Signalis menu...[/dim]")
        input()


def export_results(result, config):
    """Export matching results to files"""
    import pandas as pd
    import json

    output_dir = Path(config.output_dir)

    # Export demand matches
    if config.output_format in ['csv', 'both']:
        demand_data = []
        for match in result.demand_matches:
            demand_data.append({
                'company': match.demand.company,
                'contact_name': match.demand.full_name,
                'email': match.demand.email,
                'title': match.demand.title,
                'domain': match.demand.domain,
                'signal': match.demand.signal,
                'matched_supplier': match.supply.company,
                'supplier_contact': match.supply.full_name,
                'supplier_email': match.supply.email,
                'match_score': match.score,
                'match_tier': match.tier,
                'match_reason': match.tier_reason,
                'generated_intro': match.demand.raw.get('generated_intro', ''),
            })

        df_demand = pd.DataFrame(demand_data)
        df_demand.to_csv(output_dir / 'demand_matches.csv', index=False)
        show_info("Saved demand_matches.csv")

        # Export supply aggregates
        supply_data = []
        for agg in result.supply_aggregates:
            supply_data.append({
                'company': agg['supply'].company,
                'contact_name': agg['supply'].full_name,
                'email': agg['supply'].email,
                'title': agg['supply'].title,
                'domain': agg['supply'].domain,
                'capability': agg['supply'].signal,
                'total_matches': agg['total_matches'],
                'best_match_company': agg['best_match'].demand.company,
                'best_match_score': agg['best_match'].score,
                'generated_intro': agg['supply'].raw.get('generated_intro', ''),
            })

        df_supply = pd.DataFrame(supply_data)
        df_supply.to_csv(output_dir / 'supply_aggregates.csv', index=False)
        show_info("Saved supply_aggregates.csv")

    if config.output_format in ['json', 'both']:
        # Export as JSON (simplified)
        json_output = {
            'stats': result.stats,
            'demand_matches_count': len(result.demand_matches),
            'supply_aggregates_count': len(result.supply_aggregates),
        }

        with open(output_dir / 'results.json', 'w') as f:
            json.dump(json_output, f, indent=2)
        show_info("Saved results.json")


@cli.command()
def setup():
    """Interactive setup wizard - configure API keys and settings"""
    console.print("[bold cyan]Setup Wizard[/bold cyan]\n")

    check_first_run()
    show_quick_tips()


@cli.command()
def cache():
    """View enrichment cache statistics"""
    from .enrichment_cache import get_cache_stats
    from rich.table import Table

    console.print("[bold cyan]Enrichment Cache Statistics[/bold cyan]\n")

    stats = get_cache_stats()

    # Create stats table
    table = Table(show_header=False, box=None)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("Total Entries", str(stats['total']))
    table.add_row("Fresh (< 90 days)", f"[green]{stats['fresh']}[/green]")
    table.add_row("Stale (> 90 days)", f"[yellow]{stats['stale']}[/yellow]")
    table.add_row("Cache File", stats['cache_file'])

    console.print(table)
    console.print()

    if stats['by_source']:
        console.print("[bold cyan]By Source:[/bold cyan]")
        source_table = Table(show_header=True)
        source_table.add_column("Provider", style="cyan")
        source_table.add_column("Count", style="white")

        for source, count in stats['by_source'].items():
            source_table.add_row(source, str(count))

        console.print(source_table)
        console.print()

    console.print("[dim]Cache stores enriched emails for 90 days to reduce API costs[/dim]")
    console.print("[dim]Run 'signalis connector cache-clear' to clear the cache[/dim]\n")


@cli.command()
def cache_clear():
    """Clear the enrichment cache"""
    from .enrichment_cache import clear_cache
    from rich.prompt import Confirm

    console.print("[yellow]▲ This will clear all cached enrichment results[/yellow]\n")

    if Confirm.ask("Are you sure?", default=False):
        clear_cache()
        show_success("Cache cleared successfully")
    else:
        show_info("Cancelled")


@cli.command()
def examples():
    """Show example CSV formats and usage"""
    from rich.panel import Panel
    from rich.syntax import Syntax

    console.print("[bold cyan]Example CSV Formats[/bold cyan]\n")

    # Demand CSV example
    demand_csv = """Full Name,Company Name,Domain,Signal,Company Description
John Doe,Acme Corp,acme.com,Hiring: Senior Engineer,B2B SaaS platform
Jane Smith,TechFlow,techflow.io,Raised $10M Series A,Cloud infrastructure"""

    console.print("[bold]Demand CSV (demand.csv):[/bold]")
    console.print(Panel(demand_csv, border_style="green"))
    console.print()

    # Supply CSV example
    supply_csv = """Full Name,Company Name,Domain,Service Description
Bob Johnson,TechRecruit,techrecruit.com,We help companies hire engineers quickly
Alice Williams,DevAgency,devagency.io,Full-stack development agency"""

    console.print("[bold]Supply CSV (supply.csv):[/bold]")
    console.print(Panel(supply_csv, border_style="blue"))
    console.print()

    # Usage example
    console.print("[bold cyan]Usage Examples[/bold cyan]\n")
    console.print("[bold]1. Interactive mode (recommended):[/bold]")
    console.print("   [white]signalis connector[/white]\n")

    console.print("[bold]2. Direct mode:[/bold]")
    console.print("   [white]signalis connector run --demand demand.csv --supply supply.csv[/white]\n")

    console.print("[bold]3. With options:[/bold]")
    console.print("   [white]signalis connector run -d demand.csv -s supply.csv --min-score 40 --format both[/white]\n")


def main():
    """Entry point for CLI"""
    # Check if running standalone or from launcher
    standalone = __name__ == '__main__'

    try:
        cli()
    except KeyboardInterrupt:
        console.print("\n\n[yellow]▲  Operation cancelled by user[/yellow]")
        if standalone:
            sys.exit(0)
        else:
            # Return gracefully to launcher
            return
    except click.Abort:
        # User cancelled or validation failed - return gracefully
        if standalone:
            sys.exit(1)
        else:
            return
    except Exception as e:
        console.print(f"\n[red]☿ Unexpected error: {e}[/red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        if standalone:
            sys.exit(1)
        else:
            # Return gracefully to launcher
            return


if __name__ == '__main__':
    main()
