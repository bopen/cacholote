"""Functions to clean cache database and files."""

# Copyright 2022, European Union.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import collections
import datetime
import functools
import json
import posixpath
from typing import Any, Callable, Dict, List, Literal, Optional, Sequence, Set, Union

import sqlalchemy as sa
import sqlalchemy.orm

from . import config, database, decode, encode, extra_encoders, utils
from .database import CacheEntry

FILTERS_T = List[
    Union[sa.sql.elements.ColumnElement[bool], sa.sql.elements.BinaryExpression[bool]]
]


def _delete_cache_file(
    obj: Dict[str, Any],
    session: Optional[sa.orm.Session] = None,
    cache_entry: Optional[CacheEntry] = None,
    sizes: Optional[Dict[str, int]] = None,
    dry_run: bool = False,
) -> Any:
    logger = config.get().logger

    if {"type", "callable", "args", "kwargs"} == set(obj) and obj["callable"] in (
        "cacholote.extra_encoders:decode_xr_dataset",
        "cacholote.extra_encoders:decode_io_object",
    ):
        sizes = sizes or {}
        cache_fs, cache_dirname = utils.get_cache_files_fs_dirname()
        cache_dirname = cache_fs.unstrip_protocol(cache_dirname)

        fs, urlpath = extra_encoders._get_fs_and_urlpath(*obj["args"][:2])
        urlpath = fs.unstrip_protocol(urlpath)

        if posixpath.dirname(urlpath) == cache_dirname:
            sizes.pop(urlpath, None)
            if not dry_run:
                if session and cache_entry:
                    logger.info("delete cache entry", cache_entry=cache_entry)
                    session.delete(cache_entry)
                    database._commit_or_rollback(session)

                if fs.exists(urlpath):
                    logger.info("delete cache file", urlpath=urlpath)
                    fs.rm(
                        urlpath,
                        recursive=obj["args"][0]["type"] == "application/vnd+zarr",
                    )

    return obj


def _delete_cache_entry(session: sa.orm.Session, cache_entry: CacheEntry) -> None:
    # First, delete database entry
    session.delete(cache_entry)
    database._commit_or_rollback(session)
    if cache_entry.result:
        # Then, delete files
        json.loads(cache_entry._result_as_string, object_hook=_delete_cache_file)


def delete(
    func_to_del: Union[str, Callable[..., Any]], *args: Any, **kwargs: Any
) -> None:
    """Delete function previously cached.

    Parameters
    ----------
    func_to_del: callable, str
        Function to delete from cache
    *args: Any
        Argument of functions to delete from cache
    **kwargs: Any
        Keyword arguments of functions to delete from cache
    """
    hexdigest = encode._hexdigestify_python_call(func_to_del, *args, **kwargs)
    with config.get().sessionmaker() as session:
        for cache_entry in session.scalars(
            sa.select(CacheEntry).filter(CacheEntry.key == hexdigest)
        ):
            _delete_cache_entry(session, cache_entry)


class _Cleaner:
    def __init__(self) -> None:
        self.logger = config.get().logger
        self.fs, self.dirname = utils.get_cache_files_fs_dirname()

        urldir = self.fs.unstrip_protocol(self.dirname)

        self.logger.info("get disk usage of cache files")
        self.sizes: Dict[str, int] = collections.defaultdict(lambda: 0)
        for path, size in self.fs.du(self.dirname, total=False).items():
            # Group dirs
            urlpath = self.fs.unstrip_protocol(path)
            basename, *_ = urlpath.replace(urldir, "", 1).strip("/").split("/")
            if basename:
                self.sizes[posixpath.join(urldir, basename)] += size

    @property
    def size(self) -> int:
        sum_sizes = sum(self.sizes.values())
        self.logger.info("check cache files total size", size=sum_sizes)
        return sum_sizes

    def stop_cleaning(self, maxsize: int) -> bool:
        return self.size <= maxsize

    def get_unknown_files(self, lock_validity_period: Optional[float]) -> Set[str]:
        self.logger.info("get unknown files")
        now = datetime.datetime.now()
        files_to_skip = []
        for urlpath in self.sizes:
            if urlpath.endswith(".lock"):
                delta = now - self.fs.modified(urlpath)
                if lock_validity_period is None or delta < datetime.timedelta(
                    seconds=lock_validity_period
                ):
                    files_to_skip.append(urlpath)
                    files_to_skip.append(urlpath.rsplit(".lock", 1)[0])

        unknown_sizes = {k: v for k, v in self.sizes.items() if k not in files_to_skip}
        if unknown_sizes:
            with config.get().sessionmaker() as session:
                for cache_entry in session.scalars(
                    sa.select(CacheEntry).filter(CacheEntry.result.isnot(None))
                ):
                    json.loads(
                        cache_entry._result_as_string,
                        object_hook=functools.partial(
                            _delete_cache_file,
                            sizes=unknown_sizes,
                            dry_run=True,
                        ),
                    )
        return set(unknown_sizes)

    def delete_unknown_files(
        self, lock_validity_period: Optional[float], recursive: bool
    ) -> None:
        for urlpath in self.get_unknown_files(lock_validity_period):
            self.sizes.pop(urlpath)
            if self.fs.exists(urlpath):
                self.logger.info("delete unknown", urlpath=urlpath, recursive=recursive)
                self.fs.rm(urlpath, recursive=recursive)

    @staticmethod
    def check_tags(*args: Any) -> None:
        if None not in args:
            raise ValueError("tags_to_clean/keep are mutually exclusive.")
        for tags in args:
            if tags is not None and (
                not isinstance(tags, (list, set, tuple))
                or not all(tag is None or isinstance(tag, str) for tag in tags)
            ):
                raise TypeError(
                    "tags_to_clean/keep must be None or a sequence of str/None."
                )

    def delete_cache_files(
        self,
        maxsize: int,
        method: Literal["LRU", "LFU"],
        tags_to_clean: Optional[Sequence[Optional[str]]],
        tags_to_keep: Optional[Sequence[Optional[str]]],
    ) -> None:
        self.check_tags(tags_to_clean, tags_to_keep)

        # Filters
        filters: FILTERS_T = [CacheEntry.result.isnot(None)]
        if tags_to_keep is not None:
            filters.append(
                sa.or_(
                    CacheEntry.tag.not_in(tags_to_keep),
                    CacheEntry.tag.isnot(None)
                    if None in tags_to_keep
                    else CacheEntry.tag.is_(None),
                )
            )
        elif tags_to_clean is not None:
            filters.append(
                sa.or_(
                    CacheEntry.tag.in_(tags_to_clean),
                    CacheEntry.tag.is_(None)
                    if None in tags_to_clean
                    else CacheEntry.tag.isnot(None),
                )
            )

        # Sorters
        sorters: List[sa.orm.InstrumentedAttribute[Any]] = []
        if method == "LRU":
            sorters.extend([CacheEntry.timestamp, CacheEntry.counter])
        elif method == "LFU":
            sorters.extend([CacheEntry.counter, CacheEntry.timestamp])
        else:
            raise ValueError(f"{method=} is invalid. Choose either 'LRU' or 'LFU'.")
        sorters.append(CacheEntry.expiration)

        # Clean database files
        if self.stop_cleaning(maxsize):
            return
        with config.get().sessionmaker() as session:
            for cache_entry in session.scalars(
                sa.select(CacheEntry).filter(*filters).order_by(*sorters)
            ):
                json.loads(
                    cache_entry._result_as_string,
                    object_hook=functools.partial(
                        _delete_cache_file,
                        session=session,
                        cache_entry=cache_entry,
                        sizes=self.sizes,
                    ),
                )
                if self.stop_cleaning(maxsize):
                    return

        raise ValueError(
            f"Unable to clean {self.dirname!r}. Final size: {self.size!r}. Expected size: {maxsize!r}"
        )


def clean_cache_files(
    maxsize: int,
    method: Literal["LRU", "LFU"] = "LRU",
    delete_unknown_files: bool = False,
    recursive: bool = False,
    lock_validity_period: Optional[float] = None,
    tags_to_clean: Optional[Sequence[Optional[str]]] = None,
    tags_to_keep: Optional[Sequence[Optional[str]]] = None,
) -> None:
    """Clean cache files.

    Parameters
    ----------
    maxsize: int
        Maximum total size of cache files (bytes).
    method: str, default: "LRU"
        * LRU: Last Recently Used
        * LFU: Least Frequently Used
    delete_unknown_files: bool, default: False
        Delete all files that are not registered in the cache database.
    recursive: bool, default: False
        Whether to delete unknown directories or not
    lock_validity_period: float, optional, default: None
        Validity period of lock files in seconds. Expired locks will be deleted.
    tags_to_clean, tags_to_keep: sequence of strings/None, optional, default: None
        Tags to clean/keep. If None, delete all cache entries.
        To delete/keep untagged entries, add None in the sequence (e.g., [None, 'tag1', ...]).
        tags_to_clean and tags_to_keep are mutually exclusive.
    """
    cleaner = _Cleaner()

    if delete_unknown_files:
        cleaner.delete_unknown_files(lock_validity_period, recursive)

    cleaner.delete_cache_files(
        maxsize=maxsize,
        method=method,
        tags_to_clean=tags_to_clean,
        tags_to_keep=tags_to_keep,
    )


def clean_invalid_cache_entries(
    check_result: bool = True, check_expiration: bool = True, try_decode: bool = False
) -> None:
    """Clean invalid cache entries.

    Parameters
    ----------
    check_result: bool
        Whether or not to delete entries without results
    check_expiration: bool
        Whether or not to delete expired entries
    try_decode: bool
        Whether or not to delete entries that raise DecodeError (can be slow!)
    """
    filters: FILTERS_T = []
    if check_result:
        filters.append(CacheEntry.result.is_(None))
    if check_expiration:
        filters.append(CacheEntry.expiration <= utils.utcnow())
    if filters:
        with config.get().sessionmaker() as session:
            for cache_entry in session.scalars(
                sa.select(CacheEntry).filter(sa.or_(*filters))
            ):
                _delete_cache_entry(session, cache_entry)

    if try_decode:
        with config.get().sessionmaker() as session:
            for cache_entry in session.scalars(sa.select(CacheEntry)):
                try:
                    decode.loads(cache_entry._result_as_string)
                except decode.DecodeError:
                    _delete_cache_entry(session, cache_entry)
