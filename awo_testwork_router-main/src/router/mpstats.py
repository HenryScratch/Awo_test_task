import asyncio
from .client import AsyncAPIClient
from .worker import AsyncWorker
from .config import DONOR_CONFIG
from .models import APICooldownParam, APICooldownMode

class MPStatsAPIClient(AsyncAPIClient):

    network_timeout: float = DONOR_CONFIG['network_timeout']
    network_retries: int = DONOR_CONFIG['network_retries']
    api_domain: str = DONOR_CONFIG['api_domain']
    api_token_header_name: str = DONOR_CONFIG['api_token_header_name']
    api_token_env_name: str = DONOR_CONFIG['api_token_env_name']
    api_passthrough_headers: list[str] = DONOR_CONFIG['api_passthrough_headers']
    api_default_headers: dict[str, str] = DONOR_CONFIG['api_default_headers']

class MPStatsWorker(AsyncWorker):

    api_cooldown_param: APICooldownParam = DONOR_CONFIG['api_cooldown_param']
    api_cooldown_mode: APICooldownMode = APICooldownMode(DONOR_CONFIG['api_cooldown_mode'])
    banned_status_codes: list[int] = DONOR_CONFIG['banned_status_codes']
    freeze_status_codes: list[int] = DONOR_CONFIG['freeze_status_codes']
    retry_after_header: str = DONOR_CONFIG['retry_after_header']
    retry_after_max_time: float = DONOR_CONFIG['retry_after_max_time']
    freeze_time_initial: float = DONOR_CONFIG['freeze_time_initial']
    freeze_time_max: float = DONOR_CONFIG['freeze_time_max']
    freeze_time_factor: float = DONOR_CONFIG['freeze_time_factor']
    _api_client_cls: type[AsyncAPIClient] = MPStatsAPIClient
