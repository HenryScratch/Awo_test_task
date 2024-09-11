import re
import asyncio
from time import time
from collections import Counter
from collections.abc import Iterator

from .client import AsyncAPIClient, APIClientError
from .models import WorkerState, Account, APICooldownParam, APICooldownMode
# from .queue import CostBasedPriorityItem
from .log import get_logger


class WorkerError(Exception): ...
class RoutingError(WorkerError): ...
class LimitsError(WorkerError): ...


class AsyncWorker:

    api_cooldown_param: APICooldownParam = 0.0
    api_cooldown_mode: APICooldownMode = APICooldownMode.INTERVAL
    banned_status_codes: list[int] = []
    freeze_status_codes: list[int] = []
    retry_after_header: str | None = None
    retry_after_max_time: float | None = None
    freeze_time_initial: float = 0.0
    freeze_time_max: float = 0.0
    freeze_time_factor: float = 0.0
    _api_client_cls: type[AsyncAPIClient] | None = None
    
    

    def __init__(
        self,
        account: Account,
        manager
        # workers_queue: asyncio.PriorityQueue | None = None,
    ) -> None:
        self._account = account
        self._manager = manager
        self._cooldown_event = asyncio.Event()
        self._cooldown_event.set()
        self._semaphore = asyncio.Semaphore(2)
        
        # self.workers_queue = workers_queue
        self.task_queue = asyncio.PriorityQueue()
        if account.api_cooldown_param is None:
            assert account.api_cooldown_mode is None
            account.api_cooldown_param = self.api_cooldown_param
            account.api_cooldown_mode = self.api_cooldown_mode
        else:
            assert account.api_cooldown_mode is not None
            self.api_cooldown_param = account.api_cooldown_param
            self.api_cooldown_mode = account.api_cooldown_mode
        self.api_client = self._api_client_cls(
            api_token=account.api_token,
            proxy=account.proxy,
        )
        self._req_timestamps = []
        self._free = asyncio.Event()
        self._corotask = None
        self.logger = get_logger(
            f'{self.__class__.__name__}:{self._account.email}')
        self.update_state(WorkerState.IDLE)

    @property
    def uid(self) -> str:
        return self.account.uid

    @property
    def account(self) -> Account:
        return self._account

    @property
    def state(self) -> WorkerState:
        return self._state

    def update_state(self, state: WorkerState) -> None:
        self._state = self._account.worker_state = state

    def is_alive(self) -> bool:
        return self._state in (
            WorkerState.WAITING,
            WorkerState.RUNNING,
            WorkerState.COOLDOWN,
            WorkerState.FROZEN,
        )

    def is_running(self) -> bool:
        return self._state in (
            WorkerState.WAITING,
            WorkerState.RUNNING,
            WorkerState.COOLDOWN,
        )

    def is_frozen(self) -> bool:
        return self._state is WorkerState.FROZEN

    def is_free(self) -> bool:
        return self._free.is_set()

    def _interval_cooldown_generator(self) -> Iterator[float]:
        if isinstance(self.api_cooldown_param, list):
            for i in self.api_cooldown_param:
                if isinstance(i, (list, tuple)):
                    n, i = i
                    for _ in range(n):
                        yield i
                else:
                    yield i
        else:
            yield self.api_cooldown_param

    def _interval_cooldown_cycle(self) -> Iterator[float]:
        while True:
            yield from self._interval_cooldown_generator()

    def _get_interval_cooldown(self) -> float:
        if not hasattr(self, '_interval_cooldown'):
            self._interval_cooldown_window = sum(self._interval_cooldown_generator())
            self._interval_cooldown = self._interval_cooldown_cycle()
        elif (
            self._req_timestamps and
            (time() - self._req_timestamps[-1]) > self._interval_cooldown_window
        ):
            # reset cooldown cycle
            self._interval_cooldown = self._interval_cooldown_cycle()
        return next(self._interval_cooldown)

    def _get_window_cooldown(self) -> float:
        window_size, period = self.api_cooldown_param
        window_num, window_req = 1, 0
        since = time()
        for timestamp in reversed(self._req_timestamps):
            if timestamp < (since - (window_num * window_size)):
                if window_req <= 1:
                    break
                else:
                    window_num += 1
                    window_req = 1
            else:
                window_req += 1
            if timestamp < (since - period):
                break
        if window_req <= 1 or window_num < (period / window_size):
            return 0.0
        else:
            return window_size

    def get_api_cooldown(self) -> float:
        if self.api_cooldown_mode is APICooldownMode.INTERVAL:
            return self._get_interval_cooldown()
        elif self.api_cooldown_mode is APICooldownMode.WINDOW:
            return self._get_window_cooldown()
        else:
            raise NotImplementedError
        
    def log_task_queue_state(self) -> None:
        queue_size = self.task_queue.qsize()
        queue_tasks = list(self.task_queue._queue)  # доступ к очереди задач
        self.logger.info(f'Task queue size: {queue_size}')
        for priority, task in queue_tasks:
            self.logger.info(f'Task in queue - Priority: {priority}, Task: {task}')

    async def _run(self) -> None:
        freeze_time = self.freeze_time_initial
        freeze_left = 0

        while not self.account.banned:
            self.update_state(WorkerState.WAITING)

            #if self.workers_queue is not None and self.task_queue.empty():
            #    self.workers_queue.put_nowait(
            #        CostBasedPriorityItem(self._account.cost, self)
            #    )

            if self.task_queue.empty():
                self._free.set()
            priority, task = await self.task_queue.get()
            assert not task.is_ready()
            self._free.clear()

            # Логируем состояние очереди задач
            self.log_task_queue_state()

            # Ждем окончания общего cooldown
            await self._cooldown_event.wait()

            async with self._semaphore:
                if task.admin:
                    route = '*'
                else:
                    route = self.account.get_route(task.path)
                    if not route:
                        self.logger.warning(f'{task} has forbidden route')
                        task.error = RoutingError(f'Forbidden route: {task.path}')
                        task.ready()
                        self.task_queue.task_done()
                        continue
                    elif self.account.limits_exceeded(task.path):
                        self.logger.warning(f'account exceeded limits: {task.path}')
                        task.error = LimitsError(f'Exceeded limits: {task.path}')
                        task.ready()
                        self.task_queue.task_done()
                        continue

                self.update_state(WorkerState.RUNNING)
                task.account = self.account.email
                task.work()
                self.logger.info(f'{task} in work')

                status_code = None
                try:
                    task.result = resp = await self.api_client.request(
                        api_auth=True, **task.request)
                    if (status_code := resp.status_code) // 100 != 2:
                        # TODO: изъять акк из кэша bind при любой ошибке
                        raise APIClientError(f'status code: {resp.status_code}')
                except APIClientError as exc:
                    task.error = exc
                    self.logger.error(f'{task} failed: {exc}')
                except asyncio.CancelledError as exc:
                    task.error = exc
                    raise
                except Exception as exc:
                    task.error = exc
                    self.logger.critical(
                        f'{task} failed with unexpected exception: {exc}')
                finally:
                    task.ready()
                    self.task_queue.task_done()

                self._req_timestamps.append(time()) # after response?

                #if status_code and status_code in self.banned_status_codes:
                #    self.account.banned = True
                #    self.account.add_routing_rule('deny', '*')
                #    self.logger.critical('account is banned')
                #    break

                if not task.admin:
                    self.account.inc_usage(task.path) # failed?
                    self.account.req_stats.setdefault(route, Counter())['sent'] += 1
                    if task.error:
                        self.account.req_stats[route]['failed'] += 1
                    else:
                        self.account.req_stats[route]['succeed'] += 1
                    self.account.last_status_codes[route] = status_code
                    self.account.last_req_timestamp = self._req_timestamps[-1]

                    if status_code and status_code in self.banned_status_codes:
                        # изъять акк из кэша bind
                        self._manager.remove_bind_request(task=task)
                        self.account.add_routing_rule('deny', route)
                        self.logger.warning(
                            f'added forbidden route ({status_code}): {route}')

                    elif (
                        route != '*' and # ?
                        status_code and status_code in self.freeze_status_codes
                    ):
                        # изъять акк из кэша bind
                        self._manager.remove_bind_request(task=task)
                        freeze_endpoint = route
                        retry_after = None
                        if self.retry_after_header:
                            try:
                                retry_after = float(
                                    resp.headers.get(self.retry_after_header))
                            except Exception as exc:
                                freeze_endpoint = re.match(
                                    r'^\D*', resp.url.path).group() # TODO: regex
                                if len(freeze_endpoint) < len(route):
                                    freeze_endpoint = route
                                self.logger.debug(
                                    f'retry_after ({resp.url.path}): {exc}')

                        if self.retry_after_max_time is not None:
                            retry_after = (
                                min(self.retry_after_max_time, retry_after)
                                if retry_after is not None else self.retry_after_max_time
                            )
                        expire = None if retry_after is None else time() + retry_after
                        self.account.add_routing_rule(
                            'deny', freeze_endpoint, expire=expire)
                        self.logger.warning(
                            f'added forbidden route ({status_code}): {freeze_endpoint} {expire=}')

                    elif self.account.limits_exceeded(task.path):
                        # TODO: изъять акк из кэша bind
                        self.account.add_routing_rule('deny', route)
                        self.logger.warning(
                            f'added forbidden route (exceeded limits): {route}')

                # Устанавливаем общее событие cooldown
                self._cooldown_event.clear()
                cooldown = self.get_api_cooldown()
                if cooldown:
                    self.logger.debug(f'cooldown for {cooldown} seconds')
                self.update_state(WorkerState.COOLDOWN)
                await asyncio.sleep(cooldown or 0.001) # switch
                self._cooldown_event.set()  # Разрешаем выполнение новых задач после cooldown

                if status_code and status_code not in self.freeze_status_codes:
                    if not freeze_left:
                        freeze_time = self.freeze_time_initial
                else:
                    freeze_left = freeze_time
                    freeze_time = min(
                        freeze_time * self.freeze_time_factor,
                        self.freeze_time_max
                    )

                if freeze_left:
                    self.logger.info(f'frozen for {freeze_left} seconds')
                    self.update_state(WorkerState.FROZEN)
                    while self.task_queue.empty():
                        await asyncio.sleep(0.1)
                        freeze_left -= 0.1 # it may be more, but who cares
                        if freeze_left <= 0:
                            freeze_left = 0
                            break
                    else:
                        self.logger.debug('unfrozen earlier')

    async def run(self) -> None:
        try:
            self.logger.info('running worker')
            self.update_state(WorkerState.RUNNING)
            return await self._run()
        except Exception as exc:
            self.logger.error(exc)
        finally:
            self.logger.info('terminating worker')
            self.update_state(WorkerState.TERMINATED)

    def start(self) -> None:
        if self._corotask is None:
            self._corotask = asyncio.create_task(self.run())

    def stop(self) -> None:
        if self._corotask is not None:
            self._corotask.cancel('stopped')

    async def wait(self) -> None:
        await self._free.wait()
