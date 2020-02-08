class Memoizer:
    """
    General purpose cache for function results. Appends positional args, overlays kwargs. Both must be hashable.
    """

    __slots__ = ["_cache", "_func", "_args", "_kwargs"]

    def __init__(self, func, *args, **kwargs):
        self._cache = {}
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def clear(self):
        "clears the internal arg -> result cache"
        self._cache.clear()

    def filter(self, iterable, *, skip_nulls=False):
        "Calls the function on each item in the passed iterable. Only one positional arg at a time is supported."
        gen = map(self, iterable)

        if skip_nulls:
            return filter(None, gen)
        else:
            return gen

    def __call__(self, *args, **kwargs):
        if kwargs:
            key = (*args, tuple(kwargs.items()))
            call_kwargs = self._kwargs.copy()
            call_kwargs.update(kwargs)
        else:
            key = args
            call_kwargs = self._kwargs

        try:
            return self._cache[key]
        except KeyError:
            ret = self._cache[key] = self._func(*self._args, *args, **call_kwargs)
            return ret
