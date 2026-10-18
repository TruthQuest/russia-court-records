"""tqdm if installed (pip install tqdm), otherwise a plain stand-in so the scripts still run."""
from __future__ import annotations

import contextlib

try:
    from tqdm import tqdm
    from tqdm.contrib.logging import logging_redirect_tqdm
except ImportError:  # pragma: no cover
    class tqdm:  # noqa: N801
        def __init__(self, iterable=None, total=None, **_):
            self.iterable, self.total, self.n = iterable, total, 0

        def __iter__(self):
            for x in self.iterable:
                self.n += 1
                if self.n % 100 == 0:
                    print(f"  {self.n}/{self.total or '?'}", flush=True)
                yield x

        def update(self, k=1):
            self.n += k
            if self.n % 100 == 0 or self.n == self.total:
                print(f"  {self.n}/{self.total or '?'}", flush=True)

        def set_postfix_str(self, *_a, **_k):
            pass

        def close(self):
            pass

    @contextlib.contextmanager
    def logging_redirect_tqdm():
        yield
