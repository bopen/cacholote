import pathlib
import sqlite3

import fsspec
import pytest
import pytest_httpserver

from cacholote import cache, config, decode, encode, extra_encoders, utils


def open_url(url: str) -> fsspec.spec.AbstractBufferedFile:
    with fsspec.open(url) as f:
        return f


@pytest.mark.parametrize("io_delete_original", [True, False])
def test_dictify_io_object(tmpdir: pathlib.Path, io_delete_original: bool) -> None:
    readonly_dir = tmpdir / "readonly"
    fsspec.filesystem("file").mkdir(readonly_dir)

    tmpfile = tmpdir / "test.txt"
    with open(tmpfile, "wb") as f:
        f.write(b"test")
    tmp_checksum = fsspec.filesystem("file").checksum(tmpfile)

    with config.set(
        io_delete_original=io_delete_original, cache_files_urlpath_readonly=readonly_dir
    ):
        actual = extra_encoders.dictify_io_object(open(tmpfile, "rb"))

    href = f"{readonly_dir}/{tmp_checksum}.txt"
    local_path = f"{tmpdir}/cache_files/{tmp_checksum}.txt"
    checksum = fsspec.filesystem("file").checksum(local_path)
    expected = {
        "type": "python_call",
        "callable": "cacholote.extra_encoders:decode_io_object",
        "args": (
            {
                "type": "text/plain",
                "href": href,
                "file:checksum": checksum,
                "file:size": 4,
                "file:local_path": local_path,
            },
            {},
        ),
        "kwargs": {"mode": "rb"},
    }
    assert actual == expected
    assert fsspec.filesystem("file").exists(tmpfile) is not io_delete_original

    fsspec.filesystem("file").mv(local_path, href)
    assert decode.loads(encode.dumps(actual)).read() == b"test"


@pytest.mark.parametrize(
    "set_cache",
    ["file", "s3"],
    indirect=True,
)
def test_copy_from_http_to_cache(
    tmpdir: pathlib.Path,
    httpserver: pytest_httpserver.HTTPServer,
    set_cache: str,
) -> None:
    if set_cache == "s3":
        cache_dir = "test-bucket"
    else:
        cache_dir = str(tmpdir / "cache_files")

    con = sqlite3.connect(str(tmpdir / "cacholote.db"))
    cur = con.cursor()

    httpserver.expect_request("/test").respond_with_data(b"test")
    url = httpserver.url_for("/test")
    cached_basename = str(fsspec.filesystem("http").checksum(url))

    cfunc = cache.cacheable(open_url)
    infos = []
    for expected_count in (1, 2):
        dirfs = utils.get_cache_files_dirfs()
        result = cfunc(url)

        # Check hits
        cur.execute("SELECT count FROM cacholote")
        assert cur.fetchall() == [(expected_count,)]

        infos.append(dirfs.info(cached_basename))

        # Check result
        assert result.read() == b"test"

        # Check file in cache
        assert result.path == f"{cache_dir}/{cached_basename}"

    # Check cached file is not modified
    assert infos[0] == infos[1]


def test_io_corrupted_files(
    tmpdir: pathlib.Path, httpserver: pytest_httpserver.HTTPServer
) -> None:
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
