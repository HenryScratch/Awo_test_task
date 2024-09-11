import logging
import uvicorn
import argparse
from .api import app
from .log import configure_uvicorn_log_formatters, get_logger
from . import __version__


def parse_args() -> dict:
    parser = argparse.ArgumentParser(
        prog='routercli',
        description=f'router API v{__version__}',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        '--host',
        default='127.0.0.1',
        help='bind socket to this host',
    )
    parser.add_argument(
        '--port',
        default=8000,
        type=int,
        help='bind socket to this port',
    )
    parser.add_argument(
        '--log-level',
        default='info',
        choices=['critical', 'error', 'warning', 'info', 'debug'],
        help='logging level',
    )
    parser.add_argument(
        '-d', '--debug',
        action='store_true',
        help='debug mode',
    )
    args = parser.parse_args()
    return vars(args)

def main() -> None:
    args = parse_args()
    if args['debug']:
        app.state.debug = True
        log_level = 'debug'
    else:
        log_level = args['log_level']
    log_level = logging.getLevelNamesMapping()[log_level.upper()]
    logging.disable(log_level-10)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    configure_uvicorn_log_formatters()
    logger = get_logger(__name__)
    logger.info('running router...')
    logger.debug('debug mode is on')
    uvicorn.run(
        'router.api:app',
        host=args['host'],
        port=args['port'],
        log_level=log_level,
        reload=args['debug'],
        server_header=args['debug'],
    )


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        ...
