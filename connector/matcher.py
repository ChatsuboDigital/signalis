"""
Matching Engine Module

Python port of connector-os/src/matching/index.ts
Core intelligence for matching demand and supply records.
"""

import re
from typing import List, Dict, Any, Tuple, Optional, Literal
from dataclasses import dataclass

from .models import (
    NormalizedRecord, Match, MatchingResult,
    NeedProfile, CapabilityProfile, DemandRecord, SupplyRecord
)
from .semantic_expansion import get_semantic_score


# =============================================================================
# TYPE SAFETY UTILITIES
# =============================================================================

def to_string_safe(v: Any) -> str:
    """Safely convert any value to string"""
    if v is None:
        return ''
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float, bool)):
        return str(v)
    return str(v)


# =============================================================================
# NEED & CAPABILITY EXTRACTION
# =============================================================================

def extract_need_from_demand(demand: NormalizedRecord) -> NeedProfile:
    """
    Extract NEED from demand signals.
    What does this company actually need?

    Sources (in priority order):
    1. Job title/signal (strongest - explicit need)
    2. Funding signal (general growth need)
    3. Company description (inferred need)
    """
    signal = to_string_safe(demand.signal).lower()
    title = to_string_safe(demand.title).lower()
    description = to_string_safe(demand.company_description).lower()
    funding = to_string_safe(demand.company_funding).lower()
    industry = to_string_safe(demand.industry).lower()
    company = to_string_safe(demand.company).lower()

    # CSV-ONLY: Use signal_meta.kind to detect data type
    is_hiring_data = demand.signal_meta and demand.signal_meta.kind == 'HIRING_ROLE'

    # ==========================================================================
    # NON-HIRING DATA — Analyze by INDUSTRY, not person's title
    # ==========================================================================
    if not is_hiring_data:
        industry_and_desc = f"{industry} {company} {description}"

        # Biotech/Pharma companies
        if re.search(r'biotech|pharma|therapeutic|clinical|life science|drug|medical device|biopharma',
                     industry_and_desc, re.IGNORECASE):
            return NeedProfile(
                category='biotech',
                specifics=['funded'] if funding else [],
                confidence=0.85,
                source='industry'
            )

        # Healthcare companies
        if re.search(r'health|medical|hospital|patient|clinic', industry_and_desc, re.IGNORECASE) and \
           not re.search(r'biotech|pharma', industry_and_desc, re.IGNORECASE):
            return NeedProfile(category='healthcare', specifics=[], confidence=0.8, source='industry')

        # Tech/Software companies
        if re.search(r'\bsoftware\b|saas|\bcloud\b|platform|digital|ai company|tech company',
                     industry_and_desc, re.IGNORECASE) and \
           not re.search(r'biotech|fintech|healthtech', industry_and_desc, re.IGNORECASE):
            return NeedProfile(category='tech', specifics=[], confidence=0.8, source='industry')

        # Fintech companies
        if re.search(r'fintech|financial technology', industry_and_desc, re.IGNORECASE):
            return NeedProfile(category='fintech', specifics=[], confidence=0.8, source='industry')

        # Finance companies
        if re.search(r'financ|banking|insurance|invest|capital|asset', industry_and_desc, re.IGNORECASE) and \
           not re.search(r'fintech', industry_and_desc, re.IGNORECASE):
            return NeedProfile(category='finance_co', specifics=[], confidence=0.75, source='industry')

        # Funding signal
        if funding or re.search(r'raised|funding|series|seed|round', description, re.IGNORECASE):
            return NeedProfile(
                category='growth',
                specifics=['post-funding', 'scaling'],
                confidence=0.7,
                source='funding_signal'
            )

        # General company
        return NeedProfile(category='company', specifics=[], confidence=0.4, source='industry')

    # ==========================================================================
    # JOB DATA — Analyze by role type (what they're hiring for)
    # ==========================================================================
    combined = f"{signal} {title}"

    # Engineering hiring
    if re.search(r'engineer|developer|\bsoftware\b|devops|backend|frontend|fullstack|ml\b|ai\b|data scientist',
                 combined, re.IGNORECASE) and not re.search(r'recruit', combined, re.IGNORECASE):
        specifics = []
        if re.search(r'senior|staff|lead|principal', combined, re.IGNORECASE):
            specifics.append('senior')
        if re.search(r'ml|machine learning|ai\b', combined, re.IGNORECASE):
            specifics.append('ML/AI')
        if re.search(r'backend|server', combined, re.IGNORECASE):
            specifics.append('backend')
        if re.search(r'frontend|react|ui', combined, re.IGNORECASE):
            specifics.append('frontend')

        return NeedProfile(category='engineering', specifics=specifics, confidence=0.9, source='job_signal')

    # Sales hiring
    if re.search(r'\bsales\b|account executive|\bae\b|\bsdr\b|\bbdr\b|revenue|business development|closer',
                 combined, re.IGNORECASE):
        specifics = []
        if re.search(r'vp|head|director', combined, re.IGNORECASE):
            specifics.append('leadership')
        if re.search(r'enterprise', combined, re.IGNORECASE):
            specifics.append('enterprise')

        return NeedProfile(category='sales', specifics=specifics, confidence=0.9, source='job_signal')

    # Marketing hiring
    if re.search(r'marketing|growth|brand|content|\bseo\b|paid|demand gen|gtm', combined, re.IGNORECASE):
        specifics = []
        if re.search(r'head|vp|director', combined, re.IGNORECASE):
            specifics.append('leadership')
        if re.search(r'content', combined, re.IGNORECASE):
            specifics.append('content')

        return NeedProfile(category='marketing', specifics=specifics, confidence=0.9, source='job_signal')

    # Finance hiring
    if re.search(r'\bfinance\b|\bcfo\b|accounting|controller|fp&a|bookkeep', combined, re.IGNORECASE):
        return NeedProfile(category='finance', specifics=[], confidence=0.9, source='job_signal')

    # Operations hiring
    if re.search(r'operations|\bops\b|\bcoo\b|chief operating|supply chain|logistics', combined, re.IGNORECASE):
        return NeedProfile(category='operations', specifics=[], confidence=0.9, source='job_signal')

    # Recruiting/HR hiring
    if re.search(r'recruiter|talent|\bhr\b|human resources|people ops', combined, re.IGNORECASE):
        return NeedProfile(category='recruiting', specifics=[], confidence=0.9, source='job_signal')

    # Funding signal = general growth need
    if funding or re.search(r'raised|funding|series|seed|round', combined + ' ' + description, re.IGNORECASE):
        return NeedProfile(
            category='growth',
            specifics=['post-funding', 'scaling'],
            confidence=0.7,
            source='funding_signal'
        )

    # No clear signal
    return NeedProfile(category='general', specifics=[], confidence=0.3, source='none')


def extract_capability_from_supply(supply: NormalizedRecord) -> CapabilityProfile:
    """
    Extract CAPABILITY from supply data — SCHEMA-AWARE.

    SERVICE PROVIDERS (agencies, recruiters, consultants):
      → Detect what service they offer

    CONTACTS AT COMPANIES (Leads Finder, B2B contacts):
      → These are potential PARTNERS/CONNECTORS, not service providers
      → Return industry-based capability for proper matching
    """
    description = to_string_safe(supply.company_description).lower()
    title = to_string_safe(supply.title).lower()
    company = to_string_safe(supply.company).lower()
    industry_raw = supply.industry
    industry = to_string_safe(industry_raw[0] if isinstance(industry_raw, list) else industry_raw).lower()

    combined = f"{description} {title} {company} {industry}"

    # ==========================================================================
    # FIRST: Check if this is clearly a SERVICE PROVIDER
    # ==========================================================================

    # Recruiting/Staffing
    if re.search(r'recruit|staffing|talent acquisition|headhunt|placement|hiring agency|staffing agency',
                 combined, re.IGNORECASE):
        specifics = []
        if re.search(r'engineer|\bsoftware\b', combined, re.IGNORECASE):
            specifics.append('tech')
        if re.search(r'executive|c-suite|leadership', combined, re.IGNORECASE):
            specifics.append('executive')

        confidence = 0.95 if 'recruit' in description else (0.85 if 'recruit' in title else 0.7)
        source = 'description' if 'recruit' in description else ('title' if 'recruit' in title else 'company_name')

        return CapabilityProfile(category='recruiting', specifics=specifics, confidence=confidence, source=source)

    # Marketing Agency
    if re.search(r'marketing agency|ad agency|advertising agency|creative agency|pr agency', combined, re.IGNORECASE):
        specifics = []
        if re.search(r'startup|venture', combined, re.IGNORECASE):
            specifics.append('startups')
        if re.search(r'enterprise|b2b', combined, re.IGNORECASE):
            specifics.append('enterprise')

        return CapabilityProfile(category='marketing', specifics=specifics, confidence=0.9, source='description')

    # Dev Shop/Software Agency
    if re.search(r'dev shop|development agency|software agency|software consultancy|app development',
                 combined, re.IGNORECASE):
        specifics = []
        if re.search(r'startup', combined, re.IGNORECASE):
            specifics.append('startups')
        if re.search(r'mobile|ios|android', combined, re.IGNORECASE):
            specifics.append('mobile')

        return CapabilityProfile(category='engineering', specifics=specifics, confidence=0.8, source='description')

    # Consulting/Advisory firm
    if re.search(r'consulting firm|advisory firm|management consulting|strategy consulting|consultancy',
                 combined, re.IGNORECASE):
        return CapabilityProfile(category='consulting', specifics=[], confidence=0.75, source='description')

    # Fractional/Interim executives
    if re.search(r'fractional|interim|outsourced cfo|outsourced coo|part-time executive', combined, re.IGNORECASE):
        return CapabilityProfile(category='fractional', specifics=[], confidence=0.8, source='title')

    # ==========================================================================
    # FALLBACK: This is a CONTACT at a company, not a service provider
    # ==========================================================================

    # Biotech/Pharma contact
    if re.search(r'biotech|pharma|therapeutic|clinical|life science|biopharma', combined, re.IGNORECASE):
        return CapabilityProfile(category='biotech_contact', specifics=[], confidence=0.7, source='industry')

    # Healthcare contact
    if re.search(r'health|medical|hospital', combined, re.IGNORECASE) and \
       not re.search(r'biotech|pharma', combined, re.IGNORECASE):
        return CapabilityProfile(category='healthcare_contact', specifics=[], confidence=0.65, source='industry')

    # Tech company contact
    if re.search(r'\bsoftware\b|saas|\bcloud\b|platform', combined, re.IGNORECASE) and \
       not re.search(r'agency|shop|development company|consultancy', combined, re.IGNORECASE):
        return CapabilityProfile(category='tech_contact', specifics=[], confidence=0.6, source='industry')

    # Finance contact
    if re.search(r'financ|banking|investment|capital', combined, re.IGNORECASE) and \
       not re.search(r'recruit', combined, re.IGNORECASE):
        return CapabilityProfile(category='finance_contact', specifics=[], confidence=0.6, source='industry')

    # BD/Licensing professional
    if re.search(r'business development|licensing|partnerships|bd\b', title, re.IGNORECASE):
        return CapabilityProfile(category='bd_professional', specifics=[], confidence=0.7, source='title')

    # Executive
    if re.search(r'ceo|cto|cfo|coo|founder|co-founder|president|chief', title, re.IGNORECASE):
        return CapabilityProfile(category='executive', specifics=[], confidence=0.5, source='title')

    # General professional
    return CapabilityProfile(category='professional', specifics=[], confidence=0.3, source='none')


# =============================================================================
# ALIGNMENT SCORING
# =============================================================================

def score_alignment(need: NeedProfile, capability: CapabilityProfile) -> float:
    """
    Calculate alignment score between need and capability.
    Returns 0-50 points based on how well they match.
    """
    need_cat = need.category
    cap_cat = capability.category

    # Industry-to-industry matching
    industry_matches = {
        'biotech': ['biotech_contact', 'bd_professional'],
        'healthcare': ['healthcare_contact', 'biotech_contact'],
        'tech': ['tech_contact', 'engineering'],
        'fintech': ['finance_contact', 'tech_contact'],
        'finance_co': ['finance_contact', 'consulting'],
    }

    if need_cat in industry_matches:
        if industry_matches[need_cat][0] == cap_cat:
            return 50  # Primary match
        if cap_cat in industry_matches[need_cat]:
            return 40  # Secondary match

    # Service provider matching
    if cap_cat == 'recruiting':
        if need_cat in ['engineering', 'sales', 'marketing', 'finance', 'operations', 'recruiting']:
            return 45

    if cap_cat == 'engineering' and need_cat == 'engineering':
        return 40

    if cap_cat == 'marketing' and need_cat == 'marketing':
        return 50

    if cap_cat == 'consulting':
        if need_cat in ['operations', 'growth', 'finance_co', 'company']:
            return 35

    if cap_cat == 'fractional':
        if need_cat in ['growth', 'finance', 'operations']:
            return 40

    # BD/Exec connectors
    if cap_cat == 'bd_professional':
        if need_cat in ['growth', 'biotech', 'healthcare', 'tech', 'fintech']:
            return 35
        return 20

    if cap_cat == 'executive':
        if need_cat == 'growth':
            return 30
        return 15

    # Growth need
    if need_cat == 'growth':
        if cap_cat in ['marketing', 'recruiting']:
            return 40
        if cap_cat in ['consulting', 'fractional']:
            return 35
        if cap_cat not in ['general', 'professional']:
            return 25
        return 15

    # Cross-functional matches
    cross_matches = {
        'engineering': ['recruiting', 'consulting'],
        'sales': ['marketing', 'recruiting'],
        'marketing': ['sales', 'growth'],
        'finance': ['consulting', 'fractional'],
    }

    if need_cat in cross_matches and cap_cat in cross_matches[need_cat]:
        return 25

    # Fallback
    if need_cat in ['general', 'company']:
        if cap_cat in ['consulting', 'bd_professional']:
            return 20
        return 15

    if cap_cat in ['general', 'professional']:
        return 10

    return 5


# =============================================================================
# TIER DETERMINATION
# =============================================================================

def determine_tier(
    score: float,
    need: NeedProfile,
    capability: CapabilityProfile,
    demand_signal_label: Optional[str] = None
) -> Tuple[Literal['strong', 'good', 'open'], str]:
    """Determine confidence tier based on score and profiles"""

    # Need labels
    need_labels = {
        'engineering': 'Hiring engineers',
        'sales': 'Hiring sales',
        'marketing': 'Hiring marketing',
        'recruiting': 'Hiring recruiters',
        'finance': 'Hiring finance',
        'operations': 'Hiring operations',
        'growth': 'Raised funding',
        'general': 'Active company',
        'biotech': 'Biotech company',
        'healthcare': 'Healthcare company',
        'tech': 'Tech company',
        'fintech': 'Fintech company',
        'finance_co': 'Finance company',
        'company': 'Company',
    }

    need_label = demand_signal_label or need_labels.get(need.category, need.category)

    # Capability labels
    cap_labels = {
        'recruiting': 'Recruiter',
        'marketing': 'Marketing agency',
        'engineering': 'Dev shop',
        'consulting': 'Consultant',
        'fractional': 'Fractional exec',
        'sales': 'Sales consultant',
        'finance': 'Finance consultant',
        'operations': 'Ops consultant',
        'growth': 'Growth partner',
        'general': 'Provider',
        'biotech_contact': 'Biotech BD contact',
        'healthcare_contact': 'Healthcare contact',
        'tech_contact': 'Tech contact',
        'finance_contact': 'Finance contact',
        'bd_professional': 'BD professional',
        'executive': 'Executive',
        'professional': 'Professional',
    }

    cap_label = cap_labels.get(capability.category, 'Provider')
    tier_reason = f"{need_label} → {cap_label}"

    # Determine tier
    combined_confidence = (need.confidence + capability.confidence) / 2

    if score >= 70 and combined_confidence >= 0.7:
        return 'strong', tier_reason

    if score >= 45 or (score >= 30 and combined_confidence >= 0.5):
        return 'good', tier_reason

    return 'open', tier_reason


# =============================================================================
# SCORING FUNCTIONS
# =============================================================================

def score_industry(demand_industry: Any, supply_industry: Any) -> float:
    """Score industry alignment"""
    if not demand_industry or not supply_industry:
        return 10

    d_raw = demand_industry[0] if isinstance(demand_industry, list) else demand_industry
    s_raw = supply_industry[0] if isinstance(supply_industry, list) else supply_industry

    d = to_string_safe(d_raw).lower()
    s = to_string_safe(s_raw).lower()

    # Exact match
    if d == s:
        return 30

    # Partial match
    if d in s or s in d:
        return 20

    # Related industries
    related_groups = [
        ['software', 'tech', 'technology', 'saas', 'it'],
        ['finance', 'fintech', 'banking', 'financial services'],
        ['healthcare', 'health', 'medical', 'biotech', 'pharma'],
        ['staffing', 'recruiting', 'hr', 'talent', 'human resources'],
        ['marketing', 'advertising', 'media', 'digital marketing'],
        ['sales', 'business development', 'revenue'],
    ]

    for group in related_groups:
        d_in_group = any(term in d for term in group)
        s_in_group = any(term in s for term in group)
        if d_in_group and s_in_group:
            return 15

    return 5


def score_signal(demand_signal: Any, supply_title: Any, supply_industry: Any) -> float:
    """Score signal relevance to supply"""
    if not demand_signal:
        return 5

    signal = to_string_safe(demand_signal).lower()
    title = to_string_safe(supply_title).lower()
    industry = to_string_safe(supply_industry).lower()

    # Signal type detection
    is_engineering = bool(re.search(r'engineer|developer|software|tech|cto', signal))
    is_sales = bool(re.search(r'sales|account|revenue|sdr|bdr', signal))
    is_marketing = bool(re.search(r'marketing|growth|brand|content', signal))
    is_recruiting = bool(re.search(r'recruiter|talent|hr|hiring', signal))
    is_finance = bool(re.search(r'finance|cfo|accounting|controller', signal))

    # Check if supply serves this signal type
    supply_serves_engineering = bool(re.search(r'engineer|developer|tech|software', title + industry))
    supply_serves_sales = bool(re.search(r'sales|revenue|business', title + industry))
    supply_serves_marketing = bool(re.search(r'marketing|growth|brand', title + industry))
    supply_serves_recruiting = bool(re.search(r'recruit|staffing|talent|hr', title + industry))
    supply_serves_finance = bool(re.search(r'finance|accounting|cfo', title + industry))

    # Match signal type to supply specialty
    if is_engineering and supply_serves_engineering:
        return 40
    if is_sales and supply_serves_sales:
        return 40
    if is_marketing and supply_serves_marketing:
        return 40
    if is_recruiting and supply_serves_recruiting:
        return 40
    if is_finance and supply_serves_finance:
        return 40

    # Partial match
    if supply_serves_recruiting:
        return 25

    return 10


def score_size(demand_size: Any, supply_size: Any) -> float:
    """Score size compatibility"""
    if not demand_size or not supply_size:
        return 10

    d_size_raw = demand_size[0] if isinstance(demand_size, list) else demand_size
    s_size_raw = supply_size[0] if isinstance(supply_size, list) else supply_size

    d_size = parse_size(d_size_raw)
    s_size = parse_size(s_size_raw)

    ratio = d_size / max(s_size, 1)

    if 0.5 <= ratio <= 5:
        return 20
    if 0.2 <= ratio <= 10:
        return 15
    return 5


def parse_size(size: Any) -> int:
    """Parse size to integer"""
    num_str = re.sub(r'[^0-9]', '', to_string_safe(size))
    try:
        return int(num_str) if num_str else 50
    except (ValueError, TypeError):
        return 50


# =============================================================================
# MAIN MATCHING FUNCTION
# =============================================================================

def score_match(demand: NormalizedRecord, supply: NormalizedRecord) -> Match:
    """
    Score a demand-supply pair.

    Returns Match object with score, reasons, tier, and profiles.
    """
    reasons = []

    # Step 1: Extract profiles
    need_profile = extract_need_from_demand(demand)
    capability_profile = extract_capability_from_supply(supply)

    # Step 2: Heuristic scoring
    industry_score = score_industry(demand.industry, supply.industry)
    if industry_score > 20:
        reasons.append('Industry match')

    signal_score = score_signal(demand.signal, supply.title, supply.industry)
    if signal_score > 25:
        reasons.append('Signal alignment')

    size_score = score_size(demand.size, supply.size)
    if size_score > 10:
        reasons.append('Size fit')

    # Step 3: Need-Capability alignment (THE CORE INTELLIGENCE)
    alignment_score = score_alignment(need_profile, capability_profile)
    if alignment_score >= 40:
        reasons.append(f"{need_profile.category} need → {capability_profile.category} capability")
    elif alignment_score >= 25:
        reasons.append('Cross-functional fit')

    # Step 4: Semantic overlap bonus (0-30 points)
    # Build combined text for semantic analysis
    demand_text = f"{demand.signal} {demand.title} {demand.company_description} {demand.industry}"
    supply_text = f"{supply.signal} {supply.title} {supply.company_description} {supply.industry}"

    semantic_result = get_semantic_score(demand_text, supply_text)
    semantic_bonus = semantic_result['bonus']

    if semantic_bonus >= 20:
        reasons.append(f"Strong keyword overlap ({semantic_result['overlapCount']} matches)")
    elif semantic_bonus >= 10:
        reasons.append(f"Keyword overlap ({semantic_result['overlapCount']} matches)")

    # Step 5: Calculate total score
    WEIGHTS = {
        'industry': 0.15,
        'signal': 0.15,
        'size': 0.10,
        'alignment': 0.50,
        'base': 0.10,
    }

    base_score = 10
    total_score = (
        (industry_score * WEIGHTS['industry']) +
        (signal_score * WEIGHTS['signal']) +
        (size_score * WEIGHTS['size']) +
        (alignment_score * WEIGHTS['alignment']) +
        (base_score * WEIGHTS['base']) +
        semantic_bonus  # ADDITIVE bonus (0-30 points)
    )

    total_score = min(100, round(total_score))  # Cap at 100

    # Step 6: Determine confidence tier
    tier, tier_reason = determine_tier(
        total_score,
        need_profile,
        capability_profile,
        demand.signal_meta.label if demand.signal_meta else None
    )

    # Ensure minimum score
    if total_score == 0:
        total_score = 1
        reasons.append('Exploratory match')

    return Match(
        demand=demand,
        supply=supply,
        score=total_score,
        reasons=reasons,
        tier=tier,
        tier_reason=tier_reason,
        need_profile=need_profile,
        capability_profile=capability_profile,
    )


def match_records(
    demand: List[NormalizedRecord],
    supply: List[NormalizedRecord],
    min_score: int = 0,
    best_match_only: bool = False,
    on_progress: Optional[callable] = None,
) -> MatchingResult:
    """
    Match demand records to supply records.

    Args:
        demand: List of demand records
        supply: List of supply records
        min_score: Minimum score threshold for matches (default: 0)
        best_match_only: If True, return only best match per demand (legacy mode)
                        If False, return ALL matches above threshold (default)
        on_progress: Optional callback(current, total) called after each demand row

    Returns:
        MatchingResult with demand_matches, supply_aggregates, and stats

    Note:
        - demand_matches: All matches above threshold (or best per demand if best_match_only=True)
        - supply_aggregates: Each supply with ALL their matches
    """
    all_matches = []

    # Score every demand-supply pair
    for i, d in enumerate(demand):
        for s in supply:
            match = score_match(d, s)
            if match.score >= min_score:  # Apply min_score during matching
                all_matches.append(match)
        if on_progress:
            on_progress(i + 1, len(demand))

    # Sort by score descending
    all_matches.sort(key=lambda m: m.score, reverse=True)

    # Filter matches based on mode
    if best_match_only:
        # Legacy mode: only best match per demand
        demand_matches = get_best_match_per_demand(all_matches)
    else:
        # New default: all matches above threshold
        demand_matches = all_matches

    # Aggregate matches per supply
    supply_aggregates = aggregate_by_supply(demand_matches)

    # Calculate stats
    scores = [m.score for m in all_matches]
    avg_score = round(sum(scores) / len(scores)) if scores else 0

    # Count unique demands matched
    unique_demands = len(set(get_demand_key(m.demand) for m in demand_matches))

    return MatchingResult(
        demand_matches=demand_matches,
        supply_aggregates=supply_aggregates,
        stats={
            'total_demand': len(demand),
            'total_supply': len(supply),
            'total_matches': len(demand_matches),
            'unique_demands_matched': unique_demands,
            'avg_score': avg_score,
        }
    )


# =============================================================================
# AGGREGATION FUNCTIONS
# =============================================================================

def get_demand_key(demand: NormalizedRecord) -> str:
    """Get stable demand record key"""
    if demand.record_key:
        return demand.record_key
    return demand.full_name or f"{demand.company}-{demand.title}"


def get_supply_key(supply: NormalizedRecord) -> str:
    """Get stable supply record key"""
    if supply.record_key:
        return supply.record_key
    return supply.domain or supply.full_name or f"{supply.company}-{supply.title}"


def get_best_match_per_demand(matches: List[Match]) -> List[Match]:
    """Get best match for each demand company"""
    seen = set()
    result = []

    for match in matches:
        key = get_demand_key(match.demand)
        if key not in seen:
            seen.add(key)
            result.append(match)

    return result


def aggregate_by_supply(matches: List[Match]) -> List[Dict[str, Any]]:
    """Aggregate all matches by supply"""
    by_supply = {}

    for match in matches:
        key = get_supply_key(match.supply)
        if key not in by_supply:
            by_supply[key] = []
        by_supply[key].append(match)

    aggregates = []

    for key, supplier_matches in by_supply.items():
        # Sort by score
        supplier_matches.sort(key=lambda m: m.score, reverse=True)

        # Count unique demand records
        unique_demand_keys = set(get_demand_key(m.demand) for m in supplier_matches)

        aggregates.append({
            'supply': supplier_matches[0].supply,
            'matches': supplier_matches,
            'best_match': supplier_matches[0],
            'total_matches': len(unique_demand_keys),
        })

    # Sort by total matches
    aggregates.sort(key=lambda a: a['total_matches'], reverse=True)

    return aggregates


def filter_by_score(result: MatchingResult, min_score: float) -> MatchingResult:
    """Filter matches by minimum score"""
    filtered_demand = [m for m in result.demand_matches if m.score >= min_score]

    filtered_aggregates = []
    for agg in result.supply_aggregates:
        filtered_matches = [m for m in agg['matches'] if m.score >= min_score]
        if filtered_matches:
            filtered_aggregates.append({
                **agg,
                'matches': filtered_matches,
                'best_match': filtered_matches[0],
                'total_matches': len(filtered_matches),
            })

    # Recalculate stats for filtered matches
    filtered_scores = [m.score for m in filtered_demand]
    avg_score = round(sum(filtered_scores) / len(filtered_scores)) if filtered_scores else 0
    unique_demands = len({m.demand.domain or m.demand.company_name for m in filtered_demand})

    return MatchingResult(
        demand_matches=filtered_demand,
        supply_aggregates=filtered_aggregates,
        stats={
            'total_demand': result.stats['total_demand'],
            'total_supply': result.stats['total_supply'],
            'total_matches': len(filtered_demand),
            'unique_demands_matched': unique_demands,
            'avg_score': avg_score,
        },
    )
