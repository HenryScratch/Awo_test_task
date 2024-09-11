import httpx
from enum import Flag
from .utils import get_env_var
from .models import Proxy, ProxyStatus
from .log import get_logger


class APITokenLocation(Flag):
    HEADER = 1

class APIClientError(Exception): ...

class AsyncAPIClient:

    network_timeout: float = 20.0
    network_retries: int = 0
    api_scheme: str = 'https'
    api_domain: str | None = None
    api_token_header_name: str | None = None
    api_token_env_name: str | None = None
    api_token_location: APITokenLocation = APITokenLocation.HEADER
    api_passthrough_headers: list[str] | None = None
    api_default_headers: dict[str, str] | None = None
    _exc_cls: type[Exception] = APIClientError

    def __init__(
        self,
        *,
        api_token: str | None = None,
        proxy: Proxy | None = None,
    ) -> None:
        if api_token is None and self.api_token_env_name:
            api_token = get_env_var(self.api_token_env_name)
        self.api_token = api_token
        self.proxy = proxy
        self.logger = get_logger(self.__class__.__name__)

    async def request(
        self,
        method: str = 'GET',
        path: str | None = None,
        *,
        api_auth: bool = False,
        headers: dict | None = None,
        params: str | dict | None = None,
        content: bytes | None = None,
        json_data: dict | list | None = None,
        network_timeout: float | None = None,
        network_retries: int | None = None,
        follow_redirects: bool = True,
    ) -> httpx.Response:
        assert self.api_domain
        if path:
            url = f'{self.api_scheme}://{self.api_domain}/{path.lstrip("/")}'
        else:
            url = f'{self.api_scheme}://{self.api_domain}'

        _headers = (
            dict(self.api_default_headers) if
            self.api_default_headers else {}
        )
        if headers is not None:
            for header, value in headers.items():
                header = header.lower()
                if (
                    self.api_passthrough_headers is not None and
                    header not in self.api_passthrough_headers
                ):
                    self.logger.debug(f'Skip non-passthrough header: {header}')
                else:
                    _headers[header] = value

        if api_auth and self.api_token:
            if self.api_token_location is APITokenLocation.HEADER:
                if self.api_token_header_name:
                    _headers[self.api_token_header_name] = self.api_token

        timeout = (network_timeout if network_timeout is not None
                   else self.network_timeout)
        assert timeout > 0
        retries = (network_retries if network_retries is not None
                   else self.network_retries)
        assert retries >= 0

        self.logger.debug(f'API request {method}: {url} {params=} {json_data=}')
        self._update_proxy_status(ProxyStatus.UNKNOWN)

        try:
            while True:
                try:
                    async with httpx.AsyncClient(
                        proxy=self.proxy.url if self.proxy else None,
                        verify=False,
                    ).stream(
                        method,
                        url,
                        headers=_headers,
                        params=params,
                        content=content,
                        json=json_data,
                        timeout=timeout,
                        follow_redirects=follow_redirects,
                    ) as resp:
                        resp._content = b''
                        async for chunk in resp.aiter_raw(): # chunk size
                            resp._content += chunk
                except (httpx.ConnectError, httpx.ConnectTimeout):
                    if retries:
                        retries -= 1
                        self.logger.debug(
                            f'Retrying API request, {retries = } left')
                    else:
                        raise
                else:
                    break

            self.logger.debug(f'API request headers: {resp.request.headers}')
            self.logger.debug(f'API response status code: {resp.status_code}, '
                              f'redirects: {resp.history}')
            self.logger.debug(f'API response headers: {resp.headers}')

            resp.headers.pop('transfer-encoding', None) # ?
            self._update_proxy_status(ProxyStatus.ALIVE)
            return resp

        except httpx.HTTPError as exc:
            self._update_proxy_status(ProxyStatus.DEAD)
            raise self._exc_cls(
                f'API request failed {method}: {exc.request.url} (910)'
            ) from exc

    def _update_proxy_status(self, status: ProxyStatus) -> None:
        if self.proxy:
            self.proxy.status = status
