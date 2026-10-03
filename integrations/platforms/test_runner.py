import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile
import runner


class RunnerTests(unittest.TestCase):
    def test_candles_reject_gaps_future_and_bad_values(self):
        valid=[[0.,100.,101.,102.,99.,10.],[60000.,101.,100.,102.,99.,12.]]
        self.assertEqual(runner.validate_candles(valid,0,120000),valid)
        for rows,end in [([valid[0],dict()],120000),([valid[0]],120000),
                         ([valid[0],[120000.,101.,100.,102.,99.,12.]],180000),
                         ([valid[0],[60000.,101.,100.,102.,float('nan'),12.]],120000)]:
            with self.assertRaises((ValueError,TypeError)):runner.validate_candles(rows,0,end)
    def test_settings_never_enable_real_trading(self):
        c=runner.ft_config();self.assertIs(c['dry_run'],True)
        self.assertEqual(c['exchange']['key'],'');self.assertEqual(c['exchange']['secret'],'')
        self.assertNotIn('api_server',c);self.assertNotIn('telegram',c)
        self.assertEqual(c['max_open_trades'],1);self.assertEqual(c['stake_amount'],100)
    def test_native_zip_result_and_zero_trades(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            for count,net in [(2,-.3),(0,0.)]:
                data=dict(strategy={'LabEMATest':dict(total_trades=count,profit_total_abs=net,wins=1 if count else 0,max_drawdown_account=.001,trades=[])})
                with ZipFile(folder/'native.zip','w') as z:
                    z.writestr('backtest-result.json',json.dumps(data));z.writestr('config.json',json.dumps({'dry_run':True}))
                metrics,trades=runner.parse_ft(folder)
                self.assertEqual(metrics['count'],count);self.assertEqual(metrics['net'],net)
                self.assertEqual(metrics['drawdown_pct'],.1);self.assertEqual(trades,[])
    def test_freqtrade_error_from_native_log_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'results';folder.mkdir()
            (folder.parent/'native.log').write_text(
                "2026-10-03 14:49:09 - freqtrade.configuration - CRITICAL - Invalid configuration. Reason: 'token' is required\n")
            with self.assertRaisesRegex(ValueError,'Invalid configuration'):
                runner.parse_ft(folder)
    def test_nonfinite_native_metrics_are_explicitly_unavailable(self):
        self.assertEqual(runner.clean(dict(x=float('nan'),pf=float('inf'),zero=0)),dict(x=None,pf=None,zero=0))


if __name__=='__main__':unittest.main()
