"""慢速切换判定自校验：python tests/test_slow_switch.py

场景: 持续慢→切换 / 全程快→不切 / 前慢后快(近期已提速)→不切 /
      aifasthub 自身慢→不二次切 / 非 HF 源慢→不切
"""
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import qibo_modelscope as qm

MB = 1024 * 1024
DEST = os.path.join(tempfile.mkdtemp(prefix="qibo_sw_"), "a.bin")


class FakeResp:
    _now = [0.0]

    def __init__(self, chunks, content_length):
        self._chunks = chunks
        self.headers = {"Content-Length": str(content_length)}

    def iter_content(self, _):
        for data, ts in self._chunks:
            self._now[0] = ts
            yield data

    def close(self):
        pass


def setup_env(chunks_by_host):
    now = [0.0]
    FakeResp._now = now
    saved = (qm.time, qm._stream_get, qm._download_direct_inner)
    qm.time = types.SimpleNamespace(time=lambda: now[0])

    def fake_stream_get(url, timeout=1200):
        host = url.split("/")[2]
        assert host in chunks_by_host, f"unexpected host {host}"
        return FakeResp(chunks_by_host[host], 50 * MB)

    qm._stream_get = fake_stream_get

    calls = []
    orig_inner = qm._download_direct_inner

    def counting_inner(url, dest_path, timeout, allow_switch):
        calls.append(url)
        return orig_inner(url, dest_path, timeout, allow_switch)

    qm._download_direct_inner = counting_inner

    def restore():
        qm.time, qm._stream_get, qm._download_direct_inner = saved

    return calls, restore


def test_persist_slow_switches():
    calls, restore = setup_env({
        "hf-mirror.com": [(b"x" * MB, 5.0), (b"x" * MB, 10.0), (b"x" * MB, 15.0), (b"x" * MB, 20.0)],
        "aifasthub.com": [(b"x" * MB, 21.0 + i) for i in range(6)],
    })
    try:
        res = qm._download_direct("https://hf-mirror.com/o/r/resolve/main/a.bin", DEST)
        hosts = [u.split("/")[2] for u in calls]
        assert hosts == ["hf-mirror.com", "aifasthub.com"], hosts
        assert res["ok"] and res["downloaded"] == 6 * MB
    finally:
        restore()


def test_fast_no_switch():
    calls, restore = setup_env({"hf-mirror.com": [(b"x" * MB, float(i + 1)) for i in range(10)]})
    try:
        res = qm._download_direct("https://hf-mirror.com/o/r/resolve/main/a.bin", DEST)
        assert len(calls) == 1 and res["ok"]
    finally:
        restore()


def test_slow_then_fast_no_switch():
    calls, restore = setup_env({
        "hf-mirror.com": [(b"x" * MB, 2.0), (b"x" * MB, 4.0)]
                         + [(b"x" * MB, 4.0 + 0.5 * i) for i in range(1, 9)],
    })
    try:
        res = qm._download_direct("https://hf-mirror.com/o/r/resolve/main/a.bin", DEST)
        assert len(calls) == 1 and res["ok"]
    finally:
        restore()


def test_aifasthub_no_second_switch():
    calls, restore = setup_env({"aifasthub.com": [(b"x" * MB, 6.0 * (i + 1)) for i in range(6)]})
    try:
        res = qm._download_direct("https://aifasthub.com/o/r/resolve/main/a.bin", DEST)
        assert len(calls) == 1 and res["ok"]
    finally:
        restore()


def test_modelscope_slow_no_switch():
    calls, restore = setup_env({"www.modelscope.cn": [(b"x" * MB, 6.0 * (i + 1)) for i in range(6)]})
    try:
        res = qm._download_direct("https://www.modelscope.cn/o/r/resolve/master/a.bin", DEST)
        assert len(calls) == 1 and res["ok"]
    finally:
        restore()


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
