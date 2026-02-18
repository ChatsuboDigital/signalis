"""
Configuration Management

Loads configuration from environment variables and config files.
"""

import os
from typing import Optional, Literal
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Load .env file
load_dotenv()


def _get_default_output_dir() -> str:
    """Get default output directory from centralized config"""
    try:
        from core.config import get_config
        config = get_config()
        return str(config.get_output_dir('connector'))
    except Exception:
        # Fallback if centralized config not available
        return './output'


@dataclass
class ConnectorConfig:
    """Main configuration for Connector CLI"""

    # Enrichment API Keys
    apollo_api_key: Optional[str] = None
    anymail_api_key: Optional[str] = None
    ssm_api_key: Optional[str] = None

    # AI Configuration
    ai_provider: Literal['openai', 'anthropic', 'azure'] = 'openai'
    ai_api_key: Optional[str] = None
    ai_model: Optional[str] = None
    azure_endpoint: Optional[str] = None
    azure_deployment: Optional[str] = None
    openai_fallback_key: Optional[str] = None

    # Processing Options
    min_match_score: float = 30.0
    enable_enrichment: bool = True
    enable_ai_intros: bool = True
    max_concurrency: int = 5

    # Sending Options
    enable_sending: bool = False
    sending_provider: Literal['instantly', 'plusvibe'] = 'instantly'
    instantly_api_key: Optional[str] = None
    plusvibe_api_key: Optional[str] = None
    plusvibe_workspace_id: Optional[str] = None
    demand_campaign_id: Optional[str] = None
    supply_campaign_id: Optional[str] = None

    # Output Options
    output_format: Literal['csv', 'json', 'both'] = 'csv'
    output_dir: str = field(default_factory=_get_default_output_dir)

    @classmethod
    def from_env(cls) -> 'ConnectorConfig':
        """Load configuration from environment variables"""
        return cls(
            # Enrichment
            apollo_api_key=os.getenv('APOLLO_API_KEY'),
            anymail_api_key=os.getenv('ANYMAIL_API_KEY'),
            ssm_api_key=os.getenv('SSM_API_KEY'),

            # AI
            ai_provider=os.getenv('AI_PROVIDER', 'openai'),  # type: ignore
            ai_api_key=os.getenv('AI_API_KEY') or os.getenv('OPENAI_API_KEY') or os.getenv('ANTHROPIC_API_KEY'),
            ai_model=os.getenv('AI_MODEL'),
            azure_endpoint=os.getenv('AZURE_ENDPOINT'),
            azure_deployment=os.getenv('AZURE_DEPLOYMENT'),
            openai_fallback_key=os.getenv('OPENAI_FALLBACK_KEY'),

            # Processing
            min_match_score=float(os.getenv('MIN_MATCH_SCORE', '30')),
            enable_enrichment=os.getenv('ENABLE_ENRICHMENT', 'true').lower() == 'true',
            enable_ai_intros=os.getenv('ENABLE_AI_INTROS', 'true').lower() == 'true',
            max_concurrency=int(os.getenv('MAX_CONCURRENCY', '5')),

            # Sending
            enable_sending=os.getenv('ENABLE_SENDING', 'false').lower() == 'true',
            sending_provider=os.getenv('SENDING_PROVIDER', 'instantly'),  # type: ignore
            instantly_api_key=os.getenv('INSTANTLY_API_KEY'),
            plusvibe_api_key=os.getenv('PLUSVIBE_API_KEY'),
            plusvibe_workspace_id=os.getenv('PLUSVIBE_WORKSPACE_ID'),
            demand_campaign_id=os.getenv('DEMAND_CAMPAIGN_ID'),
            supply_campaign_id=os.getenv('SUPPLY_CAMPAIGN_ID'),

            # Output
            output_format=os.getenv('OUTPUT_FORMAT', 'csv'),  # type: ignore
            output_dir=os.getenv('OUTPUT_DIR') or _get_default_output_dir(),
        )

    def validate(self) -> None:
        """Validate configuration"""
        if self.enable_ai_intros and not self.ai_api_key:
            raise ValueError("AI API key required when AI intros are enabled")

        if self.ai_provider == 'azure' and not (self.azure_endpoint and self.azure_deployment):
            raise ValueError("Azure endpoint and deployment required for Azure provider")
