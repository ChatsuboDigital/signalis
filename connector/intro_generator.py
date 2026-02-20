"""
AI Intro Generation Module

Python port of connector-os/src/services/IntroAI.ts
Variable-fill template generation for email introductions.
"""

import re
import json
from typing import Dict, Any, Optional, Literal
from concurrent.futures import ThreadPoolExecutor

# Optional AI provider imports
try:
    import openai
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

try:
    from anthropic import Anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

from .models import DemandRecord, SupplyRecord, Edge, GeneratedIntros


# =============================================================================
# AI CONFIG
# =============================================================================

class IntroAIConfig:
    """Configuration for AI intro generation"""
    def __init__(
        self,
        provider: Literal['openai', 'anthropic', 'azure'],
        api_key: str,
        model: Optional[str] = None,
        azure_endpoint: Optional[str] = None,
        azure_deployment: Optional[str] = None,
        openai_api_key_fallback: Optional[str] = None
    ):
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.azure_endpoint = azure_endpoint
        self.azure_deployment = azure_deployment
        self.openai_api_key_fallback = openai_api_key_fallback


# =============================================================================
# HELPERS
# =============================================================================

def clean_company_name(name: str) -> str:
    """Clean company name: ALL CAPS → Title Case, remove legal suffixes"""
    if not name:
        return name

    cleaned = name.strip()

    # Check if ALL CAPS
    letters_only = re.sub(r'[^a-zA-Z]', '', cleaned)
    uppercase_count = sum(1 for c in letters_only if c.isupper())
    is_all_caps = len(letters_only) > 3 and uppercase_count / len(letters_only) > 0.8

    if is_all_caps:
        # Match connector-os acronym list exactly
        acronyms = {
            'LP', 'LLC', 'LLP', 'GP', 'INC', 'CORP', 'LTD', 'CO',
            'USA', 'UK', 'NYC', 'LA', 'SF', 'AI', 'ML', 'IT', 'HR',
            'VP', 'CEO', 'CFO', 'CTO', 'COO', 'RIA', 'AUM', 'PE', 'VC'
        }
        words = re.split(r'(\s+)', cleaned.lower())
        words = [word.upper() if word.upper() in acronyms else word.capitalize() for word in words]
        cleaned = ''.join(words)

    # Remove legal suffixes - match connector-os regex exactly
    cleaned = re.sub(
        r',?\s*(llc|l\.l\.c\.|inc\.?|corp\.?|corporation|ltd\.?|limited|co\.?|company|pllc|lp|l\.p\.|llp|l\.l\.p\.)\s*$',
        '', cleaned, flags=re.IGNORECASE
    ).strip()

    return cleaned


def extract_first_name(full_name: str) -> str:
    """Extract first name from full name"""
    trimmed = (full_name or '').strip()
    if not trimmed:
        return 'there'
    return trimmed.split()[0] or trimmed


def a_or_an(word: str) -> str:
    """Return 'a' or 'an' based on first character"""
    if not word:
        return 'a'
    return 'an' if re.match(r'^[aeiou]', word.strip(), re.IGNORECASE) else 'a'


def strip_leading_article(s: str) -> str:
    """Strip leading articles ('a ', 'an ', 'the ') from AI-returned variables"""
    return re.sub(r'^(a |an |the )', '', s, flags=re.IGNORECASE).strip()


def parse_json(raw: str) -> Any:
    """Parse JSON from AI response"""
    cleaned = re.sub(r'```json\n?', '', raw)
    cleaned = re.sub(r'```\n?', '', cleaned).strip()
    return json.loads(cleaned)


# =============================================================================
# PROMPT BUILDERS
# =============================================================================

def build_supply_vars_prompt(demand: DemandRecord, edge: Edge) -> str:
    """Build prompt for supply-side variables"""
    desc = (demand.metadata.get('companyDescription') or demand.metadata.get('description') or '')[:400]
    funding_usd = demand.metadata.get('fundingUsd', 0)
    funding = f"${funding_usd / 1_000_000:.0f}M raised" if funding_usd else ''

    return f"""Fill variables for a cold email. JSON only.

TEMPLATE: "I got a couple [dreamICP] who are looking for [painTheySolve]"

DATA:
- Signal: {edge.evidence or 'active in market'}
- Industry: {demand.industry or 'general'}
- Description: {desc}
{f'- Funding: {funding}' if funding else ''}

RULES:
- [dreamICP]: plural noun phrase describing the demand company type + vertical. 3-6 words. No "decision-makers"/"stakeholders"/"organizations".
- [painTheySolve]: what they need, from the signal data. Human language. 3-8 words. No "optimize"/"leverage"/"streamline"/"solutions".
- Both must sound like how you'd talk at a bar, not a boardroom.

{{"dreamICP": "...", "painTheySolve": "..."}}"""


def build_demand_vars_prompt(demand: DemandRecord, supply: SupplyRecord, edge: Edge) -> str:
    """Build prompt for demand-side variables"""
    supply_desc = (supply.metadata.get('companyDescription') or supply.metadata.get('description') or '')[:400]
    demand_industry = demand.industry or 'unknown'
    demand_desc = (demand.metadata.get('companyDescription') or demand.metadata.get('description') or '')[:200]

    return f"""Fill 2 variables. JSON only.

TEMPLATE: "Saw {{{{company}}}} [signalEvent]. I'm connected to [whoTheyAre] — want an intro?"

DEMAND CONTEXT:
Industry: {demand_industry}
Description: {demand_desc}

SUPPLY: {supply.capability or 'business services'}{(' — ' + supply_desc) if supply_desc else ''}
SIGNAL: {edge.evidence or 'active in market'}

RULES:

[signalEvent]: casual fragment completing "Saw {{{{company}}}}...". 3–8 words. No word "role". If signal says "hiring X", say "is hiring X" or "just posted for X".

[whoTheyAre]:
Describe what the supplier ENABLES companies with this SIGNAL to achieve faster or better.
Do NOT describe what the supplier is. Describe what they help the company accomplish.
MUST be a team/firm/group of people (not product/software).
Tie capability to the SIGNAL pressure — focus on speed, capacity, or execution improvement.
Prefer the more specific industry term if available in DEMAND CONTEXT.
No "a/an". No "solutions/optimize/leverage/software/platform/tool".
No generic restatement of SUPPLY.
No temporal padding: "during growth", "during hiring surges", "as companies scale".
No consultant language: "scaling", "digital transformation", "optimization".

Good: "recruiting team that helps fintech companies fill engineering roles faster"
Good: "engineering partner teams use when product demand outpaces hiring"
Good: "team companies use when internal recruiting can't keep up"
Bad: "technology firm specializing in digital automation"
Bad: "staffing company for growing businesses"

{{"signalEvent": "...", "whoTheyAre": "..."}}"""


# =============================================================================
# ASSEMBLE FINAL EMAILS
# =============================================================================

def assemble_supply_intro(first_name: str, vars: Dict[str, str]) -> str:
    """Assemble supply-side intro email"""
    name = first_name if first_name and first_name not in ['there', 'Contact'] else 'there'

    return f"""Hey {name}

Not sure how many people are on your waiting list, but I got a couple {vars['dreamICP']} who are looking for {vars['painTheySolve']}

Worth an intro?"""


def assemble_demand_intro(first_name: str, company_name: str, vars: Dict[str, str]) -> str:
    """Assemble demand-side intro email"""
    name = first_name if first_name and first_name not in ['there', 'Decision'] else 'there'
    company = clean_company_name(company_name)
    article = a_or_an(vars['whoTheyAre'])

    return f"""Hey {name}

Saw {company} {vars['signalEvent']}. I'm connected to {article} {vars['whoTheyAre']}

Want an intro?"""


# =============================================================================
# AI PROVIDER CALLS
# =============================================================================

def call_openai(config: IntroAIConfig, prompt: str) -> str:
    """Call OpenAI API"""
    client = openai.OpenAI(api_key=config.api_key)

    response = client.chat.completions.create(
        model=config.model or 'gpt-4o-mini',
        messages=[{'role': 'user', 'content': prompt}],
        temperature=0.3,
        max_tokens=200,
    )

    return response.choices[0].message.content or ''


def call_anthropic(config: IntroAIConfig, prompt: str) -> str:
    """Call Anthropic API"""
    client = Anthropic(api_key=config.api_key)

    response = client.messages.create(
        model=config.model or 'claude-3-haiku-20240307',
        max_tokens=200,
        temperature=0.3,
        messages=[{'role': 'user', 'content': prompt}],
    )

    return response.content[0].text if response.content else ''


def call_ai(config: IntroAIConfig, prompt: str) -> str:
    """Call configured AI provider"""
    if config.provider == 'openai':
        return call_openai(config, prompt)
    elif config.provider == 'anthropic':
        return call_anthropic(config, prompt)
    elif config.provider == 'azure':
        # Azure OpenAI
        client = openai.AzureOpenAI(
            api_key=config.api_key,
            azure_endpoint=config.azure_endpoint or '',
            api_version='2024-02-15-preview',
        )

        response = client.chat.completions.create(
            model=config.azure_deployment or 'gpt-4',
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.3,
            max_tokens=200,
        )

        return response.choices[0].message.content or ''
    else:
        raise ValueError(f"Unknown AI provider: {config.provider}")


# =============================================================================
# FALLBACK TEMPLATES
# =============================================================================

def get_fallback_intros(demand: DemandRecord, supply: SupplyRecord, edge: Edge, error: str = '') -> GeneratedIntros:
    """
    Generate deterministic fallback intros when AI fails.

    These are generic but functional templates that don't require AI.
    Used when AI API is down, rate limited, or returns errors.
    """
    demand_first_name = extract_first_name(demand.contact)
    supply_first_name = extract_first_name(supply.contact)

    # Generic but functional templates
    supply_intro = (
        f"Hey {supply_first_name}, "
        f"I got a company ({demand.company or 'potential client'}) "
        f"looking for {edge.evidence or 'services like yours'}. "
        f"Interested in connecting?"
    )

    demand_intro = (
        f"Hey {demand_first_name}, "
        f"I'm connected to a {supply.company or 'service provider'} "
        f"that might be able to help with {edge.evidence or 'your needs'}. "
        f"Want an intro?"
    )

    return GeneratedIntros(
        demand_intro=demand_intro,
        supply_intro=supply_intro,
        value_props={
            'demandValueProp': 'Generic fallback (AI unavailable)',
            'supplyValueProp': 'Generic fallback (AI unavailable)',
        },
        source='fallback',
        error=error
    )


# =============================================================================
# MAIN EXPORT
# =============================================================================

def generate_intros_ai(
    config: IntroAIConfig,
    demand: DemandRecord,
    supply: SupplyRecord,
    edge: Edge
) -> GeneratedIntros:
    """
    Generate intros by filling template variables (2 parallel AI calls).

    AI fills tight variables. Code assembles the email. No free-form writing.

    Falls back to generic templates if AI fails (API down, rate limit, etc).
    """
    demand_first_name = extract_first_name(demand.contact)
    supply_first_name = extract_first_name(supply.contact)

    # Two AI calls in parallel (matches connector-os Promise.all behavior)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            # Submit both AI calls simultaneously
            supply_future = executor.submit(
                call_ai, config, build_supply_vars_prompt(demand, edge)
            )
            demand_future = executor.submit(
                call_ai, config, build_demand_vars_prompt(demand, supply, edge)
            )

            # Wait for both to complete
            supply_vars_raw = supply_future.result()
            demand_vars_raw = demand_future.result()
    except Exception as e:
        # AI call failed completely - use fallback templates
        return get_fallback_intros(demand, supply, edge, error=str(e))

    # Parse supply variables
    try:
        supply_vars = parse_json(supply_vars_raw)
    except Exception as e:
        # Silently use fallback on parse error
        supply_vars = {
            'dreamICP': f"{demand.industry or 'companies'} in your space".lower(),
            'painTheySolve': edge.evidence or 'what they need right now',
        }

    # Parse demand variables
    try:
        parsed = parse_json(demand_vars_raw)
        demand_vars = {
            'signalEvent': parsed.get('signalEvent', 'is making moves'),
            'whoTheyAre': strip_leading_article(parsed.get('whoTheyAre', '')),
        }
    except Exception as e:
        # Silently use fallback on parse error
        demand_vars = {
            'signalEvent': 'is making moves',
            'whoTheyAre': f"{supply.capability or 'services'} firm",
        }

    # Assemble emails
    supply_intro = assemble_supply_intro(supply_first_name, supply_vars)
    demand_intro = assemble_demand_intro(demand_first_name, demand.company, demand_vars)

    return GeneratedIntros(
        demand_intro=demand_intro,
        supply_intro=supply_intro,
        value_props={
            'demandValueProp': f"{demand_vars['signalEvent']} → {demand_vars['whoTheyAre']}",
            'supplyValueProp': f"{supply_vars['dreamICP']} looking for {supply_vars['painTheySolve']}",
        }
    )
