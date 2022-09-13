import os
from typing import Any, Dict, TypeVar

import fsspec
import pytest

from cacholote import cache, config, decode, encode, extra_encoders

try:
    import xarray as xr
finally:
    pytest.importorskip("cfgrib")
    pytest.importorskip("dask")
    pytest.importorskip("xarray")
    pytest.importorskip("zarr")

T = TypeVar("T")


def func(a: T) -> T:
    return a


@pytest.fixture
def ds() -> xr.Dataset:
    url = "https://github.com/ecmwf/cfgrib/raw/master/tests/sample-data/era5-levels-members.grib"
    with fsspec.open(f"simplecache::{url}", simplecache={"same_names": True}) as of:
        fname = of.name
    ds = xr.open_dataset(fname, engine="cfgrib")
    del ds.attrs["history"]
    return ds.sel(number=0)


PARAMETRIZE = (
    "xarray_cache_type,extension,size,open_kwargs",
    [
        ("application/x-netcdf", ".nc", 501607, {"chunks": "auto"}),
        ("application/x-grib", ".grib", 353088, {"chunks": "auto"}),
        (
            "application/vnd+zarr",
            ".zarr",
            448,
            {"chunks": "auto", "engine": "zarr", "consolidated": True},
        ),
    ],
)


@pytest.mark.parametrize(*PARAMETRIZE)
def test_dictify_xr_dataset(
    ds: xr.Dataset,
    xarray_cache_type: str,
    extension: str,
    size: int,
    open_kwargs: Dict[str, Any],
) -> None:
    local_path = os.path.join(
        config.SETTINGS["cache_store"].directory,
        f"06810be7ce1f5507be9180bfb9ff14fd{extension}",
    )
    with config.set(xarray_cache_type=xarray_cache_type):
        res = extra_encoders.dictify_xr_dataset(ds)

    expected = {
        "type": xarray_cache_type,
        "href": local_path,
        "file:checksum": fsspec.filesystem("file").checksum(local_path),
        "file:size": size,
        "file:local_path": local_path,
        "xarray:open_kwargs": open_kwargs,
        "xarray:storage_options": {},
    }
    assert res == expected


@pytest.mark.parametrize(*PARAMETRIZE)
def test_xr_roundtrip(
    ds: xr.Dataset,
    xarray_cache_type: str,
    extension: str,
    size: int,
    open_kwargs: Dict[str, Any],
) -> None:
    with config.set(xarray_cache_type=xarray_cache_type):
        ds_json = encode.dumps(ds)
        res = decode.loads(ds_json)

    if xarray_cache_type == "application/x-grib":
        xr.testing.assert_equal(res, ds)
    else:
        xr.testing.assert_identical(res, ds)


@pytest.mark.parametrize(*PARAMETRIZE)
def test_xr_cacheable(
    ds: xr.Dataset,
    xarray_cache_type: str,
    extension: str,
    size: int,
    open_kwargs: Dict[str, Any],
) -> None:
    local_path = os.path.join(
        config.SETTINGS["cache_store"].directory,
        f"06810be7ce1f5507be9180bfb9ff14fd{extension}",
    )

    with config.set(xarray_cache_type=xarray_cache_type):
        cfunc = cache.cacheable(func)

        # 1: create cached data
        res = cfunc(ds)
        assert config.SETTINGS["cache_store"].stats() == (0, 1)
        assert len(config.SETTINGS["cache_store"]) == 1
        mtime = os.path.getmtime(local_path)

        if xarray_cache_type == "application/x-grib":
            xr.testing.assert_equal(res, ds)
        else:
            xr.testing.assert_identical(res, ds)

        # 2: use cached data
        res = cfunc(ds)
        assert config.SETTINGS["cache_store"].stats() == (1, 1)
        assert len(config.SETTINGS["cache_store"]) == 1
        assert mtime == os.path.getmtime(local_path)

        if xarray_cache_type == "application/x-grib":
            xr.testing.assert_equal(res, ds)
        else:
            xr.testing.assert_identical(res, ds)
