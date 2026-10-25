"""Per-task active collection budget; waiting for the shared browser is excluded."""
import asyncio
from contextvars import ContextVar

current_budget=ContextVar('collection_budget',default=None)
ACTIVE_SECONDS=600
QUEUE_SECONDS=1800


class Budget:
    def __init__(self,timer):
        self.timer=timer
        self.remaining=0
        self.buffers=[]

    def pause(self):
        deadline=self.timer.when()
        self.remaining=max(0,deadline-asyncio.get_running_loop().time()) if deadline is not None else 0
        self.timer.reschedule(None)

    def resume(self):
        self.timer.reschedule(asyncio.get_running_loop().time()+self.remaining)

    def jobs(self):
        return list({j.id:j for buf in self.buffers for j in (buf.values() if isinstance(buf,dict) else buf)}.values())


def track(buffer):
    """Keep the collector's live result buffer available if its task times out."""
    budget=current_budget.get()
    if budget is not None: budget.buffers.append(buffer)
