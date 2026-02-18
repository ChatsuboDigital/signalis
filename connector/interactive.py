"""
Interactive Mode for Connector

Guides users through the flow with prompts and questions.
"""

import os
from pathlib import Path
from rich.prompt import Prompt, Confirm

# Optional inquirer import - fallback to rich prompts if not available
try:
    import inquirer
    HAS_INQUIRER = True
except ImportError:
    HAS_INQUIRER = False

from .banner import show_step, show_success, show_warning, show_info, show_error, console
from .config import ConnectorConfig

def ask_for_csv_files():
    """Ask user for CSV file paths"""
    show_step(1, "CSV Files", "We need your demand and supply CSV files")

    if HAS_INQUIRER:
        questions = [
            inquirer.Path(
                'demand',
                message="Path to demand CSV file",
                exists=True,
                path_type=inquirer.Path.FILE,
            ),
            inquirer.Path(
                'supply',
                message="Path to supply CSV file",
                exists=True,
                path_type=inquirer.Path.FILE,
            ),
        ]

        answers = inquirer.prompt(questions)
        if not answers:
            return None, None

        return answers['demand'], answers['supply']
    else:
        # Fallback to rich prompts
        demand = Prompt.ask("[cyan]Path to demand CSV file[/cyan]")
        supply = Prompt.ask("[cyan]Path to supply CSV file[/cyan]")
        return demand, supply


def ask_for_output_dir():
    """Ask user for output directory"""
    try:
        from core.config import get_config
        default_output = str(get_config().get_output_dir('connector'))
    except Exception:
        default_output = './output'
    output_dir = Prompt.ask(
        "[cyan]Output directory[/cyan]",
        default=default_output
    )
    return output_dir


def ask_for_match_score():
    """Ask user for minimum match score"""
    show_info("Match score filters: Higher = fewer but better matches")

    if HAS_INQUIRER:
        questions = [
            inquirer.List(
                'score',
                message="Minimum match score threshold",
                choices=[
                    ('50+ (Very High Quality - Strong matches only)', 50),
                    ('40+ (High Quality - Good and strong matches)', 40),
                    ('30+ (Balanced - Recommended)', 30),
                    ('20+ (More Matches - Include exploratory)', 20),
                    ('0+ (All Matches - No filter)', 0),
                ],
                default=30,
            ),
        ]

        answers = inquirer.prompt(questions)
        return answers['score'] if answers else 30
    else:
        # Fallback to rich prompts
        console.print("\n[cyan]Minimum match score threshold:[/cyan]")
        console.print("  [white]1[/white]  50+ (Very High Quality - Strong matches only)")
        console.print("  [white]2[/white]  40+ (High Quality - Good and strong matches)")
        console.print("  [white]3[/white]  30+ (Balanced - Recommended)")
        console.print("  [white]4[/white]  20+ (More Matches - Include exploratory)")
        console.print("  [white]5[/white]  0+ (All Matches - No filter)")

        choice = Prompt.ask("\nSelect option", choices=["1", "2", "3", "4", "5"], default="3")
        score_map = {"1": 50, "2": 40, "3": 30, "4": 20, "5": 0}
        return score_map[choice]


def ask_for_enrichment():
    """Ask if user wants enrichment"""
    show_step(2, "Email Enrichment", "Find missing contact emails automatically")

    # Check if API keys are configured
    has_apollo = bool(os.getenv('APOLLO_API_KEY'))
    has_anymail = bool(os.getenv('ANYMAIL_API_KEY'))
    has_ssm = bool(os.getenv('SSM_API_KEY'))

    if not any([has_apollo, has_anymail, has_ssm]):
        show_warning("No enrichment API keys found in .env file")
        show_info("You can still run matching without enrichment")
        enable = Confirm.ask("[yellow]Skip enrichment?[/yellow]", default=True)
        return not enable
    else:
        providers = []
        if has_apollo:
            providers.append("Apollo")
        if has_anymail:
            providers.append("Anymail Finder")
        if has_ssm:
            providers.append("SSM")

        show_success(f"Found API keys for: {', '.join(providers)}")
        enable = Confirm.ask("[cyan]Enable email enrichment?[/cyan]", default=True)
        return enable


def ask_for_ai_intros():
    """Ask if user wants AI intro generation"""
    show_step(3, "AI Intro Generation", "Generate personalized email introductions")

    ai_key = os.getenv('AI_API_KEY') or os.getenv('OPENAI_API_KEY') or os.getenv('ANTHROPIC_API_KEY')

    if not ai_key:
        show_warning("No AI API key found in .env file")
        show_info("Add OPENAI_API_KEY or ANTHROPIC_API_KEY to enable this feature")
        return False, None
    else:
        provider = os.getenv('AI_PROVIDER', 'openai')
        show_success(f"Using {provider.upper()} for AI generation")

        enable = Confirm.ask("[cyan]Generate AI-powered intros?[/cyan]", default=True)

        if enable:
            # Ask for model preference
            if HAS_INQUIRER:
                if provider == 'openai':
                    questions = [
                        inquirer.List(
                            'model',
                            message="Choose OpenAI model",
                            choices=[
                                ('GPT-4o Mini (Fast & Cheap - Recommended)', 'gpt-4o-mini'),
                                ('GPT-4o (More Capable)', 'gpt-4o'),
                                ('GPT-4 (Most Capable)', 'gpt-4'),
                            ],
                            default='gpt-4o-mini',
                        ),
                    ]
                elif provider == 'anthropic':
                    questions = [
                        inquirer.List(
                            'model',
                            message="Choose Anthropic model",
                            choices=[
                                ('Claude 3 Haiku (Fast & Cheap - Recommended)', 'claude-3-haiku-20240307'),
                                ('Claude 3 Sonnet (Balanced)', 'claude-3-sonnet-20240229'),
                                ('Claude 3 Opus (Most Capable)', 'claude-3-opus-20240229'),
                            ],
                            default='claude-3-haiku-20240307',
                        ),
                    ]
                else:
                    return enable, None

                answers = inquirer.prompt(questions)
                return enable, answers['model'] if answers else None
            else:
                # Fallback to rich prompts
                if provider == 'openai':
                    console.print("\n[cyan]Choose OpenAI model:[/cyan]")
                    console.print("  [white]1[/white]  GPT-4o Mini (Fast & Cheap - Recommended)")
                    console.print("  [white]2[/white]  GPT-4o (More Capable)")
                    console.print("  [white]3[/white]  GPT-4 (Most Capable)")

                    choice = Prompt.ask("\nSelect option", choices=["1", "2", "3"], default="1")
                    model_map = {"1": "gpt-4o-mini", "2": "gpt-4o", "3": "gpt-4"}
                    return enable, model_map[choice]
                elif provider == 'anthropic':
                    console.print("\n[cyan]Choose Anthropic model:[/cyan]")
                    console.print("  [white]1[/white]  Claude 3 Haiku (Fast & Cheap - Recommended)")
                    console.print("  [white]2[/white]  Claude 3 Sonnet (Balanced)")
                    console.print("  [white]3[/white]  Claude 3 Opus (Most Capable)")

                    choice = Prompt.ask("\nSelect option", choices=["1", "2", "3"], default="1")
                    model_map = {"1": "claude-3-haiku-20240307", "2": "claude-3-sonnet-20240229", "3": "claude-3-opus-20240229"}
                    return enable, model_map[choice]
                else:
                    return enable, None

        return False, None


def ask_for_email_sending():
    """Ask if user wants to send emails to campaigns"""
    show_step(4, "Email Sending", "Send generated intros to campaign platform")

    # Check for sending API keys
    has_instantly = bool(os.getenv('INSTANTLY_API_KEY'))
    has_plusvibe = bool(os.getenv('PLUSVIBE_API_KEY') and os.getenv('PLUSVIBE_WORKSPACE_ID'))

    if not has_instantly and not has_plusvibe:
        show_warning("No sender API keys found in .env file")
        show_info("Add INSTANTLY_API_KEY or PLUSVIBE_API_KEY to enable sending")
        return False

    # Auto-detect provider if not explicitly set
    configured_provider = os.getenv('SENDING_PROVIDER')

    if not configured_provider:
        # Auto-detect based on available API keys
        if has_plusvibe and not has_instantly:
            provider = 'plusvibe'
            show_info("Auto-detected PlusVibe (set SENDING_PROVIDER=plusvibe in .env to persist)")
        elif has_instantly:
            provider = 'instantly'  # Default to Instantly if both or only Instantly
            show_info("Auto-detected Instantly.ai (set SENDING_PROVIDER=instantly in .env to persist)")
        else:
            provider = 'instantly'  # Fallback default
    else:
        provider = configured_provider

    # Show which provider is being used
    if provider == 'instantly' and has_instantly:
        show_success("Using Instantly.ai for sending")
    elif provider == 'plusvibe' and has_plusvibe:
        show_success("Using PlusVibe for sending")
    elif provider == 'instantly' and not has_instantly:
        show_warning(f"Provider set to 'instantly' but INSTANTLY_API_KEY not found")
        return False
    elif provider == 'plusvibe' and not has_plusvibe:
        show_warning(f"Provider set to 'plusvibe' but PLUSVIBE_API_KEY or PLUSVIBE_WORKSPACE_ID not found")
        return False

    # Temporarily set provider for this session if auto-detected
    if not configured_provider:
        os.environ['SENDING_PROVIDER'] = provider

    # Check for campaign IDs
    has_demand_campaign = bool(os.getenv('DEMAND_CAMPAIGN_ID'))
    has_supply_campaign = bool(os.getenv('SUPPLY_CAMPAIGN_ID'))

    if not has_demand_campaign and not has_supply_campaign:
        show_warning("No campaign IDs configured")
        show_info("Add DEMAND_CAMPAIGN_ID and/or SUPPLY_CAMPAIGN_ID to .env")
        return False

    # Read default from .env
    default_enable = os.getenv('ENABLE_SENDING', 'false').lower() == 'true'

    enable = Confirm.ask("[cyan]Send emails to campaign platform?[/cyan]", default=default_enable)
    return enable


def ask_for_output_format():
    """Ask user for output format"""
    if HAS_INQUIRER:
        questions = [
            inquirer.List(
                'format',
                message="Output format",
                choices=[
                    ('CSV (Spreadsheet-friendly)', 'csv'),
                    ('JSON (Developer-friendly)', 'json'),
                    ('Both CSV and JSON', 'both'),
                ],
                default='csv',
            ),
        ]

        answers = inquirer.prompt(questions)
        return answers['format'] if answers else 'csv'
    else:
        # Fallback to rich prompts
        console.print("\n[cyan]Output format:[/cyan]")
        console.print("  [white]1[/white]  CSV (Spreadsheet-friendly)")
        console.print("  [white]2[/white]  JSON (Developer-friendly)")
        console.print("  [white]3[/white]  Both CSV and JSON")

        choice = Prompt.ask("\nSelect option", choices=["1", "2", "3"], default="1")
        format_map = {"1": "csv", "2": "json", "3": "both"}
        return format_map[choice]


def confirm_run(config_summary: dict):
    """Show configuration summary and ask for confirmation"""
    console.print()
    console.print("[bold cyan]Configuration Summary:[/bold cyan]")
    console.print(f"  Demand CSV: [white]{config_summary['demand']}[/white]")
    console.print(f"  Supply CSV: [white]{config_summary['supply']}[/white]")
    console.print(f"  Output Dir: [white]{config_summary['output_dir']}[/white]")
    console.print(f"  Min Score: [white]{config_summary['min_score']}[/white]")
    console.print(f"  Enrichment: [white]{'Enabled' if config_summary['enrich'] else 'Disabled'}[/white]")
    console.print(f"  AI Intros: [white]{'Enabled' if config_summary['ai_intros'] else 'Disabled'}[/white]")
    if config_summary.get('ai_model'):
        console.print(f"  AI Model: [white]{config_summary['ai_model']}[/white]")
    console.print(f"  Email Sending: [white]{'Enabled' if config_summary.get('enable_sending') else 'Disabled'}[/white]")
    console.print(f"  Format: [white]{config_summary['format'].upper()}[/white]")
    console.print()

    return Confirm.ask("[bold green]Start the flow?[/bold green]", default=True)


def run_interactive_setup():
    """
    Run interactive setup wizard.
    Returns configuration dict or None if cancelled.
    """
    # Step 1: CSV Files
    demand_file, supply_file = ask_for_csv_files()
    if not demand_file or not supply_file:
        return None

    output_dir = ask_for_output_dir()

    # Step 2: Match Score
    console.print()
    min_score = ask_for_match_score()

    # Step 3: Enrichment
    console.print()
    enable_enrich = ask_for_enrichment()

    # Step 4: AI Intros
    console.print()
    enable_ai, ai_model = ask_for_ai_intros()

    # Step 5: Email Sending (only if AI intros are enabled)
    enable_sending = False
    if enable_ai:
        console.print()
        enable_sending = ask_for_email_sending()

    # Step 6: Output Format
    console.print()
    output_format = ask_for_output_format()

    # Confirm
    config_summary = {
        'demand': demand_file,
        'supply': supply_file,
        'output_dir': output_dir,
        'min_score': min_score,
        'enrich': enable_enrich,
        'ai_intros': enable_ai,
        'ai_model': ai_model,
        'enable_sending': enable_sending,
        'format': output_format,
    }

    console.print()
    if not confirm_run(config_summary):
        show_warning("Cancelled by user")
        return None

    return config_summary


def check_first_run():
    """Check if this is the first run and guide user through setup"""
    signalis_dir = Path(__file__).parent.parent
    env_file = signalis_dir / '.env'

    if not env_file.exists():
        console.print()
        console.print("[yellow]▲ First time setup required![/yellow]")
        console.print()
        console.print("I don't see a [cyan].env[/cyan] file with your API keys.")
        console.print()

        if Confirm.ask("Would you like me to create one now?", default=True):
            # Copy .env.example to .env
            example_file = signalis_dir / '.env.example'
            if example_file.exists():
                import shutil
                shutil.copy(example_file, env_file)
                show_success("Created .env file from template")
                console.print()
                console.print("[cyan]Next steps:[/cyan]")
                console.print("  1. Open [white].env[/white] in your text editor")
                console.print("  2. Add your API keys (OpenAI, Apollo, etc.)")
                console.print("  3. Run [white]signalis connect[/white] again")
                console.print()
                return False
            else:
                show_error("Could not find .env.example template")
                return False
        else:
            console.print()
            console.print("You can still run matching without API keys,")
            console.print("but enrichment and AI intros will be disabled.")
            console.print()
            return True

    return True


def show_quick_tips():
    """Show quick tips for users"""
    from rich.panel import Panel

    tips = Panel(
        "[bold cyan]Quick Tips:[/bold cyan]\n\n"
        "• Use [white]--help[/white] to see all options\n"
        "• CSV files need: Full Name, Company Name, Domain\n"
        "• Higher match scores = fewer but better matches\n"
        "• Enrichment finds missing emails (requires API keys)\n"
        "• AI intros work best with OpenAI or Anthropic\n\n"
        "[dim]Type 'signalis connect' to start in interactive mode[/dim]",
        border_style="blue",
        padding=(1, 2)
    )
    console.print(tips)
    console.print()
