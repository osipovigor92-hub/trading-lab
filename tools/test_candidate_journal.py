"""Real SQLite persistence, historical evidence, gaps, cursor queries and cache-only collection."""
import copy
import csv
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/trading-panel'))
import candidate_journal as journal
import selection
from market_alerts import MarketAlerts
from market_data import MarketData
from test_market_alerts import evidence
from manual_paper import ManualPaper
from test_manual_paper import Market, plan


class CandidateJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.now=1000
        self.journal=journal.CandidateJournal(self.tmp.name,clock=lambda:self.now)

    def tearDown(self):
        self.tmp.cleanup()

    def cycle(self, packet=None, filters=None, search=''):
        self.journal.cycle(**(packet or evidence(self.now)),scopes=[(filters or selection.DEFAULT_FILTERS,search)],now=self.now)

    def page(self, **changes):
        q={k:[str(v)] for k,v in dict(period='all',**changes).items()}
        return self.journal.page(journal.parse_query(q,self.now))

    def test_durable_first_evidence_and_coalesced_unique_source_samples(self):
        self.cycle();first=self.page()['rows'][0];self.cycle()
        self.assertEqual(self.page()['total'],1);self.assertEqual(self.page()['rows'][0]['samples'],1)
        self.now+=10;packet=evidence(self.now,price=101);self.cycle(packet)
        saved=self.page()['rows'][0]
        self.assertEqual(saved['samples'],2);self.assertEqual(saved['first_seen'],1000)
        self.assertEqual(saved['last_seen'],1010);self.assertEqual(saved['evidence'],first['evidence'])
        self.assertEqual(saved['evidence']['price'],100)
        restarted=journal.CandidateJournal(self.tmp.name,clock=lambda:self.now)
        restarted.cycle(**packet,scopes=[(selection.DEFAULT_FILTERS,'')],now=self.now)
        self.assertEqual(restarted.page(journal.parse_query({'period':['all']},self.now))['rows'][0]['samples'],2)

    def test_known_rejections_include_outside_shortlist_and_unknowns_do_not_fail(self):
        packet=evidence(self.now);low=dict(packet['tickers']['rows'][0],symbol='LOWUSDT',turnover=2e6)
        packet['tickers']['rows'].append(low);self.cycle(packet)
        rows={r['symbol']:r for r in self.page()['rows']}
        self.assertEqual(rows['LOWUSDT']['status'],'rejected')
        checks={c['key']:c for c in rows['LOWUSDT']['evidence']['checks']}
        self.assertEqual(checks['turnover']['value'],2e6);self.assertEqual(checks['turnover']['min'],20e6)
        self.assertEqual(checks['depth']['state'],'pending');self.assertEqual(checks['oi']['state'],'pass')
        self.assertEqual(rows['BTCUSDT']['status'],'passed')
        self.now+=10;unknown=evidence(self.now);unknown['tickers']['rows'][0]['open_interest']=None;self.cycle(unknown)
        self.assertEqual(self.page()['rows'][0]['status'],'pending')
        self.assertEqual(self.page()['summary']['reasons'][0]['key'],'turnover')

    def test_errors_alignment_future_and_stale_sources_never_confirm(self):
        for source,change in [('charts',dict(refresh_error='API failed')),('books',dict(updated=900)),
                              ('books',dict(mid=101)),('charts',dict(updated=1100)),('books',dict(symbol='ETHUSDT'))]:
            with self.subTest(source=source,change=change):
                packet=evidence(self.now);packet[source]['BTCUSDT'].update(change)
                self.cycle(packet);latest=self.page()['rows'][0]
                self.assertEqual(latest['status'],'pending');self.assertIsNone(latest['evidence']['rating']['score'])
                self.now+=10
        self.cycle(evidence(self.now));self.assertEqual(self.page()['rows'][0]['status'],'passed')
        previous=self.page()['total'];self.now+=10;old=evidence(900);self.cycle(old)
        self.assertEqual(self.page()['rows'][0]['kind'],'gap');self.assertEqual(self.page()['total'],previous+1)

    def test_source_rollback_does_not_rewrite_or_make_new_decision(self):
        self.cycle();self.now+=2;packet=evidence(999,rvol=.5);self.cycle(packet)
        self.assertEqual(self.page()['total'],1);self.assertEqual(self.page()['rows'][0]['status'],'passed')

    def test_filter_scopes_gap_recovery_and_restart_preserve_records(self):
        self.cycle();self.now+=10;filters=dict(selection.DEFAULT_FILTERS,rvol_min=2);self.cycle(filters=filters,search='BTC')
        self.assertEqual(self.page()['total'],2);self.assertEqual(self.page(scope='default')['total'],1)
        self.now+=60;restarted=journal.CandidateJournal(self.tmp.name,clock=lambda:self.now);self.journal=restarted;self.cycle()
        rows=self.page()['rows'];self.assertTrue(any(r['kind']=='gap' for r in rows))
        self.assertEqual(sum(r['kind']=='candidate' for r in rows),3)
        self.assertTrue(self.page()['collector']['collecting'])

    def test_gaps_never_bridge_a_successful_collection_between_errors(self):
        self.cycle();self.assertEqual(sum(r['kind']=='gap' for r in self.page()['rows']),0)
        self.now+=10;bad=dict(status='error',updated=0);packet=evidence(self.now);packet['tickers']=bad;self.cycle(packet)
        self.now+=10;self.cycle()
        self.now+=10;packet=evidence(self.now);packet['tickers']=bad;self.cycle(packet)
        gaps=[r for r in self.page()['rows'] if r['kind']=='gap']
        self.assertEqual(len(gaps),2);self.assertTrue(all(r['first_seen']==r['last_seen'] for r in gaps))

    def test_alerts_captured_at_transition_and_not_deleted_after_expiry_or_restart(self):
        monitor=MarketAlerts(event_sink=self.journal.event);key=monitor.register(selection.DEFAULT_FILTERS,'',self.now)
        packet=evidence(self.now);monitor.update(key,**packet,now=self.now)
        signals=self.page(status='signal')['rows'];self.assertEqual(len(signals),2)
        self.assertEqual({r['evidence']['event']['kind'] for r in signals},{'ready','near_level'})
        self.now+=20;monitor.update(key,**evidence(self.now),now=self.now)
        self.assertEqual(self.page(status='signal')['total'],2)
        # A new monitor replays the exact same source evidence once; persistent key suppresses it.
        restarted=MarketAlerts(event_sink=self.journal.event);key=restarted.register(selection.DEFAULT_FILTERS,'',1000)
        restarted.update(key,**packet,now=1000);self.assertEqual(self.page(status='signal')['total'],2)
        self.now+=300;self.assertEqual(self.page(status='signal')['total'],2)

    def test_cursor_filters_learning_multiple_causes_and_lossless_csv_page(self):
        for i in range(5):
            packet=evidence(self.now,rvol=.5 if i%2 else 1.2,depth=1000 if i%2 else 8000)
            self.cycle(packet);self.now+=10
        first=self.page(limit=2);second=self.page(limit=2,before=first['next_before'],anchor=first['query']['anchor'])
        self.assertEqual(len(first['rows']),2);self.assertFalse({r['id'] for r in first['rows']}&{r['id'] for r in second['rows']})
        self.assertEqual(self.page(status='rejected')['total'],2)
        causes=self.page()['summary']['reasons'];self.assertEqual({r['key']:r['count'] for r in causes},{'depth':2,'rvol':2})
        csv_rows=list(csv.DictReader(io.StringIO(journal.csv_page(first).decode('utf-8-sig'))))
        self.assertEqual(len(csv_rows),2);self.assertEqual(json.loads(csv_rows[0]['evidence_json']),first['rows'][0]['evidence'])
        self.assertEqual(self.page(search='ETH')['total'],0)

    def test_capacity_write_failure_and_corrupt_db_preserve_history(self):
        self.journal.max_records=1;self.cycle();original=self.page()['rows'][0]
        self.now+=10;self.cycle(evidence(self.now,rvol=.5));failed=self.page()
        self.assertEqual(failed['status'],'partial');self.assertEqual(failed['rows'][0],original)
        self.assertFalse(failed['collector']['collecting']);self.assertEqual(failed['total'],1)
        with patch.object(self.journal,'connect',side_effect=sqlite3.OperationalError('read-only disk')):
            self.cycle();self.assertIn('read-only disk',self.journal.error)
        with tempfile.TemporaryDirectory() as bad:
            p=Path(bad)/'candidates.sqlite3';p.write_bytes(b'original corrupt data')
            broken=journal.CandidateJournal(bad);self.assertFalse(broken.installed);self.assertEqual(p.read_bytes(),b'original corrupt data')

    def test_bounded_cache_collection_without_browser_or_extra_jobs(self):
        market=MarketData(api=lambda *a,**k: (_ for _ in ()).throw(AssertionError('No upstream request')),journal=self.journal)
        try:
            packet=evidence(self.now)
            market.entries[('screener','','')]=dict(data=packet['tickers'])
            market.entries[('chart','BTCUSDT','1')]=dict(data=packet['charts']['BTCUSDT'])
            market.entries[('book','BTCUSDT','')]=dict(data=packet['books']['BTCUSDT'])
            market.book_history['BTCUSDT']=packet['histories']['BTCUSDT']
            market._journal_tick(self.now);self.assertEqual(self.page(status='passed')['total'],1)
            self.assertEqual(self.page(status='signal')['total'],2)
            market._journal_tick(self.now+1);self.assertEqual(self.page(status='passed')['rows'][0]['samples'],1)
            self.assertEqual(market.pool._max_workers,2);self.assertEqual(len(market.entries),3)
        finally:market.close()

    def test_query_validation_and_csv_formula_protection(self):
        for q in ({'limit':['51']},{'limit':['1','2']},{'search':['BTC%']},{'before':['-1']},{'anchor':['1100']},{'status':['ready']},{'unknown':['x']}):
            with self.assertRaises(ValueError):journal.parse_query(q,self.now)
        csv_rows=list(csv.DictReader(io.StringIO(journal.csv_page(dict(rows=[dict(id='safe',net=-1,reason='=HYPERLINK("bad")')]),True).decode('utf-8-sig'))))
        self.assertEqual(csv_rows[0]['net'],'-1');self.assertTrue(csv_rows[0]['reason'].startswith("'="))

    def test_manual_full_history_pages_read_only_preserve_account_commands_and_gaps(self):
        market=Market();paper=ManualPaper(market,self.tmp.name,clock=lambda:market.now)
        for i in range(25):
            a=paper.snapshot();paper.command(dict(id=f'journal-open-{i}',action='open',generation=a['generation'],plan=plan()))
            paper.command(dict(id=f'journal-close-{i}',action='close',generation=paper.snapshot()['generation']))
        before=paper.path.read_bytes();a=paper.snapshot();first=paper.journal(limit=20);second=paper.journal(before=first['next_before'],limit=20)
        self.assertEqual(first['total'],25);self.assertEqual(len(first['rows']),20);self.assertEqual(len(second['rows']),5)
        self.assertFalse({r['id'] for r in first['rows']}&{r['id'] for r in second['rows']})
        self.assertEqual(paper.path.read_bytes(),before);self.assertEqual(paper.snapshot()['generation'],a['generation'])
        self.assertEqual(paper.snapshot()['balance'],a['balance']);self.assertEqual(len(paper.snapshot()['trades']),20)
        reopened=ManualPaper(market,self.tmp.name,clock=lambda:market.now);self.assertEqual(reopened.journal()['total'],25)
