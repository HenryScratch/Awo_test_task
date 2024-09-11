from enum import StrEnum, auto
from asyncio import Event

class TaskState(StrEnum):
    CREATED = auto()
    SCHEDULED = auto()
    IN_WORK = auto()
    FINISHED = auto()

class Task:

    def __init__(
        self,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        params: str | None = None,
        params_dict: dict | None = None,
        content: bytes | None = None,
        account: str | None = None,
        group: str | None = None,
        login: str | None = None,
        admin: bool = False,
        priority: int = 1
    ) -> None:
        self.method = method.upper()
        self.path = path
        self.headers = headers
        self.params = params
        self.params_dict = params_dict
        self.content = content
        self.account = account
        self.group = group
        self.login = login
        self.admin = admin
        self.result = None
        self.error = None
        self._state = TaskState.CREATED
        self._ready = Event()
        self.priority = priority

    @property
    def request(self) -> dict:
        return {
            'method': self.method,
            'path': self.path,
            'headers': self.headers,
            'params': self.params,
            'content': self.content,
        }

    @property
    def state(self) -> TaskState:
        return self._state

    async def wait(self) -> None:
        await self._ready.wait()

    def schedule(self) -> None:
        self._state = TaskState.SCHEDULED

    def work(self) -> None:
        self._state = TaskState.IN_WORK

    def ready(self) -> None:
        self._state = TaskState.FINISHED
        self._ready.set()

    def is_ready(self) -> bool:
        return self._state is TaskState.FINISHED

    def is_failed(self) -> bool:
        return self.is_ready() and self.error is not None

    def __str__(self) -> str:
        return (
            f'{self.__class__.__name__} from '
            f'"{"admin" if self.admin else self.login}" '
            f'by "{self.group + ":" if self.group else ""}{self.account or "any"}" '
            f'priority {self.priority} '
            f'<{self.method} {self.path} {self.params}>'
        )
