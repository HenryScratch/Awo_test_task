import collections
import re
import asyncio
import logging

from copy import deepcopy
from time import monotonic
from datetime import datetime, timezone
from collections import Counter

from .task import Task
from .cache import RedisCache
from .mpstats import MPStatsWorker
from .models import Account, AccountAPIMode
from .log import get_logger, log_on_error
from .config import DONOR_CONFIG, API_CONFIG


class ManagerError(Exception): ...

class Manager:

    task_queue_maxsize = 25
    task_queue_size_warning_threshold = 10
    nodatetime = datetime(1000, 1, 1, tzinfo=timezone.utc)
    

    def __init__(self) -> None:
        self._accounts = {}
        self._workers = {}
        # self._workers_queue = asyncio.PriorityQueue()
        self._worker_waiting_time = Counter()
        self._task_type = Counter()
        self.bind_requests_cache = RedisCache(
            maxsize=10**3,
            ttl=DONOR_CONFIG['api_bind_requests_cache_ttl'],
        )
        self._bind_requests_path_re = re.compile(
            '|'.join([elem.get("path") for elem in DONOR_CONFIG['api_bind_requests_path_re']]),
            re.I
        )
        self.logger = get_logger(f'{self.__class__.__name__}')

    @property
    def free_workers_available(self) -> int:
        num = 0
        for worker in self._workers.values():
            if worker.is_running():
                num += 1
        return num
    
    def remove_bind_request(self, task: Task):
        bind_key = getattr(task, "bind_key", None)
        if bind_key: 
            self.bind_requests_cache.remove(bind_key)
            return True
        return False
            
    @log_on_error(logging.WARNING)
    async def add_task(self, task: Task) -> None:
        if task.admin:
            if not task.account:
                if not task.group:
                    self._task_type[0] += 1
                else:
                    self._task_type[1] += 1
            else:
                self._task_type[2] += 1
            # is_group_request = False
        else:
            if not task.account:
                if not task.group:
                    self._task_type[3] += 1
                else:
                    self._task_type[4] += 1
            else:
                self._task_type[5] += 1
            

            is_bind_request = self._bind_requests_path_re.match(task.path)
            if is_bind_request:
                params_cache = collections.OrderedDict()
                path_re = None
                catch_path = None
                self._task_type[-1] += 1
                if not task.account:
                    for elem in DONOR_CONFIG["api_bind_requests_path_re"]:
                        path_re, params_mask = elem["path"], elem["params"]
                        catch_path = re.match(path_re, task.path)
                        if catch_path:
                            for param, value in task.params_dict.items():
                                if param in params_mask:
                                    params_cache.update({param: value})
                            break
                    if catch_path and params_cache:
                        sorted_params_cache = "|".join([k+":"+params_cache[k] for k in sorted(params_cache)])
                        key = f"bind|{catch_path[0]}|{sorted_params_cache}"
                        setattr(task,"bind_key", key)
                        task.account = self.bind_requests_cache.get(key)
                        # Приоритет высший для повторных запросов по url (ведь они не считаются)
                        if task.account: task.priority = 0 

        if task.account is not None:
            if (account := self._accounts.get(task.account)) is None:
                self.remove_bind_request(task=task)
                raise ManagerError(f'account not found: {task.account}')
            worker = self._workers[account.uid]
            self._worker_waiting_time[0] += 1
            if (qsize := worker.task_queue.qsize()) >= self.task_queue_maxsize:
                raise ManagerError(
                    f'{worker.account.email} queue exceeded maxsize: {qsize}')
            #if account.api_mode is AccountAPIMode.DRUM:
            #    self._cancel(worker)
        elif not task.admin:
            #while True:
            #    item = await self._workers_queue.get() # block forever
            #    if not item.cancelled:
            #        worker = item.worker
            #        break
            group = task.group or Account.model_fields['group'].default
            candidates = []
            for worker in self._workers.values():
                if (
                    worker.account.api_mode is AccountAPIMode.DRUM and
                    worker.account.group == group and
                    worker.is_running() and
                    worker.task_queue.qsize() < self.task_queue_maxsize and
                    worker.account.get_route(task.path) and
                    not worker.account.limits_exceeded(task.path)
                ):
                    candidates.append(worker)

            if not candidates:
                self._worker_waiting_time[-1] += 1
                raise ManagerError(f'no workers available: {task}')

            since = monotonic()
            aws = [
                asyncio.create_task(worker.wait())
                for worker in sorted(
                    candidates,
                    key=lambda _: (
                        _.account.cost,
                        _.account.last_req_timestamp or self.nodatetime,
                        self.bind_requests_cache.count_keys_for_value(_.account.email),
                    )
                )
            ]
            done, pending = await asyncio.wait(
                aws,
                timeout=API_CONFIG['workers_timeout'],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for aw in pending:
                aw.cancel()

            if done:
                time_spent = monotonic() - since
                self._worker_waiting_time[int(time_spent)+1] += 1
                self.logger.debug(
                    f'free worker was found in {time_spent:.2f} seconds')
            else:
                self._worker_waiting_time[-1] += 1
                raise ManagerError(f'no free worker available: {task}')

            aw = next(iter(done))
            worker = candidates[aws.index(aw)]

        else:
            raise ManagerError

        if worker.account.banned:
            raise ManagerError(f'{worker.account.email} is banned')
        elif not ((worker.is_frozen() and task.admin) or worker.is_running()):
            raise ManagerError(f'{worker.account.email} is {worker.state.name}')

        if is_bind_request:
            self.logger.debug(f'bind request by {worker.account.email}: {task}')
            self.bind_requests_cache.set(task.bind_key, worker.account.email)
            
        task.schedule()
        worker.task_queue.put_nowait((task.priority, task))
        self.logger.debug(f'{task} is scheduled')
        qsize = worker.task_queue.qsize()
        msg = f'{worker.account.email} queue size: {qsize}'
        if qsize > self.task_queue_size_warning_threshold:
            self.logger.warning(msg)
        else:
            self.logger.debug(msg)

    def add_account(self, account: Account) -> None:
        if account.email in self._accounts:
            raise ManagerError(f'account is already registered: {account.email}')
        self._accounts[account.email] = account
        if (
            not account.limits and
            DONOR_CONFIG.get('api_daily_limits_per_account')
        ):
            account.limits = dict(
                DONOR_CONFIG['api_daily_limits_per_account'])
        if (
            not account.api_routing_rules and
            DONOR_CONFIG.get('api_default_routing_rules')
        ):
            account.api_routing_rules = deepcopy(
                DONOR_CONFIG['api_default_routing_rules'])
        account._routing_rules_origin = deepcopy(account.api_routing_rules)
        self.logger.info(f'account {account.email} is registered')
        self._start_worker(account)

    def get_account(self, email: str) -> Account:
        if email not in self._accounts:
            raise ManagerError(f'account not found: {email}')
        account = self._accounts[email]
        account._refresh_routing_rules()
        return account

    def get_all_accounts(self) -> list[Account]:
        return [self.get_account(email) for email in self._accounts]

    def remove_account(self, email: str) -> None:
        if email not in self._accounts:
            raise ManagerError(f'account not found: {email}')
        account = self._accounts.pop(email)
        self.logger.info(f'account {account.email} is removed')
        self._stop_worker(account)

    def remove_all_accounts(self) -> None:
        for email in list(self._accounts):
            self.remove_account(email)

    def reset_account(self, email: str) -> None:
        if email not in self._accounts:
            raise ManagerError(f'account not found: {email}')
        account = self._accounts[email]
        account.api_routing_rules = account._routing_rules_origin
        account._api_routing_rules_expire = {}
        account.req_stats = {}
        account.last_status_codes = {}
        account.last_req_timestamp = None
        account.usage = Counter()

    def reset_all_accounts(self) -> None:
        for email in self._accounts:
            self.reset_account(email)

    def _start_worker(self, account: Account) -> None:
        worker = MPStatsWorker(
            account,
            self
        )
        self._workers[worker.uid] = worker
        worker.start()

    def _stop_worker(self, account: Account) -> None:
        worker = self._workers.pop(account.uid)
        worker.stop()#
        #if account.api_mode is AccountAPIMode.DRUM:
        #    self._cancel(worker)

    #def _cancel(self, worker: AsyncWorker) -> None:
    #    for item in self._workers_queue._queue:
    #        if item.worker is worker:
    #            item.cancelled = True
