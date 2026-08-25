from pathlib import Path

def test_scheduler_has_no_signal_creation_reference():
    text=Path('app/scheduler/monitor.py').read_text(encoding='utf-8')
    assert 'best_stock(' not in text
    assert 'best_equity_option(' not in text
    assert 'best_index_option(' not in text
