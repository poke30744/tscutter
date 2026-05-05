"""Progress utility for tscutter/tsmarker subprocess tools.

Two modes:
  standalone: Rich Progress renders directly in terminal
  --progress: emit PROGRESS JSON lines to stderr for parent orchestration
"""

import json, sys
from rich.progress import Progress as RichProgress


class Progress:
    def __init__(self, use_protocol: bool = False):
        self.use_protocol = use_protocol
        self._rich: RichProgress | None = None
        self._tasks: dict[str, int] = {}
        if not use_protocol:
            self._rich = RichProgress().__enter__()

    def add_task(self, task_id: str, total: float, desc: str, unit: str = "it"):
        if self.use_protocol:
            self._emit({"task": task_id, "total": total, "desc": desc, "unit": unit})
        elif self._rich is not None:
            self._tasks[task_id] = self._rich.add_task(desc, total=total)

    def update(self, task_id: str, n: float):
        if self.use_protocol:
            self._emit({"task": task_id, "n": n})
        elif self._rich is not None:
            self._rich.update(self._tasks[task_id], completed=n)

    def done(self, task_id: str):
        if self.use_protocol:
            self._emit({"task": task_id, "status": "done"})
        elif self._rich is not None:
            self._rich.update(self._tasks[task_id], visible=False)

    def close(self):
        if self._rich is not None:
            self._rich.__exit__(None, None, None)

    def _emit(self, data: dict):
        sys.stderr.write(f"PROGRESS:{json.dumps(data)}\n")
        sys.stderr.flush()
