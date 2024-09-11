#!/usr/bin/env python3
# parse custom NGINX log into structured JSON excluding unused fields

# NGINX LOG FORMAT:
# 1. client IP address
# 2. time of the request
# 3. request method
# 4. requested URL
# 5. HTTP version
# 6. HTTP status code
# 7. size of the response sent to the client
# 8. referrer URL
# 9. user agent string
# 10. @1
# 11. backend
# 12. login

import re
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import Generator
from urllib.parse import urlparse, parse_qsl

NGINX_LOG_RE = (
    r'(?P<ip>(?:\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|(?:[a-f0-9]{0,4}:){1,7}[a-f0-9]{1,4})) - - '
    r'\[(?P<datetime>\d{2}\/[a-z]{3}\/\d{4}:\d{2}:\d{2}:\d{2} (\+|\-)\d{4})\] '
    r'"(?P<method>HEAD|GET|POST|PUT|PATCH|DELETE|OPTIONS) (?P<url>.+?) HTTP\/(?:1\.1|2\.0)" '
    r'(?P<status>\d{3}) '
    r'(?P<size>\d+) '
    r'"(?P<referrer>[-]|.+?)" '
    r'"(?P<useragent>.+?)" '
    r'"(?P<ip2>(?:\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|(?:[a-f0-9]{0,4}:){1,7}[a-f0-9]{1,4}))" '
    r'backend="(?P<backend>.+?)" '
    r'login="(?P<login>.+?)" '
)
NGINX_DATETIME_FORMAT = '%d/%b/%Y:%H:%M:%S %z'

class ParserError(Exception): ...

def parse_args() -> dict:
    parser = argparse.ArgumentParser(description='NGINX to JSONL log parser')
    parser.add_argument('nginx_log', help='input file path')
    parser.add_argument('jsonl_log', nargs='?', help='output file path')
    parser.add_argument('-s', '--strict', action='store_true', help='do not ignore errors')
    args = parser.parse_args()
    return vars(args)

def parse_nginx_log(
    path: str,
    strict: bool = False,
    exclude_fields: tuple = ('useragent', 'ip2'),
) -> Generator[dict, None, None]:

    def parse(line: str) -> dict | None:
        res = re.match(NGINX_LOG_RE, line, re.I)
        if not res:
            return None
        doc = res.groupdict()
        if doc['status'] != '200':
            return None
        if doc['ip'] != doc['ip2']:
            raise ParserError('IP address mismatch')
        url = urlparse(doc['url'])
        doc['path'] = url.path
        doc['query'] = url.query
        doc['query_list'] = sorted(parse_qsl(url.query))
        for key in ('useragent', 'referrer'):
            if doc[key] == '-':
                doc[key] = ''
        for key in ('status', 'size'):
            doc[key] = int(doc[key])
        try:
            dt = datetime.strptime(doc['datetime'], NGINX_DATETIME_FORMAT)
        except ValueError as e:
            raise ParserError(e)
        doc['datetime'] = dt.isoformat()
        for key in exclude_fields:
            doc.pop(key)
        return doc

    errors = 0
    with open(path) as log:
        for n, line in enumerate(log):
            doc = parse(line)
            if not doc:
                errors += 1
                if not strict:
                    continue
                else:
                    raise ParserError(f'Failed to parse line: {n}')
            yield doc
    print(f'Failed to parse {errors} lines')

def main() -> None:
    args = parse_args()
    nginx_log_path = Path(args['nginx_log'])
    if not nginx_log_path.exists():
        raise IOError('Nginx log not found')
    if args['jsonl_log']:
        jsonl_log_path = Path(args['jsonl_log'])
    else:
        jsonl_log_path = nginx_log_path.parent / (nginx_log_path.name + '.jsonl')
    if jsonl_log_path.exists():
        print(f'JSONL log file exists: {jsonl_log_path}')
        if input('Overwrite? [y/n]: ').lower().strip() not in ('y', 'yes'):
            return
    print(f'Writing log into: {jsonl_log_path}')
    with open(jsonl_log_path, 'w') as jsonl_log:
        try:
            for n, doc in enumerate(parse_nginx_log(nginx_log_path, args['strict'])):
                if n and not n % (10 ** 5):
                    print(f'{n} lines processed...')
                jsonl_log.write(json.dumps(doc) + '\n')
        except ParserError as e:
            print(f'[ERROR] {e}')
            sys.exit(1)
    print('Done')

if __name__ == '__main__':
    main()
