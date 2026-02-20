"""
Sender adapters for email campaign platforms (Instantly, Plusvibe).
Port of connector-os/src/services/senders/
"""

import time
import requests
from typing import Protocol, Literal, Optional, Dict, Any, List
from dataclasses import dataclass
from abc import abstractmethod


# Types
SenderId = Literal['instantly', 'plusvibe']
SendType = Literal['DEMAND', 'SUPPLY']
SendStatus = Literal['new', 'existing', 'needs_attention']


@dataclass
class SenderConfig:
    """Configuration for a sender provider."""
    api_key: str
    demand_campaign_id: Optional[str] = None
    supply_campaign_id: Optional[str] = None
    workspace_id: Optional[str] = None  # Plusvibe only


@dataclass
class SendLeadParams:
    """Parameters for sending a lead to a campaign."""
    type: SendType
    campaign_id: str
    email: str
    first_name: str
    last_name: str
    company_name: str
    company_domain: str
    intro_text: str
    contact_title: Optional[str] = None
    signal_metadata: Optional[Dict[str, Any]] = None


@dataclass
class SendResult:
    """Result of sending a lead."""
    success: bool
    lead_id: Optional[str] = None
    status: SendStatus = 'needs_attention'
    detail: Optional[str] = None
    is_rate_limited: bool = False  # True when provider returned 429


class SenderAdapter(Protocol):
    """Protocol for sender adapters."""

    @property
    @abstractmethod
    def id(self) -> SenderId:
        """Sender ID."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name."""
        ...

    @abstractmethod
    def validate_config(self, config: SenderConfig) -> Optional[str]:
        """
        Validate configuration. Returns error message if invalid, None if valid.
        """
        ...

    @abstractmethod
    def send_lead(self, config: SenderConfig, params: SendLeadParams) -> SendResult:
        """Send a lead to the campaign."""
        ...

    @abstractmethod
    def supports_campaigns(self) -> bool:
        """Whether this sender supports campaigns."""
        ...


class InstantlySender:
    """Instantly.ai sender implementation."""

    @property
    def id(self) -> SenderId:
        return 'instantly'

    @property
    def name(self) -> str:
        return 'Instantly'

    def validate_config(self, config: SenderConfig) -> Optional[str]:
        """Validate Instantly config."""
        if not config.api_key:
            return "Instantly API key is required"

        if not config.demand_campaign_id and not config.supply_campaign_id:
            return "At least one campaign ID (demand or supply) is required"

        # Validate campaign ID format (UUID v4)
        import re
        uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'

        if config.demand_campaign_id and not re.match(uuid_pattern, config.demand_campaign_id, re.IGNORECASE):
            return "Invalid demand campaign ID format (must be UUID v4)"

        if config.supply_campaign_id and not re.match(uuid_pattern, config.supply_campaign_id, re.IGNORECASE):
            return "Invalid supply campaign ID format (must be UUID v4)"

        return None

    def send_lead(self, config: SenderConfig, params: SendLeadParams) -> SendResult:
        """Send a lead to Instantly."""
        try:
            # Build payload
            payload = {
                "campaign": params.campaign_id,
                "email": params.email,
                "first_name": params.first_name,
                "last_name": params.last_name,
                "company_name": params.company_name,
                "website": params.company_domain,
                "personalization": params.intro_text,
                "skip_if_in_workspace": True,
                "skip_if_in_campaign": True,
                "skip_if_in_list": True,
                "custom_variables": {
                    "send_type": params.type,
                }
            }

            # Add signal metadata if present
            if params.signal_metadata:
                import json
                payload["custom_variables"]["signal_metadata"] = json.dumps(params.signal_metadata)

            # Make API request
            headers = {
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json"
            }

            response = requests.post(
                "https://api.instantly.ai/api/v2/leads",
                json=payload,
                headers=headers,
                timeout=30
            )

            response.raise_for_status()
            data = response.json()

            # Parse response
            # Instantly returns: { status: 1 (new) or 2 (existing), id: "..." }
            if data.get('status') == 1:
                return SendResult(
                    success=True,
                    lead_id=data.get('id'),
                    status='new',
                    detail='Lead added to campaign'
                )
            elif data.get('status') == 2:
                return SendResult(
                    success=True,
                    lead_id=data.get('id'),
                    status='existing',
                    detail='Lead already in workspace'
                )
            else:
                return SendResult(
                    success=False,
                    status='needs_attention',
                    detail=f"Unexpected status: {data.get('status')}"
                )

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                return SendResult(
                    success=False,
                    status='needs_attention',
                    detail='Rate limited (429) — will retry',
                    is_rate_limited=True
                )
            return SendResult(
                success=False,
                status='needs_attention',
                detail=f"HTTP error: {e.response.status_code} - {e.response.text}"
            )
        except Exception as e:
            return SendResult(
                success=False,
                status='needs_attention',
                detail=f"Error: {str(e)}"
            )

    def supports_campaigns(self) -> bool:
        return True


class PlusvibeSender:
    """Plusvibe sender implementation."""

    @property
    def id(self) -> SenderId:
        return 'plusvibe'

    @property
    def name(self) -> str:
        return 'Plusvibe'

    def validate_config(self, config: SenderConfig) -> Optional[str]:
        """Validate Plusvibe config."""
        if not config.api_key:
            return (
                "Plusvibe API key is required\n"
                "Add to .env: PLUSVIBE_API_KEY=your_key"
            )

        if not config.workspace_id:
            return (
                "Plusvibe workspace ID is required\n"
                "Add to .env: PLUSVIBE_WORKSPACE_ID=your_workspace_id"
            )

        if not config.demand_campaign_id and not config.supply_campaign_id:
            return (
                "At least one campaign ID is required\n"
                "Add to .env:\n"
                "  DEMAND_CAMPAIGN_ID=campaign_id (for demand contacts)\n"
                "  SUPPLY_CAMPAIGN_ID=campaign_id (for supply contacts)"
            )

        return None

    def send_lead(self, config: SenderConfig, params: SendLeadParams) -> SendResult:
        """Send a lead to Plusvibe."""
        try:
            # Build lead object
            lead = {
                "email": params.email,
                "first_name": params.first_name,
                "last_name": params.last_name,
                "company_name": params.company_name,
                "company_website": params.company_domain,
                "custom_variables": {
                    "personalization": params.intro_text,
                    "send_type": params.type,
                }
            }

            # Add contact title if present
            if params.contact_title:
                lead["custom_variables"]["contact_title"] = params.contact_title

            # Build payload
            payload = {
                "workspace_id": config.workspace_id,
                "campaign_id": params.campaign_id,
                "skip_if_in_workspace": True,
                "skip_lead_in_active_pause_camp": True,
                "leads": [lead]
            }

            # Make API request
            headers = {
                "x-api-key": config.api_key,
                "Content-Type": "application/json"
            }

            response = requests.post(
                "https://api.plusvibe.ai/api/v1/lead/add",
                json=payload,
                headers=headers,
                timeout=30
            )

            response.raise_for_status()
            data = response.json()

            # Parse Plusvibe API response (actual format from API)
            # Response: {
            #   status: 'success' | 'error',
            #   leads_uploaded: number,      // New leads added
            #   skipped: number,             // Already in workspace/campaign
            #   invalid_email_count: number,
            #   ... other fields
            # }

            if data.get('status') != 'success':
                return SendResult(
                    success=False,
                    status='needs_attention',
                    detail=f"Plusvibe error: {data.get('message', 'Unknown error')}"
                )

            # Check result counts
            leads_uploaded = data.get('leads_uploaded', 0)
            skipped = data.get('skipped', 0)
            invalid = data.get('invalid_email_count', 0)

            # Status is 'success' at this point (non-success returned early above)
            if leads_uploaded > 0:
                return SendResult(
                    success=True,
                    status='new',
                    detail=f"Added {leads_uploaded} new lead(s)"
                )
            elif invalid > 0:
                return SendResult(
                    success=False,
                    status='needs_attention',
                    detail=f"Invalid email: {data.get('invalid_email_message', 'Check format')}"
                )
            elif skipped > 0:
                return SendResult(
                    success=True,
                    status='existing',
                    detail=f"Lead already exists ({skipped} skipped)"
                )
            else:
                # Success but zero results - lead may already be in workspace
                return SendResult(
                    success=True,
                    status='existing',
                    detail="Lead already in workspace"
                )

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                return SendResult(
                    success=False,
                    status='needs_attention',
                    detail='Rate limited (429) — will retry',
                    is_rate_limited=True
                )
            return SendResult(
                success=False,
                status='needs_attention',
                detail=f"HTTP error: {e.response.status_code} - {e.response.text}"
            )
        except Exception as e:
            return SendResult(
                success=False,
                status='needs_attention',
                detail=f"Error: {str(e)}"
            )

    def supports_campaigns(self) -> bool:
        return True


# Sender registry
_SENDERS: Dict[SenderId, SenderAdapter] = {
    'instantly': InstantlySender(),
    'plusvibe': PlusvibeSender(),
}


def resolve_sender(sender_id: SenderId) -> SenderAdapter:
    """Resolve sender by ID."""
    sender = _SENDERS.get(sender_id)
    if not sender:
        raise ValueError(f"Unknown sender: {sender_id}")
    return sender


def build_sender_config(
    sending_provider: SenderId,
    instantly_api_key: Optional[str] = None,
    plusvibe_api_key: Optional[str] = None,
    plusvibe_workspace_id: Optional[str] = None,
    demand_campaign_id: Optional[str] = None,
    supply_campaign_id: Optional[str] = None,
) -> SenderConfig:
    """Build sender config from settings."""
    if sending_provider == 'instantly':
        return SenderConfig(
            api_key=instantly_api_key if instantly_api_key else None,
            demand_campaign_id=demand_campaign_id if demand_campaign_id else None,
            supply_campaign_id=supply_campaign_id if supply_campaign_id else None,
        )
    elif sending_provider == 'plusvibe':
        return SenderConfig(
            api_key=plusvibe_api_key if plusvibe_api_key else None,
            workspace_id=plusvibe_workspace_id if plusvibe_workspace_id else None,
            demand_campaign_id=demand_campaign_id if demand_campaign_id else None,
            supply_campaign_id=supply_campaign_id if supply_campaign_id else None,
        )
    else:
        raise ValueError(f"Unknown sender: {sending_provider}")


# Simple rate limiter (basic implementation)
class SimpleRateLimiter:
    """Simple rate limiter using token bucket algorithm."""

    def __init__(self, tokens_per_second: float, max_concurrent: int = 5):
        self.tokens_per_second = tokens_per_second
        self.max_concurrent = max_concurrent
        self.tokens = 0.0
        self.last_update = time.time()
        self.in_flight = 0

    def wait_for_token(self):
        """Wait until a token is available."""
        while True:
            # Refill tokens
            now = time.time()
            elapsed = now - self.last_update
            self.tokens = min(self.tokens + elapsed * self.tokens_per_second, self.tokens_per_second * 10)
            self.last_update = now

            # Check if we can proceed
            if self.tokens >= 1.0 and self.in_flight < self.max_concurrent:
                self.tokens -= 1.0
                self.in_flight += 1
                break

            # Wait a bit
            time.sleep(0.1)

    def release(self):
        """Release a concurrent slot."""
        self.in_flight = max(0, self.in_flight - 1)

    def drain(self):
        """
        Drain the token bucket to zero.

        Called on 429 response — forces all subsequent requests to wait
        for the bucket to refill before proceeding, mirroring the
        connector-os bucket.pause() behaviour.
        """
        self.tokens = 0.0
        self.last_update = time.time()


# Limiter instances
_limiters: Dict[SenderId, SimpleRateLimiter] = {
    'instantly': SimpleRateLimiter(tokens_per_second=8, max_concurrent=4),
    'plusvibe': SimpleRateLimiter(tokens_per_second=5, max_concurrent=2),
}


def get_limiter(sender_id: SenderId) -> SimpleRateLimiter:
    """Get rate limiter for a sender."""
    return _limiters[sender_id]
