from penny_lab.report import statistics, render, cell

def test_trade_statistics():
    result = statistics([{'net_pnl': v} for v in (30, -10, 0, 10)])
    assert result['wins'] == 2
    assert result['losses'] == 1
    assert result['breakeven'] == 1
    assert result['win_rate'] == .5
    assert result['average_win'] == 20
    assert result['average_loss'] == -10
    assert result['expectancy'] == 7.5
    assert result['profit_factor'] == 4

def test_empty_and_all_winners():
    assert statistics([])['win_rate'] is None
    assert statistics([])['best'] is None
    assert statistics([{'net_pnl': 1}])['profit_factor'] is None
    assert statistics([{'net_pnl': 1}])['no_losses']

def test_failed_run_does_not_invent_equity():
    text = render()
    assert 'No completed backtest' in text
    assert 'Final equity' not in text

def test_completed_zero_trade_run():
    text = render({'summary': {'starting_equity': 2000, 'ending_equity': 2000, 'max_drawdown': 0}, 'trades': []})
    assert 'Final equity' in text
    assert '$2,000.00' in text
    assert 'no trades met' in text

def test_untrusted_table_cells_are_escaped():
    assert cell('<b>|x\ny') == '&lt;b&gt;&#124;x y'
