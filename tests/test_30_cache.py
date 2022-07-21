from typing import Any

import pytest

import callcache
from callcache import cache


def func(a: Any, *args: Any, b: Any = None, **kwargs: Any) -> Any:
    if b is None:
        return locals()
    else:

        class LocalClass:
            pass

        return LocalClass()


@pytest.mark.xfail()
def test_MemcacheStore() -> None:
    store = cache.MemcacheStore()

    store.set("1", "a")

    assert store.get("1") == "a"
    assert store.stats["hit"] == 1

    store.set("2", "b")

    assert store.get("2") == "b"
    assert store.stats["hit"] == 2

    store.set("3", "c", expire=-1)

    assert store.get("3") is None
    assert store.stats["miss"] == 1

    store.clear()

    assert store.get("2") is None
    assert store.stats["hit"] == 0


@pytest.mark.xfail()
def test_DynamoDBStore() -> None:
    store = cache.DynamoDBStore("test_callcache")

    store.set("1", "a")

    assert store.get("1") == "a"
    assert store.stats["hit"] == 1

    store.set("2", "b")

    assert store.get("2") == "b"
    assert store.stats["hit"] == 2

    store.set("3", "c", expire=-1)

    assert store.get("3") is None
    assert store.stats["miss"] == 1

    store.clear()

    assert store.get("2") is None
    assert store.stats["hit"] == 0


@pytest.mark.xfail()
def test_FirestoreStore() -> None:
    store = cache.FirestoreStore("test_callcache")

    store.set("1", "a")

    assert store.get("1") == "a"
    assert store.stats["hit"] == 1

    store.set("2", "b")

    assert store.get("2") == "b"
    assert store.stats["hit"] == 2

    store.set("3", "c", expire=-1)

    assert store.get("3") is None
    assert store.stats["miss"] == 1

    store.clear()

    assert store.get("2") is None
    assert store.stats["hit"] == 0


def test_hexdigestify() -> None:
    text = "some random Unicode text \U0001f4a9"
    expected = "278a2cefeef9a3269f4ba1c41ad733a4c07101ae6859f607c8a42cf2"
    res = cache.hexdigestify(text)
    assert res == expected


def test_cacheable() -> None:
    cfunc = cache.cacheable()(func)
    res = cfunc("test")
    assert res == {"a": "test", "args": [], "b": None, "kwargs": {}}
    assert callcache.SETTINGS["cache"].stats() == (0, 1)

    res = cfunc("test")
    assert res == {"a": "test", "args": [], "b": None, "kwargs": {}}
    assert callcache.SETTINGS["cache"].stats() == (1, 1)

    class Dummy:
        pass

    inst = Dummy()
    with pytest.warns(UserWarning, match="bad input"):
        res = cfunc(inst)
    assert res == {"a": inst, "args": (), "b": None, "kwargs": {}}

    with pytest.warns(UserWarning, match="bad output"):
        res = cfunc("test", b=1)
    assert res.__class__.__name__ == "LocalClass"
