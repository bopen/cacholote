from typing import Any, Dict

import fsspec
import pytest
import pytest_httpserver

from cacholote import cache, config, extra_encoders


def open_url(url: str) -> fsspec.spec.AbstractBufferedFile:
    with fsspec.open(url) as f:
        return f


@pytest.mark.parametrize("io_delete_original", [True, False])
def test_dictify_io_object(tmpdir: str, io_delete_original: bool) -> None:
    tmpfile = f"{tmpdir}/test.txt"
    with open(tmpfile, "wb") as f:
        f.write(b"test")
    tmp_checksum = fsspec.filesystem("file").checksum(tmpfile)

    with config.set(io_delete_original=io_delete_original):
        actual = extra_encoders.dictify_io_object(open(tmpfile, "rb"))

    local_path = f"{tmpdir}/{tmp_checksum}.txt"
    checksum = fsspec.filesystem("file").checksum(local_path)
    expected = {
        "type": "text/plain",
        "href": f"file://{local_path}",
        "file:checksum": checksum,
        "file:size": 4,
        "file:local_path": local_path,
        "tmp:open_kwargs": {"mode": "rb"},
        "tmp:storage_options": {},
    }
    assert actual == expected
    assert fsspec.filesystem("file").exists(tmpfile) is not io_delete_original


@pytest.mark.parametrize("ftp_config_settings", [False, True], indirect=True)
def test_copy_from_http_to_cache(
    tmpdir: str,
    httpserver: pytest_httpserver.HTTPServer,
    ftp_config_settings: Dict[str, Any],
) -> None:
    httpserver.expect_request("/test").respond_with_data(b"test")
    url = httpserver.url_for("/test")
    url_checksum = fsspec.filesystem("http").checksum(url)

    cfunc = cache.cacheable(open_url)
    infos = []
    for expected_stats in ((0, 1), (1, 1)):
        with config.set(**ftp_config_settings):
            dirfs = config.get_cache_files_dirfs()
            result = cfunc(url)

            # Check hit & miss
            assert config.SETTINGS["cache_store"].stats() == expected_stats

            infos.append(dirfs.info(f"{url_checksum}"))

        # Check result
        assert result.read() == b"test"

        # Check file in cache
        assert result.path == f"{'' if ftp_config_settings else tmpdir}/{url_checksum}"

    # Check cached file is not modified
    assert infos[0] == infos[1]

    if not ftp_config_settings:
        # Warn but don't fail if file is corrupted
        dirfs.touch(f"{url_checksum}", truncate=False)
        touched_checksum = dirfs.checksum(f"{url_checksum}")
        with pytest.warns(UserWarning, match="checksum mismatch"):
            result = cfunc(url)
        assert result.read() == b"test"
        assert dirfs.checksum(f"{url_checksum}") != touched_checksum

        # Warn but don't fail if file is deleted
        dirfs.rm(f"{url_checksum}", recursive=True)
        with pytest.warns(UserWarning, match="No such file or directory"):
            result = cfunc(url)
        assert result.read() == b"test"
        assert dirfs.exists(f"{url_checksum}")
