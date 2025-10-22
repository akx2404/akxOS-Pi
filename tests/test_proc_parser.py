from scripts.process_info import get_process_stats
def test_parser_runs():
    data = get_process_stats()
    assert isinstance(data, list)
    assert "pid" in data[0]
