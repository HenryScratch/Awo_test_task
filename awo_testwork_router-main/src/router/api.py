import pickle
import re
import asyncio

from enum import Enum
from time import monotonic
from collections import Counter
from urllib.parse import unquote
from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.responses import JSONResponse

from .task import Task
from .manager import Manager, ManagerError
from .cache import HTTPCache
from .models import Account, User
from .log import get_logger
from .config import API_CONFIG, DONOR_CONFIG

# monkeypatch
from uvicorn.protocols.http import httptools_impl as _httptools_impl
_httptools_impl.STATUS_LINE.update(
    (status_code, _httptools_impl._get_status_line(status_code))
    for status_code in range(900, 999)
)

PAYLOAD_SIZES = sorted([
    4096,
    32768,
    131072,
    1048576,
    DONOR_CONFIG['api_http_cache_size_threshold'],
    DONOR_CONFIG['api_http_cache_item_maxsize'],
])

UNLIMITED_USERS_REGEX = '|'.join(API_CONFIG['unlimited_users'])


app = FastAPI(openapi_url=None)
app.state.debug = False
app.logger = get_logger(__name__)

manager = Manager()

process_time_stats = Counter()
http_stats = {
    'codes': Counter(),
    'size_kb': Counter(),
}

http_cache = HTTPCache(
    maxsize=DONOR_CONFIG['api_http_cache_capacity'],
    ttl=DONOR_CONFIG['api_http_cache_default_ttl'],
)
http_cache_lookup_users = {}

users = {}


def _get_user(login: str) -> User:
    user = users.get(login)
    if not user:
        user = User(
            login=login,
            limits=dict(API_CONFIG['daily_limits_per_user']),
        )
        users[user.login] = user
    return user


async def read_http_cache(
    origin_request: Request,
    method: str,
    path: str,
    headers: dict,
    params: str,
    body: bytes,
) -> tuple[int, bytes, dict] | None:
    key = http_cache.make_request_key(
        method, path, headers, params, body)
    if (login := origin_request.headers.get('x-login')):
        http_cache_lookup_users.setdefault(key, set()).add(login)
    serialized_response = http_cache.get(key)
    if serialized_response is not None:
        response = pickle.loads(serialized_response)
        return response
    return None

async def write_http_cache(
    origin_request: Request,
    method: str,
    path: str,
    headers: dict,
    params: str,
    body: bytes,
    response: bytes,
    ttl: float | None = None,
) -> None:
    key = http_cache.make_request_key(
        method, path, headers, params, body)
    serialized_response = pickle.dumps(response)
    http_cache.set(key, serialized_response, ttl)


class CacheHeader(Enum):
    SKIP = 0
    USE = 1
    REPLACE = 2

def _make_response(
    status_code: int = 200,
    content: bytes | None = None,
    headers: dict | None = None,
) -> Response:
    if headers:
        for key, val in headers.items():
            if not isinstance(val, str):
                headers[key] = str(val)
    return Response(
        status_code=status_code,
        content=content,
        headers=headers,
    )

@app.exception_handler(404)
async def not_found(request, exc):
    return JSONResponse(
        status_code=904,
        content={'detail': 'not found'},
    )

@app.middleware('http')
async def add_process_time_header(request: Request, call_next):
    start_time = monotonic()
    response = await call_next(request)
    process_time = monotonic() - start_time
    process_time_stats[int(process_time)+1] += 1
    # app.logger.debug(f'{request} | x-process-time: {process_time:.4f}')
    response.headers['x-process-time'] = f'{process_time:.4f}'
    return response

async def x_token(request: Request):
    if request.headers.get('x-token') != API_CONFIG['auth_token']:
        raise HTTPException(901, 'invalid x-token')

async def x_headers(request: Request, response: Response):
    for header in ('x-login', 'x-admin'):
        if v := request.headers.get(header):
            response.headers[header] = v


@app.get('/router/ping', dependencies=[Depends(x_token)])
async def ping() -> str:
    return 'pong'


@app.get('/router/stats/service', dependencies=[Depends(x_token)])
async def get_service_stats() -> dict:
    return {
        'process_time': dict(process_time_stats.most_common()),
        'worker_waiting_time': dict(manager._worker_waiting_time.most_common()),
        'task_type': dict(manager._task_type.most_common()),
    }

@app.get('/router/stats/http', dependencies=[Depends(x_token)])
async def get_http_stats() -> dict:
    return {key: dict(http_stats[key].most_common()) for key in http_stats}


@app.get('/router/stats/users', dependencies=[Depends(x_token)])
async def get_users_stats(limit: int | None = None) -> list[dict]:
    stats = sorted(
        [
            {'login': user.login, 'usage_total': user.usage_total}
            for user in users.values()
        ],
        key=lambda _: _['usage_total'],
        reverse=True,
    )
    if limit is not None:
        return stats[:limit]
    else:
        return stats

@app.get('/router/stats/users/{login}', dependencies=[Depends(x_token)])
async def get_user_stats(login: str) -> dict:
    user = users.get(login)
    if not user:
        raise HTTPException(900, f'user not found: {login}')
    return {
        'login': user.login,
        'usage_total': user.usage_total,
    }

@app.get('/router/stats/cache', dependencies=[Depends(x_token)])
async def get_cache_stats() -> dict:
    return {
        'capacity': http_cache.capacity,
        'size': http_cache.size,
        'lookups': http_cache.lookups,
        'hits': http_cache.hits,
        'misses': http_cache.misses,
        'hitrate': http_cache.hitrate,
    }


@app.get('/router/cache/top{n}', dependencies=[Depends(x_token)])
async def get_cache_top(n: int) -> list[dict]:
    requests = http_cache.most_common_requests()
    for req in requests:
        req['params'] = unquote(req['params'])
        req['users'] = (
            len(http_cache_lookup_users[req['key']])
            if req['key'] in http_cache_lookup_users else 0
        )
    return sorted(
        requests,
        key=lambda _: (_['users'], _['lookups']),
        reverse=True,
    )[:abs(n)]

@app.delete('/router/cache',
            status_code=204, dependencies=[Depends(x_token)])
async def purge_cache() -> None:
    http_cache.purge()


@app.get('/router/users', dependencies=[Depends(x_token)])
async def get_users() -> list[User]:
    return users.values()

@app.get('/router/users/{login}', dependencies=[Depends(x_token)])
async def get_user(login: str) -> User:
    user = users.get(login)
    if not user:
        raise HTTPException(900, f'user not found: {login}')
    return user


@app.get('/router/accounts', dependencies=[Depends(x_token)])
async def get_accounts() -> list[Account]:
    return manager.get_all_accounts()

@app.get('/router/accounts/{email}', dependencies=[Depends(x_token)])
async def get_account(email: str) -> Account:
    try:
        return manager.get_account(email)
    except ManagerError as exc:
        raise HTTPException(900, str(exc))

@app.post('/router/accounts',
          status_code=204, dependencies=[Depends(x_token)])
async def add_account(account: Account) -> None:
    try:
        manager.add_account(account)
    except ManagerError as exc:
        raise HTTPException(900, str(exc))

@app.delete('/router/accounts/{email}',
            status_code=204, dependencies=[Depends(x_token)])
async def remove_account(email: str) -> None:
    try:
        manager.remove_account(email)
    except ManagerError as exc:
        raise HTTPException(900, str(exc))


@app.post('/router/reset', status_code=204, dependencies=[Depends(x_token)])
async def reset(
    remove_cache: bool = True,
    remove_accounts: bool = True,
) -> None:
    try:
        manager.logger.info('RESET')
        manager._worker_waiting_time.clear()
        manager._task_type.clear()
        users.clear()
        http_cache_lookup_users.clear()
        process_time_stats.clear()
        for stats in http_stats.values():
            stats.clear()
        if remove_cache:
            http_cache.purge()
        if remove_accounts:
            manager.remove_all_accounts()
        else:
            manager.reset_all_accounts()
    except ManagerError as exc:
        raise HTTPException(900, str(exc))

@app.post('/router/reset/accounts',
          status_code=204, dependencies=[Depends(x_token)])
async def reset_accounts() -> None:
    try:
        manager.reset_all_accounts()
    except ManagerError as exc:
        raise HTTPException(900, str(exc))

@app.post('/router/reset/accounts/{email}',
          status_code=204, dependencies=[Depends(x_token)])
async def reset_account(email: str) -> None:
    try:
        manager.reset_account(email)
    except ManagerError as exc:
        raise HTTPException(900, str(exc))

@app.post('/router/reset/users',
          status_code=204, dependencies=[Depends(x_token)])
async def reset_users() -> None:
    users.clear()


@app.api_route(
    '/api/{endpoint:path}',
    methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'],
    dependencies=[Depends(x_token), Depends(x_headers)],
)
async def route_all(request: Request, endpoint: str) -> Response:
    method = request.method
    path = f'/api/{endpoint}'
    headers = request.headers
    if DONOR_CONFIG.get('api_passthrough_headers'):
        passthrough_headers = {
            header: value for header, value in headers.items()
            if header in DONOR_CONFIG['api_passthrough_headers']
        }
    else:
        passthrough_headers = {}
    params = str(request.query_params)
    params_dict = dict(request.query_params)
    if method in ('PUT', 'POST', 'PATCH'):
        body = await request.body()
    else:
        body = b''
    admin = bool(headers.get('x-admin'))
    if admin and not headers.get('x-account'):
        raise HTTPException(
            900, 'invalid `x-admin` request (no `x-account` specified)')

    try:
        x_cache = CacheHeader(
            int(headers.get('x-cache', 0))
        )
        if admin and x_cache is not CacheHeader.SKIP:
            raise ValueError
    except ValueError:
        raise HTTPException(900, 'invalid `x-cache` header')

    if (
        not admin and
        DONOR_CONFIG['api_http_cache_enabled'] and
        x_cache is CacheHeader.USE and
        (
            cached_response := await read_http_cache(
                request,
                method,
                path,
                passthrough_headers,
                params,
                body,
            )
        ) is not None
    ):
        status_code, content, headers = cached_response
        return _make_response(
            status_code=status_code,
            content=content,
            headers={'x-cache': 1, **headers},
        )

    else:
        #try:
        #    manager.ensure_free_workers_available()
        #except ManagerError as exc:
        #    http_stats['codes'][903] += 1
        #    raise HTTPException(903, str(exc))

        if not admin and (login := headers.get('x-login')):
            user = _get_user(login)
            if (
                not re.match(UNLIMITED_USERS_REGEX, login) and
                user.limits_exceeded(path)
            ):
                raise HTTPException(929, 'daily limits exceeded')
        else:
            user = None

        task = Task(
            method=method,
            path=path,
            headers=passthrough_headers,
            params=params,
            params_dict=params_dict,
            content=body,
            account=headers.get('x-account'),
            group=headers.get('x-group'),
            login=headers.get('x-login'),
            admin=admin,
        )

        try:
            async with asyncio.timeout(API_CONFIG['task_timeout']):
                try:
                    await manager.add_task(task)
                except ManagerError as exc:
                    raise HTTPException(900, f'unable to process request: {exc}')
                else:
                    await task.wait()
        except TimeoutError:
            http_stats['codes'][905] += 1
            raise HTTPException(905, 'timeout')

        resp = task.result
        if not admin and resp:
            if user:
                user.inc_usage(path)
            http_stats['codes'][resp.status_code] += 1
            size_from = 0
            for size in PAYLOAD_SIZES:
                if len(resp.content) <= size:
                    http_stats['size_kb'][f'{size_from//1024}-{size//1024}'] += 1
                    break
                else:
                    size_from = size
            else:
                http_stats['size_kb'][f'{size//1024}++'] += 1
        elif not resp:
            http_stats['codes'][910] += 1

        if (
            not admin and
            DONOR_CONFIG['api_http_cache_enabled'] and
            x_cache in (CacheHeader.USE, CacheHeader.REPLACE) and
            not task.is_failed() and
            len(resp.content) <= DONOR_CONFIG['api_http_cache_item_maxsize']
        ):
            ttl = (
                DONOR_CONFIG['api_http_cache_short_ttl'] if
                len(resp.content) > DONOR_CONFIG['api_http_cache_size_threshold']
                else DONOR_CONFIG['api_http_cache_default_ttl']
            )
            # path before redirects
            await write_http_cache(
                request,
                method,
                path,
                passthrough_headers,
                params,
                body,
                (
                    resp.status_code,
                    resp.content,
                    dict(resp.headers)
                ),
                ttl,
            )

        return _make_response(
            status_code=resp.status_code if resp else 910,
            content=resp.content if resp else None,
            headers={
                'x-account': task.account,
                'x-cache': 0,
                **(resp.headers if resp else {})
            },
        )
