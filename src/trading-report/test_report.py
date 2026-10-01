import json,sqlite3,tempfile,unittest
from pathlib import Path
import report

class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.db=report.connect(self.root/'archive.sqlite')
 def tearDown(self):self.db.close();self.tmp.cleanup()
 def trade(self,opened=100,closed=200,net=-.23):
  return dict(symbol='TEST',side=1,opened=opened,closed=closed,net=net,gross=net+.11,entry_fee=.055,exit_fee=.055,funding=0)
 def test_idempotent_archive_and_immutable(self):
  r=self.trade();report.archive(self.db,'A',[r,r]);self.assertEqual(report.comparison(self.db,0,300)['A']['count'],1)
  with self.assertRaises(ValueError):report.archive(self.db,'A',[dict(r,net=1)])
 def test_common_window(self):
  report.archive(self.db,'A',[self.trade(50,150),self.trade(101,201),self.trade(150,301)])
  s=report.comparison(self.db,100,300)['A'];self.assertEqual(s['count'],1);self.assertEqual(s['crossing_excluded'],1);self.assertAlmostEqual(s['net'],-.23)
 def test_metrics_and_empty(self):
  s=report.stats([self.trade(net=1),self.trade(net=-.5)])
  self.assertEqual(s['profit_factor'],2);self.assertEqual(s['win_rate'],50);self.assertAlmostEqual(s['gross']-s['fees']+s['funding'],s['net'])
  self.assertIsNone(report.stats([])['average']);self.assertIsNone(report.stats([])['profit_factor'])
 def test_ingest_dedup_freshness_whole_minutes(self):
  path=self.root/'history.sqlite';src=sqlite3.connect(path);src.execute('CREATE TABLE samples(t REAL PRIMARY KEY,data TEXT)')
  for t in [121.,126.]:
   src.execute('INSERT INTO samples VALUES(?,?)',(t,json.dumps(dict(phase='running',observations=[dict(symbol='X',time=t,ready=False,warmup_remaining=20,reasons=['Накопление потока или нет свежих сделок','cost','cost']),dict(symbol='STALE',time=t-30,ready=True,reasons=[])]))))
  src.commit();src.close()
  self.assertEqual(report.ingest(self.db,path),2);self.assertEqual(report.ingest(self.db,path),0)
  d=report.diagnostics(self.db,120,180)['rows'];self.assertEqual(len(d),1);self.assertEqual(d[0]['samples'],2)
  self.assertEqual({v['reason']:v['n'] for v in d[0]['reasons']},{'Прогрев потока':2,'cost':2})
  self.assertEqual(report.diagnostics(self.db,121,180)['rows'],[])
 def test_import_rollback(self):
  path=self.root/'history.sqlite';src=sqlite3.connect(path);src.execute('CREATE TABLE samples(t REAL PRIMARY KEY,data TEXT)');src.execute("INSERT INTO samples VALUES(100,'bad json')");src.commit();src.close()
  with self.assertRaises(ValueError):report.ingest(self.db,path)
  self.assertIsNone(self.db.execute("SELECT v FROM meta WHERE k='cursor'").fetchone())
 def test_atomic_report(self):
  old=report.ROOT;report.ROOT=self.root
  try:
   report.save({'status':'ok'});self.assertEqual(json.loads((self.root/'report.json').read_text())['status'],'ok');self.assertFalse((self.root/'report.tmp').exists())
  finally:report.ROOT=old

if __name__=='__main__':unittest.main()
