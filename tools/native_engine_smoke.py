"""Native dependency/API check with synthetic prices. No exchange or production access."""
import json
import math
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO/'integrations/platforms'))
import runner


def candles():
    start = 1704067200000
    rows=[]
    for i in range(3180):
        p=100+4*math.sin(i/90)
        rows.append([start+i*60000, p, p+.01, p+.12, p-.12, 20.])
    return rows


def main(engine):
    info=runner.probe(engine)
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary)
        if engine=='freqtrade':
            import pandas as pd
            from freqtrade.commands.arguments import Arguments
            from freqtrade.configuration import Configuration
            from freqtrade.enums import RunMode
            from freqtrade.resolvers import StrategyResolver
            config_file=root/'config.json'
            runner.atomic(config_file,runner.ft_config())
            args=Arguments(['backtesting','--config',str(config_file),'--strategy','LabEMATest',
                '--strategy-path',str(runner.HERE),'--userdir',str(root),
                '--export-directory',str(root/'results')]).get_parsed_arg()
            config=Configuration(args,RunMode.BACKTEST).get_config()
            strategy=StrategyResolver.load_strategy(config)
            data=pd.DataFrame(candles(),columns=['date','open','close','high','low','volume'])
            data['date']=pd.to_datetime(data['date'],unit='ms',utc=True)
            df=strategy.populate_indicators(data,{'pair':'BTC/USDT:USDT'})
            df=strategy.populate_entry_trend(df,{'pair':'BTC/USDT:USDT'})
            df=strategy.populate_exit_trend(df,{'pair':'BTC/USDT:USDT'})
            assert df['enter_long'].sum()>0 and df['enter_short'].sum()>0
            assert config['dry_run'] is True
            assert 'api_server' not in config and 'telegram' not in config
        elif engine=='jesse':
            from datetime import datetime, timezone
            rows=candles();start=datetime.fromtimestamp(rows[300][0]/1000,timezone.utc)
            end=datetime.fromtimestamp((rows[-1][0]+60000)/1000,timezone.utc)
            # Use the real native backtest API, with only its public data loader replaced.
            with patch.object(runner,'period',return_value=(start,end)),patch.object(runner,'bybit_candles',return_value=rows):
                metrics,trades=runner.jesse(root,lambda **kw:None)
            assert metrics['count']>0,metrics
            assert isinstance(metrics['net'],(int,float)) and math.isfinite(metrics['net'])
            assert len(trades)==metrics['count'],(len(trades),metrics)
            assert (root/'native-result.json').is_file()
        else:
            raise ValueError('Native CI checks support Freqtrade and Jesse only')
    print(json.dumps(dict(status='ok',engine=info['engine'],version=info['version'],
                         data='synthetic compatibility check, not a profitability result')))


if __name__=='__main__':
    main(sys.argv[1])
