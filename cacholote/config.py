"""Global settings."""

# Copyright 2019, B-Open Solutions srl.
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

import os
import tempfile
from types import MappingProxyType, TracebackType
from typing import Any, Dict, Optional, Type

import diskcache

_EXTENSIONS = MappingProxyType(
    {
        "application/x-netcdf": ".nc",
        "application/x-grib": ".grib",
        "application/vnd+zarr": ".zarr",
    }
)
_SETTINGS: Dict[str, Any] = {
    "cache_store_directory": os.path.join(tempfile.gettempdir(), "cacholote"),
    "cache_files_urlpath": None,
    "cache_files_storage_options": {},
    "xarray_cache_type": list(_EXTENSIONS)[0],
    "io_delete_original": False,
}


def _initialize_cache_store() -> None:
    _SETTINGS["cache_store"] = diskcache.Cache(
        _SETTINGS["cache_store_directory"], disk=diskcache.JSONDisk, statistics=1
    )


_initialize_cache_store()

# Immutable settings to be used by other modules
SETTINGS = MappingProxyType(_SETTINGS)


class set:
    """Customize cacholote settings.

    It is possible to use it either as a context manager, or to configure global settings.

    Parameters
    ----------
    cache_store_directory : str, default: system-specific-tmpdir/cacholote
        Directory for the cache store.
    cache_files_urlpath : str, optional, default: None
        URL for cache files.
        * None: store cache files in `cache_store_directory`
    cache_files_storage_options : dict, default: {}
        `fsspec` storage options for storing cache files.
    xarray_cache_type : {"application/x-netcdf", "application/x-grib", "application/vnd+zarr"}, \
        default: "application/x-netcdf"
        Type for `xarray` cache files.
    io_delete_original: bool, default: False
        Whether to delete the original copy of cached files.
    cache_store:
        Key-value store object for the cache. Mutually exclusive with `cache_store_directory`.
    """

    def __init__(self, **kwargs: Any):

        if "cache_store" in kwargs:
            if "cache_store_directory" in kwargs:
                raise ValueError(
                    "'cache_store' and 'cache_store_directory' are mutually exclusive"
                )
            kwargs["cache_store_directory"] = None

        if (
            "xarray_cache_type" in kwargs
            and kwargs["xarray_cache_type"] not in _EXTENSIONS
        ):
            raise ValueError(f"'xarray_cache_type' must be one of {list(_EXTENSIONS)}")

        try:
            self._old = {key: _SETTINGS[key] for key in kwargs}
        except KeyError as ex:
            raise ValueError(
                f"Wrong settings. Available settings: {list(_SETTINGS)}"
            ) from ex

        _SETTINGS.update(kwargs)
        if kwargs.get("cache_store_directory") is not None:
            self._old["cache_store"] = _SETTINGS["cache_store"]
            _initialize_cache_store()

    def __enter__(self) -> None:
        pass

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        _SETTINGS.update(self._old)
