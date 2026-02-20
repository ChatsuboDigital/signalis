"""
Semantic Expansion for Matching - MATCH-1

Port of connector-os/src/matching/semantic.ts
Advanced semantic expansion with dual-direction mapping, ambiguity resolution,
and text-based context detection.

GOVERNANCE: Code-owned taxonomy. No admin UI. No runtime edits.
Changes require code review + deploy.
"""

import re
from typing import Any, Set, List, Dict, Literal, Optional, Tuple
from dataclasses import dataclass


# =============================================================================
# FEATURE FLAG
# =============================================================================

SEMANTIC_MATCHING_ENABLED = True


# =============================================================================
# MATCH-1A: Dual Direction Taxonomy
# =============================================================================

# Supply capability expansions - What suppliers DO
SUPPLY_CAPABILITY_EXPANSIONS = {
    'recruiting': [
        'hiring', 'talent acquisition', 'staffing', 'headhunting',
        'recruiter', 'placement', 'sourcing', 'talent', 'hire',
        'engineer', 'engineers', 'engineering', 'developer', 'software',
        'sales', 'marketing'
    ],
    'recruit': ['hiring', 'talent', 'staffing', 'hire'],
    'staffing': ['recruiting', 'hiring', 'talent', 'hire'],
    'talent': ['recruiting', 'hiring', 'staffing', 'hire'],
    'engineering_recruiting': [
        'technical hiring', 'hire engineers', 'engineering hires',
        'tech hiring', 'developer hiring', 'engineer', 'software'
    ],
    'sales_recruiting': [
        'sales hiring', 'hire salespeople', 'sales hires', 'revenue hiring'
    ],
    'marketing_recruiting': [
        'marketing hiring', 'hire marketers', 'marketing hires'
    ],
    'executive_recruiting': [
        'executive hiring', 'leadership hiring', 'c-suite hiring', 'executive search'
    ],
}

# Demand need expansions - What companies NEED
DEMAND_NEED_EXPANSIONS = {
    'hiring': [
        'recruiting', 'talent acquisition', 'staffing', 'team building',
        'headcount', 'recruit', 'recruiter'
    ],
    'engineer': [
        'recruiting', 'staffing', 'talent', 'hire', 'hiring', 'technical hiring'
    ],
    'engineers': [
        'recruiting', 'staffing', 'talent', 'hire', 'hiring'
    ],
    'engineering': [
        'recruiting', 'staffing', 'talent', 'hire', 'hiring',
        'engineering hires', 'hire engineers', 'technical hiring',
        'developer', 'software engineer', 'tech talent'
    ],
    'software': [
        'recruiting', 'staffing', 'talent', 'hire', 'engineering'
    ],
    'developer': [
        'recruiting', 'staffing', 'talent', 'hire', 'engineering'
    ],
    'sales': [
        'recruiting', 'staffing', 'talent', 'hire', 'hiring',
        'sales hires', 'hire salespeople', 'sales talent', 'revenue team'
    ],
    'marketing': [
        'recruiting', 'staffing', 'talent', 'hire', 'hiring',
        'marketing hires', 'hire marketers', 'marketing talent'
    ],
    'operations': [
        'recruiting', 'staffing', 'talent', 'hire',
        'operations hires', 'hire ops', 'ops talent'
    ],
    'finance': [
        'recruiting', 'staffing', 'talent', 'hire',
        'finance hires', 'hire finance', 'accounting talent'
    ],
}


# =============================================================================
# MATCH-1B: Ambiguity Resolution (Context Gate)
# =============================================================================

@dataclass
class SemanticContext:
    """Context for semantic expansion"""
    side: Literal['demand', 'supply']
    text: str


def resolve_ambiguous_term(
    term: str,
    ctx: SemanticContext
) -> Optional[Literal['need', 'capability']]:
    """
    Resolve ambiguous terms based on context.

    Returns:
        'need' - Term indicates demand needing something
        'capability' - Term indicates supply providing something
        None - Not ambiguous or no clear context

    Example:
        resolve_ambiguous_term('engineering', SemanticContext(
            side='demand',
            text='Hiring 5 engineers'
        )) → 'need'

        resolve_ambiguous_term('engineering', SemanticContext(
            side='supply',
            text='Engineering recruiting agency'
        )) → 'capability'
    """
    lower_term = term.lower()
    lower_text = ctx.text.lower()

    # Context indicators
    has_hiring_context = bool(re.search(
        r'\b(hire|hiring|team|headcount|recruit|talent|staffing|placement)\b',
        lower_text
    ))
    has_recruiting_context = bool(re.search(
        r'\b(recruit|recruiting|staffing|talent|headhunt|placement|sourcing)\b',
        lower_text
    ))

    # ENGINEERING / ENGINEER / ENGINEERS
    if lower_term in ['engineering', 'engineer', 'engineers']:
        if ctx.side == 'demand' and has_hiring_context:
            return 'need'  # Demand + hiring context → NEED engineers
        if ctx.side == 'supply' and has_recruiting_context:
            return 'capability'  # Supply + recruiting context → PROVIDES engineering recruiting
        # Else → treat as software capability, do NOT map to hiring
        return None

    # SALES
    if lower_term == 'sales':
        if ctx.side == 'demand' and has_hiring_context:
            return 'need'
        if ctx.side == 'supply' and has_recruiting_context:
            return 'capability'
        return None

    # MARKETING
    if lower_term == 'marketing':
        if ctx.side == 'demand' and has_hiring_context:
            return 'need'
        if ctx.side == 'supply' and has_recruiting_context:
            return 'capability'
        return None

    # GROWTH
    if lower_term == 'growth':
        # Expand into hiring ONLY if text includes hiring indicators
        if has_hiring_context:
            return 'need' if ctx.side == 'demand' else 'capability'
        # Ambiguous + no context → do not expand
        return None

    # Not an ambiguous term
    return None


# =============================================================================
# MATCH-1C: Semantic Expansion Function
# =============================================================================

@dataclass
class SemanticExpansionResult:
    """Result of semantic expansion"""
    base: Set[str]
    expanded: Set[str]
    reasons: Dict[str, List[str]]


def expand_semantic_signals(
    tokens: List[str],
    ctx: SemanticContext
) -> SemanticExpansionResult:
    """
    Expand tokens with semantic equivalents.

    Args:
        tokens: Original tokens to expand
        ctx: Context for ambiguity resolution

    Returns:
        SemanticExpansionResult with base tokens, expanded tokens, and reasons
    """
    base = set(t.lower() for t in tokens)
    expanded = set(base)
    reasons: Dict[str, List[str]] = {}

    # If feature flag disabled, return base only
    if not SEMANTIC_MATCHING_ENABLED:
        return SemanticExpansionResult(base=base, expanded=expanded, reasons=reasons)

    lower_text = ctx.text.lower()

    # Select expansion map based on side
    expansion_map = (
        DEMAND_NEED_EXPANSIONS if ctx.side == 'demand'
        else SUPPLY_CAPABILITY_EXPANSIONS
    )

    # Process each token
    for token in tokens:
        lower_token = token.lower()

        # Check direct taxonomy match
        if lower_token in expansion_map:
            for expansion in expansion_map[lower_token]:
                exp_lower = expansion.lower()
                expanded.add(exp_lower)
                if exp_lower not in reasons:
                    reasons[exp_lower] = []
                reasons[exp_lower].append(f'taxonomy:{lower_token}')

        # Check ambiguity resolution
        resolution = resolve_ambiguous_term(lower_token, ctx)
        if resolution:
            # Add cross-functional expansions based on resolution
            if resolution == 'need' and ctx.side == 'demand':
                # Demand needs hiring help → add recruiting equivalents
                hiring_expansions = DEMAND_NEED_EXPANSIONS.get('hiring', [])
                for exp in hiring_expansions:
                    exp_lower = exp.lower()
                    expanded.add(exp_lower)
                    if exp_lower not in reasons:
                        reasons[exp_lower] = []
                    reasons[exp_lower].append(f'ambiguity:{lower_token}→need')

            if resolution == 'capability' and ctx.side == 'supply':
                # Supply does recruiting → add hiring equivalents
                recruiting_expansions = SUPPLY_CAPABILITY_EXPANSIONS.get('recruiting', [])
                for exp in recruiting_expansions:
                    exp_lower = exp.lower()
                    expanded.add(exp_lower)
                    if exp_lower not in reasons:
                        reasons[exp_lower] = []
                    reasons[exp_lower].append(f'ambiguity:{lower_token}→capability')

    # TEXT-BASED CONTEXT DETECTION (MATCH-1D)
    # Check for recruiting/hiring keywords in text and expand
    if ctx.side == 'supply':
        if re.search(r'\b(recruit|recruiting|staffing|talent|headhunt|placement)\b', lower_text):
            recruiting_expansions = SUPPLY_CAPABILITY_EXPANSIONS.get('recruiting', [])
            for exp in recruiting_expansions:
                exp_lower = exp.lower()
                if exp_lower not in expanded:
                    expanded.add(exp_lower)
                    if exp_lower not in reasons:
                        reasons[exp_lower] = []
                    reasons[exp_lower].append('text:recruiting_detected')

    if ctx.side == 'demand':
        if re.search(r'\b(hiring|hire|hires|team building|headcount)\b', lower_text):
            hiring_expansions = DEMAND_NEED_EXPANSIONS.get('hiring', [])
            for exp in hiring_expansions:
                exp_lower = exp.lower()
                if exp_lower not in expanded:
                    expanded.add(exp_lower)
                    if exp_lower not in reasons:
                        reasons[exp_lower] = []
                    reasons[exp_lower].append('text:hiring_detected')

    return SemanticExpansionResult(base=base, expanded=expanded, reasons=reasons)


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def extract_tokens(text: str) -> List[str]:
    """
    Extract meaningful tokens from text.
    Simple tokenization - splits on whitespace and punctuation.
    """
    if not text:
        return []

    # Lowercase and remove punctuation
    cleaned = re.sub(r'[^\w\s]', ' ', text.lower())

    # Split and filter short tokens
    tokens = [t for t in cleaned.split() if len(t) > 2]

    return tokens


def compute_semantic_overlap(
    demand_tokens: Set[str],
    supply_tokens: Set[str]
) -> Dict[str, Any]:
    """
    Compute semantic overlap between two token sets.

    Returns:
        {
            'overlapCount': number of matching tokens,
            'matchedTokens': list of tokens that matched
        }
    """
    matched = [token for token in demand_tokens if token in supply_tokens]

    return {
        'overlapCount': len(matched),
        'matchedTokens': matched
    }


def calculate_semantic_bonus(overlap_count: int) -> int:
    """
    Calculate bonus points based on semantic overlap.

    Thresholds (from connector-os):
    - 5+ matches: 30 points
    - 3-4 matches: 20 points
    - 1-2 matches: 10 points
    - 0 matches: 0 points
    """
    if overlap_count >= 5:
        return 30
    elif overlap_count >= 3:
        return 20
    elif overlap_count >= 1:
        return 10
    else:
        return 0


def get_semantic_score(demand_text: str, supply_text: str) -> Dict[str, Any]:
    """
    Complete semantic scoring pipeline.

    Args:
        demand_text: Full text from demand record
        supply_text: Full text from supply record

    Returns:
        {
            'bonus': int (0-30 points),
            'overlapCount': int,
            'matchedTokens': list
        }
    """
    # Extract tokens
    demand_tokens = extract_tokens(demand_text)
    supply_tokens = extract_tokens(supply_text)

    # Expand semantically with context
    demand_result = expand_semantic_signals(
        demand_tokens,
        SemanticContext(side='demand', text=demand_text)
    )
    supply_result = expand_semantic_signals(
        supply_tokens,
        SemanticContext(side='supply', text=supply_text)
    )

    # Compute overlap
    overlap = compute_semantic_overlap(
        demand_result.expanded,
        supply_result.expanded
    )

    # Calculate bonus
    bonus = calculate_semantic_bonus(overlap['overlapCount'])

    return {
        'bonus': bonus,
        'overlapCount': overlap['overlapCount'],
        'matchedTokens': overlap['matchedTokens']
    }
