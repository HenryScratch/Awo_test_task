#!/usr/bin/env python3.12
# warm-up cache

import re
import sys
import json
import httpx
import logging
from collections import Counter
from datetime import datetime, timedelta


DEBUG_MODE = False
AUTH_HEADER_NAME = 'x-token'
ACCOUNTS_ENDPOINT = '/router/accounts'
CACHE_TOP_ENDPOINT = '/router/cache/top'
CACHE_TOP_MAX = 1000
X_CACHE_HEADER = '2'
X_GROUP_HEADER = 'cache'
RETRY_NUM = 10
RETRY_STATUS_CODES = [403, 429, 910]
DATE_FORMATS = ['%Y-%m-%d', '%Y/%m/%d', '%d%m%Y']
DATE_REGEX = r'\b(\d{4}-\d{2}-\d{2})\b|\b(\d{2}\d{2}\d{4})\b'
CURRENT_YEAR = datetime.now().year


def api(
    method: str,
    url: str,
    auth_token: str,
    headers: dict | None = None,
    params: str | None = None,
    data: str | None = None,
    network_timeout: float = 60.0,
    retries: int = 0,
) -> httpx.Response:
    if headers is None:
        headers = {}
    while True:
        try:
            return httpx.request(
                method,
                url,
                headers={
                    AUTH_HEADER_NAME: auth_token,
                    **headers
                },
                params=params,
                json=json.loads(data) if data else None,
                timeout=network_timeout,
            )
        except httpx.HTTPError:
            if retries > 0:
                retries -= 1
                continue
            else:
                raise


def shift_date(date: str, days: int = 1) -> str:
    for date_format in DATE_FORMATS:
        try:
            date_obj = datetime.strptime(date, date_format)
            if date_obj.year == CURRENT_YEAR:
                date_obj += timedelta(days=days)
                return date_obj.strftime(date_format)
        except ValueError:
            continue
    else:
        return date

def shift_dates_in_text(text: str) -> str:
    if not text:
        return text
    else:
        return re.sub(
            DATE_REGEX,
            lambda _: shift_date(_.group()),
            text,
        )


def warm_up_cache(
    router_host: str,
    auth_token: str,
    req_num: int,
    data: list | None = None,
) -> None:
    logging.info('warming up the cache...')

    if not router_host.lower().startswith('http'):
        router_host = f'http://{router_host}'
    router_host = router_host.strip('/')
    req_num = min(req_num, CACHE_TOP_MAX)

    if data is not None:
        data = data[:req_num]
        logging.info(f'loaded top-{len(data)} most popular requests from file')
    else:
        data = api(
            'GET',
            f'{router_host}{CACHE_TOP_ENDPOINT}{req_num}',
            auth_token,
            retries=5,
        ).json()
        logging.info(f'got top-{len(data)} most popular requests from cache')

    accs = [
        acc['email'] for acc in
        api(
            'GET',
            f'{router_host}{ACCOUNTS_ENDPOINT}',
            auth_token,
            retries=5,
        ).json()
        if acc['group'] == X_GROUP_HEADER and not acc['banned']
    ]
    logging.info(f'{len(accs)} accounts are ready for work: {accs}')

    counter = Counter()
    for n, req in enumerate(data):
        logging.info(f'#{n} warming "{req["method"]} {req["path"]} {req["params"]}" endpoint')
        counter['tasks'] += 1

        try:
            retries = RETRY_NUM
            while True:
                resp = api(
                    req['method'],
                    f'{router_host}{req["path"]}',
                    auth_token,
                    {
                        'x-group': X_GROUP_HEADER,
                        'x-login': X_GROUP_HEADER,
                        'x-cache': X_CACHE_HEADER,
                        **req['headers']
                    },
                    shift_dates_in_text(req['params']),
                    shift_dates_in_text(req['body']),
                    retries=1,
                )
                if resp.status_code in RETRY_STATUS_CODES and retries > 0:
                    counter['retries'] += 1
                    retries -= 1
                    continue
                else:
                    resp.raise_for_status()
                    break
        except httpx.HTTPError as exc:
            counter['failed'] += 1
            logging.error(f'failed on {req["method"]} {req["path"]}: {exc}')
        else:
            counter['done'] += 1

    print(f'results: {dict(counter)}')
    logging.info('all done')


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.DEBUG if DEBUG_MODE else logging.INFO,
        format='[%(asctime)s] [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S',
    )
    logging.getLogger('httpx').setLevel(30)
    if len(sys.argv) not in (4, 5):
        print('usage: cachewarmup.py ROUTER_HOST AUTH_TOKEN REQ_NUM [STATS_FILE]')
        sys.exit(1)
    router_host, auth_token, req_num = *sys.argv[1:3], int(sys.argv[3])
    if len(sys.argv) == 4:
        data = None
    else:
        with open(sys.argv[-1]) as f:
            data = json.load(f)
        if not data:
            print('no data')
            sys.exit(1)
    try:
        warm_up_cache(router_host, auth_token, req_num, data=data)
    except KeyboardInterrupt:
        ...
