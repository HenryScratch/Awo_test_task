#!/usr/bin/env python3.12
# sync router with hub accounts

import sys
import json
import httpx
import logging
from time import sleep

DEBUG_MODE = False
AUTH_HEADER_NAME = 'x-token'
STATE_PARAMS = [
    'api_cooldown_param',
    'api_mode',
    'api_routing_rules',
    'api_token',
    'group',
]
STATE = {}

def api(
    method: str,
    url: str,
    auth_token: str,
    data: dict | None = None,
    network_timeout: float = 30.0,
) -> httpx.Response:
    resp = httpx.request(
        method,
        url,
        headers={AUTH_HEADER_NAME: auth_token},
        json=data,
        timeout=network_timeout,
    )
    resp.raise_for_status()
    return resp

def cast(acc: dict) -> dict:
    try:
        data = {
            'email': str(acc['email']),
            'api_token': str(acc['token']),
            'api_cooldown_param': (
                json.loads(a) if
                isinstance((a := acc.get('api_cooldown')), str)
                else a
            ),
            'api_routing_rules': ({'allow': acc['allow']}
                                  if 'allow' in acc else {}),
            'api_mode': acc.get('mode_api', 'drum').lower(),
            'cost': int(acc['cost']),
            'limits': acc.get('limits', {}),
            'proxy': {
                'type': str(acc['proxy']['protocol']),
                'host': str(acc['proxy']['ip']),
                'port': int(acc['proxy']['port']),
                'user': str(acc['proxy']['login_proxy']),
                'password': str(acc['proxy']['password_proxy']),
            }
        }
        if data['api_mode'] == 'cache':
            data['api_mode'] = 'drum'
            data['group'] = 'cache'
        elif acc.get('group'):
            data['group'] = acc['group']
        else:
            data['group'] = 'main'
        if data['api_cooldown_param'] is not None:
            data['api_cooldown_mode'] = 'interval'
        return data
    except Exception as exc:
        raise ValueError(f'broken account data structure: {exc}')

def reload_acc(
    router_endpoint: str,
    auth_token: str,
    acc: dict,
) -> None:
    api('DELETE', f'{router_endpoint}/{acc["email"]}', auth_token)
    sleep(5)
    api('POST', router_endpoint, auth_token, data=acc)
    logging.info(f'account is reloaded: {acc["email"]}')

def sync_forever(
    hub_endpoint: str,
    router_endpoint: str,
    auth_token: str,
    poll_interval: float,
    max_accounts: int,
) -> None:
    logging.info(
        f'start syncing accs from hub at `{hub_endpoint}` to router at `{router_endpoint}` '
        f'(interval: {poll_interval} seconds)...'
    )
    if not hub_endpoint.lower().startswith('http'):
        hub_endpoint = f'http://{hub_endpoint}'
    if not router_endpoint.lower().startswith('http'):
        router_endpoint = f'http://{router_endpoint}'
    while True:
        try:
            router_accs = {
                acc['email']: acc for acc in
                api('GET', router_endpoint, auth_token).json()
            }
            logging.debug(f'router accs: {", ".join(sorted(router_accs.keys()))}')
            hub_accs = {
                acc['email']: acc for acc in
                api('GET', hub_endpoint, auth_token).json()[:max_accounts]
            }
            logging.debug(f'hub accs: {", ".join(sorted(hub_accs.keys()))}')
            for acc in router_accs.values():
                try:
                    if acc['email'] not in hub_accs:
                        api('DELETE', f'{router_endpoint}/{acc["email"]}', auth_token)
                        logging.info(f'account is removed: {acc["email"]}')
                except Exception as exc:
                    logging.error(exc)
            for hub_acc in hub_accs.values():
                try:
                    acc = cast(hub_acc)
                    if acc['email'] in router_accs:
                        if acc['email'] not in STATE:
                            reload_acc(router_endpoint, auth_token, acc)
                        else:
                            for param in STATE_PARAMS:
                                if acc[param] != STATE[acc['email']][param]:
                                    reload_acc(router_endpoint, auth_token, acc)
                                    break
                    else:
                        api('POST', router_endpoint, auth_token, data=acc)
                        logging.info(f'account is loaded: {acc["email"]}')
                    STATE[acc['email']] = {param: acc[param] for param in STATE_PARAMS}
                except Exception as exc:
                    logging.error(exc)
        except Exception as exc:
            logging.error(exc)
        finally:
            sleep(poll_interval)

if __name__ == '__main__':
    logging.basicConfig(
        level=logging.DEBUG if DEBUG_MODE else logging.INFO,
        format='[%(asctime)s] [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S',
    )
    logging.getLogger('httpx').setLevel(30)
    if len(sys.argv) != 6:
        print('usage: syncaccs.py HUB_ENDPOINT ROUTER_ENDPOINT AUTH_TOKEN POLL_INTERVAL MAX_ACCOUNTS') 
        sys.exit(1)
    try:
        sync_forever(*sys.argv[1:-2], float(sys.argv[-2]), int(sys.argv[-1]))
    except KeyboardInterrupt:
        ...
