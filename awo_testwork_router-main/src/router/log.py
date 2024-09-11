import sys
import logging
import asyncio
import functools
from .utils import memoize
from .config import LOGGING_CONFIG


def log_on_error(level):

    def decorator(method):
        @functools.wraps(method)
        def wrapper(self, *args, **kwargs):
            try:
                return method(self, *args, **kwargs)
            except Exception as exc:
                self.logger.log(level, exc)
                raise

        @functools.wraps(method)
        async def async_wrapper(self, *args, **kwargs):
            try:
                return await method(self, *args, **kwargs)
            except Exception as exc:
                self.logger.log(level, exc)
                raise

        if asyncio.iscoroutinefunction(method):
            return async_wrapper
        else:
            return wrapper

    return decorator


@memoize
def get_logger(name: str | None = None) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(stream=sys.stderr)
    formatter = logging.Formatter(**LOGGING_CONFIG['app']['default'])
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


def configure_uvicorn_log_formatters() -> None:
    from uvicorn.config import LOGGING_CONFIG as UVICORN_LOGGING_CONFIG
    formatters = UVICORN_LOGGING_CONFIG['formatters']
    formatters['default'].update(LOGGING_CONFIG['uvicorn']['default'])
    formatters['access'].update(LOGGING_CONFIG['uvicorn']['access'])
