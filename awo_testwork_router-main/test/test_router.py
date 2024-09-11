#!/usr/bin/env python3.12
# test for router (localhost)

import re
import sys
import json
import time
import httpx
import asyncio
import logging
from pprint import pprint
from collections import Counter

ROUTER_HOST = 'http://127.0.0.1:8000'
AUTH_TOKEN = 'auth'
LOGIN = 'user'
NETWORK_TIMEOUT = 30.0
URL_RE = r'^/api/(wb|oz|seo|ym)'

STATUS_CODES = Counter()
XTIME = Counter()
RTIME = Counter()
ACCOUNTS = Counter()

async def run_producer(queue, log_path):
    def parse_jsonl_log(path):
        with open(path) as log:
            for line in log:
                try:
                    yield json.loads(line)
                except Exception as e:
                    logging.error(e)
                    continue
    logging.info(f'parsing {log_path}')
    for data in parse_jsonl_log(log_path):
        if data['method'] != 'GET':
            continue
        elif data['status'] != 200:
            continue
        elif not re.match(URL_RE, data['url']):
            continue
        url = ROUTER_HOST + data['url']
        await queue.put(url)

async def run_worker(queue):
    while True:
        url = await queue.get()
        logging.info(f'URL: {url}')
        headers = {
            'x-token': AUTH_TOKEN,
            'x-login': LOGIN,
        }
        start_time = time.monotonic()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    url,
                    headers=headers,
                    timeout=NETWORK_TIMEOUT,
                    follow_redirects=False,
                )
        except httpx.HTTPError as exc:
            logging.critical(exc)
            raise
        else:
            if resp.status_code in (901, 903):
                logging.critical(resp.status_code)
                raise Exception(resp.status_code)
            xtime = float(resp.headers['x-process-time'])
            XTIME[int(xtime)+1] += 1
            ACCOUNTS[resp.headers['x-account']] += 1
            STATUS_CODES[resp.status_code] += 1
            if resp.status_code != 200:
                logging.warning(f'status code: {resp.status_code}')
            else:
                logging.debug(f'body length: {len(resp.content)}')
        RTIME[int(time.monotonic()-start_time)+1] += 1

async def run_manager(concurrency, log_path):
    logging.info(f'running test with {concurrency} workers')
    queue = asyncio.Queue(concurrency*10)
    tasks = []
    tasks.append(asyncio.create_task(run_producer(queue, log_path)))
    for n in range(concurrency):
        tasks.append(asyncio.create_task(run_worker(queue)))
    print(await asyncio.gather(*tasks, return_exceptions=True))

def print_accounts():
    print()
    print('--- ACCOUNTS ON ROUTER---')
    pprint(httpx.get(
        ROUTER_HOST + '/router/accounts',
        headers={'x-token': AUTH_TOKEN},
    ).json())
    print()

def register_accounts(path):
    with open(path) as f:
        for line in f:
            try:
                account = json.loads(line)
            except Exception:
                continue
            if not account['email']:
                continue
            logging.info(
                f'registering account [{account["email"]}] with the router')
            resp = httpx.post(
                ROUTER_HOST + '/router/accounts',
                headers={'x-token': AUTH_TOKEN},
                json=account,
            )
            if resp.status_code // 100 != 2:
                logging.critical(resp.json())
                raise Exception(resp.status_code)

def print_stats():
    print()
    print('--- STATS ---')
    for v in ('ACCOUNTS', 'STATUS_CODES', 'XTIME', ):
        print()
        print(f'[{v}]')
        pprint(dict(globals()[v]))

if __name__ == '__main__':
    if len(sys.argv) not in (3, 4):
        print('usage: test_router.py CONCURRENCY LOG_PATH [ACCOUNTS_PATH]')
        sys.exit(1)
    logging.basicConfig(level=20)
    logging.getLogger('httpx').setLevel(30)
    concurrency, log_path = int(sys.argv[1]), sys.argv[2]
    if len(sys.argv) == 4:
        accounts_path = sys.argv[3]
        register_accounts(accounts_path)
    print_accounts()
    try:
        asyncio.run(run_manager(concurrency, log_path))
    except KeyboardInterrupt:
        ...
    finally:
        print_stats()
