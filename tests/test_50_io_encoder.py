import fsspec
import pytest
import pytest_httpserver

from cacholote import cache, config, extra_encoders, utils


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


@pytest.mark.parametrize("set_cache", ["file", "ftp", "s3"], indirect=True)
def test_copy_from_http_to_cache(
    tmpdir: str,
    httpserver: pytest_httpserver.HTTPServer,
    set_cache: str,
) -> None:

    httpserver.expect_request("/test").respond_with_data(b"test")
    url = httpserver.url_for("/test")
    cached_basename = str(fsspec.filesystem("http").checksum(url))

    cfunc = cache.cacheable(open_url)
    infos = []
    for expected_stats in ((0, 1), (1, 1)):
        dirfs = utils.get_cache_files_dirfs()
        result = cfunc(url)

        # Check hit & miss
        assert config.SETTINGS["cache_store"].stats() == expected_stats

        infos.append(dirfs.info(cached_basename))

        # Check result
        assert result.read() == b"test"

        # Check file in cache
        if set_cache == "ftp":
            assert result.path == f"/{cached_basename}"
        elif set_cache == "s3":
            assert result.path.startswith(
                f"http://127.0.0.1:5555/test-bucket/{cached_basename}"
            )
        else:
            assert result.path == f"{tmpdir}/{cached_basename}"

    # Check cached file is not modified
    assert infos[0] == infos[1]


def test_io_corrupted_files(httpserver: pytest_httpserver.HTTPServer) -> None:
    httpserver.expect_request("/test").respond_with_data(b"test")
    url = httpserver.url_for("/test")
    cached_basename = str(fsspec.filesystem("http").checksum(url))

    cfunc = cache.cacheable(open_url)
    dirfs = utils.get_cache_files_dirfs()
    cfunc(url)

    # Warn if file is corrupted
    dirfs.touch(cached_basename)
    touched_info = dirfs.info(cached_basename)
    with pytest.warns(UserWarning, match="checksum mismatch"):
        result = cfunc(url)
    assert result.read() == b"test"
    assert dirfs.info(cached_basename) != touched_info

    # Warn if file is deleted
    dirfs.rm(cached_basename)
    with pytest.warns(UserWarning, match="No such file or directory"):
        result = cfunc(url)
    assert result.read() == b"test"
    assert dirfs.exists(cached_basename)
