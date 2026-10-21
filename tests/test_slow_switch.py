"""镜像测速选源+慢速切换自校验：python tests/test_slow_switch.py

场景: 持续慢→中途切换 / 全程快→不切 / 前慢后快(近期已提速)→不切 /
      aifasthub 自身慢→不二次切 / 非 HF 源慢→不切 /
      测速选源: aifasthub 明显快→选用 / 速度相近→保持 mirror /
      mirror 测速失败→选 aifasthub / 都失败→保持默认 /
      集成: 测速选快源下载 / 小文件不测速
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


def setup_env(chunks_by_host, probe_speeds=None, probe_recorder=None):
    now = [0.0]
    FakeResp._now = now
    if probe_speeds is None:
        probe_speeds = {"hf-mirror.com": 5.0 * MB, "aifasthub.com": 0.5 * MB}
    saved = (qm.time, qm._stream_get, qm._download_direct_inner, qm._probe_speed)
    qm.time = types.SimpleNamespace(time=lambda: now[0])

    stream_urls = []

    def fake_stream_get(url, timeout=1200):
        host = url.split("/")[2]
        assert host in chunks_by_host, f"unexpected host {host}"
        stream_urls.append(url)
        return FakeResp(chunks_by_host[host], 50 * MB)

    qm._stream_get = fake_stream_get

    def fake_probe(url, max_bytes=None):
        if probe_recorder is not None:
            probe_recorder.append(url)
        host = url.split("/")[2]
        return probe_speeds.get(host, 0.0)

    qm._probe_speed = fake_probe

    calls = []
    orig_inner = qm._download_direct_inner

    def counting_inner(url, dest_path, timeout, allow_switch):
        calls.append(url)
        return orig_inner(url, dest_path, timeout, allow_switch)

    qm._download_direct_inner = counting_inner

    def restore():
        qm.time, qm._stream_get, qm._download_direct_inner, qm._probe_speed = saved

    return calls, stream_urls, restore


def test_persist_slow_switches():
    calls, _, restore = setup_env({
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
    calls, _, restore = setup_env({"hf-mirror.com": [(b"x" * MB, float(i + 1)) for i in range(10)]})
    try:
        res = qm._download_direct("https://hf-mirror.com/o/r/resolve/main/a.bin", DEST)
        assert len(calls) == 1 and res["ok"]
    finally:
        restore()


def test_slow_then_fast_no_switch():
    calls, _, restore = setup_env({
        "hf-mirror.com": [(b"x" * MB, 2.0), (b"x" * MB, 4.0)]
                         + [(b"x" * MB, 4.0 + 0.5 * i) for i in range(1, 9)],
    })
    try:
        res = qm._download_direct("https://hf-mirror.com/o/r/resolve/main/a.bin", DEST)
        assert len(calls) == 1 and res["ok"]
    finally:
        restore()


def test_aifasthub_no_second_switch():
    calls, _, restore = setup_env({"aifasthub.com": [(b"x" * MB, 6.0 * (i + 1)) for i in range(6)]})
    try:
        res = qm._download_direct("https://aifasthub.com/o/r/resolve/main/a.bin", DEST)
        assert len(calls) == 1 and res["ok"]
    finally:
        restore()


def test_modelscope_slow_no_switch():
    calls, _, restore = setup_env({"www.modelscope.cn": [(b"x" * MB, 6.0 * (i + 1)) for i in range(6)]})
    try:
        res = qm._download_direct("https://www.modelscope.cn/o/r/resolve/master/a.bin", DEST)
        assert len(calls) == 1 and res["ok"]
    finally:
        restore()


def _pick_with(speeds):
    saved = qm._probe_speed
    qm._probe_speed = lambda url, max_bytes=None: speeds.get(url.split("/")[2], 0.0)
    try:
        return qm._pick_fast_hf_url("https://hf-mirror.com/o/r/resolve/main/a.bin", 50 * MB)
    finally:
        qm._probe_speed = saved


def test_pick_prefers_faster_aifasthub():
    best, note = _pick_with({"hf-mirror.com": 0.5 * MB, "aifasthub.com": 5.0 * MB})
    assert best.split("/")[2] == "aifasthub.com", (best, note)
    assert "选用 aifasthub.com" in note


def test_pick_keeps_mirror_when_similar():
    best, _ = _pick_with({"hf-mirror.com": 2.0 * MB, "aifasthub.com": 2.2 * MB})
    assert best.split("/")[2] == "hf-mirror.com"


def test_pick_alt_when_mirror_dead():
    best, _ = _pick_with({"hf-mirror.com": 0.0, "aifasthub.com": 1.0 * MB})
    assert best.split("/")[2] == "aifasthub.com"


def test_pick_all_dead_keeps_default():
    best, _ = _pick_with({"hf-mirror.com": 0.0, "aifasthub.com": 0.0})
    assert best.split("/")[2] == "hf-mirror.com"


def test_download_uses_probed_fast_source():
    calls, stream_urls, restore = setup_env(
        {
            "hf-mirror.com": [(b"x" * MB, 1.0)] * 10,
            "aifasthub.com": [(b"x" * MB, 1.0)] * 10,
        },
        probe_speeds={"hf-mirror.com": 0.5 * MB, "aifasthub.com": 5.0 * MB},
    )
    try:
        res = qm._download_direct("https://hf-mirror.com/o/r/resolve/main/a.bin", DEST)
        assert res["ok"] and res["downloaded"] == 10 * MB
        assert len(calls) == 1
        assert stream_urls[0].split("/")[2] == "hf-mirror.com"
        assert stream_urls[-1].split("/")[2] == "aifasthub.com", "应用测速选中的快源下载"
    finally:
        restore()


def test_small_file_skips_probe():
    probe_urls = []
    saved_stream = qm._stream_get
    saved_inner = qm._download_direct_inner
    saved_time = qm.time
    now = [0.0]
    qm.time = types.SimpleNamespace(time=lambda: now[0])

    def small_stream_get(url, timeout=1200):
        return FakeResp([(b"x" * MB, 1.0)] * 3, 3 * MB)

    qm._stream_get = small_stream_get

    def fake_probe(url, max_bytes=None):
        probe_urls.append(url)
        return 1.0

    qm._probe_speed = fake_probe
    try:
        res = qm._download_direct("https://hf-mirror.com/o/r/resolve/main/a.bin", DEST)
        assert res["ok"] and res["downloaded"] == 3 * MB
        assert probe_urls == [], "小文件(<=4MB)不应触发测速"
    finally:
        qm._stream_get = saved_stream
        qm._download_direct_inner = saved_inner
        qm.time = saved_time


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
