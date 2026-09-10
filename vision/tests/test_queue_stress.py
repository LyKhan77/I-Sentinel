import json

from vision.transport.queue import DiskQueue


def test_stress_multithread_put(tmp_path):
    q = DiskQueue(str(tmp_path), max_bytes=1_000_000_000)
    results = []

    import threading

    def worker():
        for i in range(50):
            q.put({"w": threading.get_ident(), "i": i})

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    seqs = [s for s, _ in q._files()]
    assert q.size() == 400
    assert len(set(seqs)) == 400, "duplicate seqs -> overwrites/lost events"
    for seq in seqs[:3]:
        with open(f"{tmp_path}/{seq:012d}.json", encoding="utf-8") as f:
            json.load(f)  # no truncated files
