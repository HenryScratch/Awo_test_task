import re
from time import time
from datetime import datetime
from collections import Counter
from enum import StrEnum, auto
from pydantic import BaseModel, Field, ConfigDict, computed_field
from .utils import get_uuid


class WorkerState(StrEnum):
    IDLE = auto()
    WAITING = auto()
    RUNNING = auto()
    COOLDOWN = auto()
    FROZEN = auto()
    TERMINATED = auto()


class ProxyStatus(StrEnum):
    UNKNOWN = auto()
    ALIVE = auto()
    DEAD = auto()

class ProxyType(StrEnum):
    SOCKS5 = auto()
    HTTP = auto()

class Proxy(BaseModel):
    uid: str = Field(default_factory=get_uuid)
    type: ProxyType = ProxyType.HTTP
    host: str
    port: int
    user: str | None = None
    password: str | None = None
    token: str | None = None
    status: ProxyStatus = ProxyStatus.UNKNOWN

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_assignment=True,
    )

    @computed_field
    @property
    def url(self) -> str:
        auth = f'{self.user}:{self.password}@' if self.user else ''
        return f'{self.type.value}://{auth}{self.host}:{self.port}'

    def is_alive(self) -> bool:
        return self.status is ProxyStatus.ALIVE

    def test(self) -> None:
        self.status = ProxyStatus.UNKNOWN
        try:
            return
        except Exception:
            self.status = ProxyStatus.DEAD
        else:
            self.status = ProxyStatus.ALIVE


class LimitsMixin(BaseModel):

    limits: dict[str, int] = Field(default_factory=dict)
    usage: Counter = Field(default_factory=Counter)

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_assignment=True,
    )

    @computed_field
    @property
    def usage_total(self) -> int:
        return self.usage.total()

    def limits_exceeded(self, path: str) -> bool:
        assert isinstance(path, str)
        if not self.limits:
            return False
        for route, limits in self.limits.items():
            if route == '*' or re.match(route, path, re.I):
                if self.usage.get(route, 0) < limits:
                    return False
                else:
                    return True
        else:
            return False

    def inc_usage(self, path: str) -> None:
        assert isinstance(path, str)
        if self.limits:
            for route in self.limits:
                if route == '*' or re.match(route, path, re.I):
                    break
            else:
                route = '*'
        else:
            route = '*'
        self.usage[route] += 1


class AccountAPIMode(StrEnum):
    DIRECT = auto()
    DRUM = auto()

class APICooldownMode(StrEnum):
    INTERVAL = auto()
    WINDOW = auto()

type APICooldownParam = float | list[tuple[int, float] | float]

# TODO: repr
class Account(LimitsMixin):
    uid: str = Field(default_factory=get_uuid)
    email: str
    group: str = 'main'
    api_token: str
    api_mode: AccountAPIMode = AccountAPIMode.DRUM
    api_cooldown_param: APICooldownParam | None = None
    api_cooldown_mode: APICooldownMode | None = None
    api_routing_rules: dict[str, list[str]] = Field(default_factory=dict)
    cost: int = 0
    created_at: datetime | None = None # accepts epoch in seconds
    expire_at: datetime | None = None # accepts epoch in seconds
    registered_at: datetime = Field(default_factory=datetime.now)
    req_stats: dict[str, Counter] = Field(default_factory=dict)
    last_status_codes: dict[str, int] = Field(default_factory=dict)
    last_req_timestamp: datetime | None = None # accepts epoch in seconds
    worker_state: WorkerState | None = None
    banned: bool = False
    proxy: Proxy | None = None

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_assignment=True,
    )

    def __init__(self, **data) -> None:
        super().__init__(**data)
        self._api_routing_rules_expire = {}

    #@computed_field
    #@property
    #def req_succeed(self) -> int:
    #    return self.req_sent - self.req_failed

    #@computed_field
    #@property
    #def req_left(self) -> int | None:
    #    if self.req_max is None:
    #        return None
    #    else:
    #        return max(0, self.req_max - self.req_sent)

    #@computed_field
    #@property
    #def fail_rate(self) -> float:
    #    if self.req_sent:
    #        return self.req_failed / self.req_sent
    #    else:
    #        return 0.0

    @computed_field
    @property
    def lifetime(self) -> int | None:
        if self.expire_at:
            return max(0, int(self.expire_at.timestamp() - time()))
        else:
            return None

    @computed_field
    @property
    def worth(self) -> float | None:
        if self.created_at and self.expire_at and self.cost:
            created_at = self.created_at.timestamp()
            expire_at = self.expire_at.timestamp()
            if created_at >= expire_at:
                return None
            else:
                return self.lifetime * (
                    self.cost / (expire_at - created_at)
                )
        else:
            return None

    def get_route(self, path: str) -> str | None:
        assert isinstance(path, str)
        if self.banned:
            return None
        elif not self.api_routing_rules:
            return '*'
        self._refresh_routing_rules()
        for route in self.api_routing_rules.get('deny', []):
            if route == '*' or re.match(route, path, re.I):
                return None
        if 'allow' in self.api_routing_rules:
            for route in self.api_routing_rules['allow']:
                if route == '*' or re.match(route, path, re.I):
                    return route
            else:
                return None
        else:
            return '*'

    def add_routing_rule(
        self,
        rule: str,
        route: str,
        index: int = -1,
        expire: int | float | None = None,
    ) -> None:
        assert isinstance(rule, str) and rule in ('allow', 'deny')
        assert isinstance(route, str)
        assert isinstance(index, int)
        assert expire is None or isinstance(expire, (int, float))
        routes = self.api_routing_rules.setdefault(rule, [])
        if route in routes:
            routes.remove(route)
        if index == -1:
            routes.append(route)
        else:
            routes.insert(index, route)
        if expire is not None:
            self._api_routing_rules_expire[(rule, route)] = expire
        else:
            self._api_routing_rules_expire.pop((rule, route), None)

    def _refresh_routing_rules(self) -> None:
        now = None
        for (rule, route), expire in list(self._api_routing_rules_expire.items()):
            if route in self.api_routing_rules.get(rule, []):
                if expire < (now or (now := time())):
                    self._api_routing_rules_expire.pop((rule, route), None)
                    self.api_routing_rules[rule].remove(route)
            else:
                self._api_routing_rules_expire.pop((rule, route), None)


class User(LimitsMixin):
    uid: str = Field(default_factory=get_uuid)
    login: str
    sub: str = 'base'
    banned: bool = False

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_assignment=True,
    )
