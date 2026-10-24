from scripts.bench_latency import percentile


def test_percentile_nearest_rank():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    assert percentile(xs, 50) == 5.0
    assert percentile(xs, 95) == 10.0
    assert percentile([3.0], 50) == 3.0
    assert percentile([], 50) == 0.0
