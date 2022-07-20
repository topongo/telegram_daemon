from typing import Callable
from inspect import getsource
from datetime import datetime, timedelta
from telebotapi import TelegramBot
from time import sleep
from uuid import uuid4


class Filter:
    def __init__(self, comparer: Callable):
        self.comparer = comparer

    def call(self, msg):
        try:
            return self.comparer(msg)
        except AttributeError:
            print("Exception caught")
            return False

    def __str__(self):
        return f"Filter(\"{getsource(self.comparer).strip()}\""

    def __repr__(self):
        return str(self)


class Condition:
    def __init__(self, *filters: Filter, callback=lambda l: None, stop_return=None):
        self.callback = callback
        self.stop_return = stop_return
        self.filters = list(filters)

    def add_filter(self, *f):
        for i in f:
            self.filters.append(i)

    def meet(self, msg):
        return all(map(lambda l: l.call(msg), self.filters))

    def __str__(self):
        return f"Condition(filters=[{', '.join(map(lambda l: str(l), self.filters))}], callback={self.callback})"

    def __repr__(self):
        return str(self)


class Fork:
    def __init__(self, *conditions, completed, exclusive=False):
        self.exclusive = exclusive
        self.quick_stop = True
        self.conditions = conditions
        self.substitute = None
        for c in self.conditions:
            if c.stop_return is not None:
                raise TypeError("\"conditions\" argument cannot contain Conditions with stop_return, only the"
                                "\"completed\" argument can have it.")
        self.completed = completed
        if self.completed.stop_return is None:
            raise TypeError("\"completed\" argument must have the stop_return attribute set")
        self.result = None
        self.done = False

    def process(self, u_: TelegramBot.Update):
        if self.done:
            return
        if self.quick_stop and self.completed.meet(u_.content):
            self.completed.callback(u_.content)
            self.done = True
            return
        for c in self.conditions:
            if c.meet(u_.content):
                c.callback(u_.content)
                if self.exclusive:
                    break
        if self.completed.meet(u_.content):
            self.done = True
        else:
            print(":: warning: fork has matched, but is still running")

    def join(self):
        while not self.done:
            if self.substitute:
                self.substitute.join()
                break
            sleep(.2)


class Forks:
    def __init__(self):
        self.forks = {}

    def attach(self, *conds: Condition, completed: Condition, exclusive=False, custom_id=None):
        u_ = uuid4() if custom_id is None else custom_id
        self.forks[u_] = Fork(*conds, completed=completed, exclusive=exclusive)
        return u_

    def detach(self, id_):
        self.forks.pop(id_)

    def replace(self, id_, *conds: Condition, completed: Condition, exclusive=False, quick_stop=False):
        new_fork = Fork(*conds, completed=completed, exclusive=exclusive, quick_stop=quick_stop)
        self.get(id_).substitute = new_fork
        self.forks[id_] = new_fork

    def send(self, u_: TelegramBot.Update):
        for id_, f in self.forks.items():
            f.process(u_)

    def get(self, id_) -> Fork:
        return self.forks[id_]


def wait_for(t: TelegramBot,
             *conditions: Condition,
             timeout=300,
             forks=None):

    t.daemon.delay = 0.5

    if timeout == 0:
        infinite = True
        timeout_end = datetime.now()
    else:
        infinite = False
        timeout_end = datetime.now() + timedelta(seconds=timeout)

    while True:
        for u in t.get_updates():
            for c in conditions:
                if c.meet(u.content):
                    c.callback(u.content)
                    if c.stop_return is not None:
                        if isinstance(c.stop_return, Callable):
                            return c.stop_return(u.content)
                        else:
                            return c.stop_return
                    continue
            if forks:
                forks.send(u)
        if not infinite and timeout_end < datetime.now():
            return False
        sleep(0.1)
