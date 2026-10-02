"""First-install/idempotent bootstrap for C/D only; upgrades require a separate migration."""
import ast
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import tempfile
import time
import deploy

REPO=Path(__file__).resolve().parents[1]
ROOT=Path('/var/lib/trading-research')
CODE=Path('/opt/trading-research')
UNIT=Path('/etc/systemd/system/trading-research.service')
TRACK=Path('/var/lib/trading-lab-deploy')
MANIFEST=TRACK/'research-installed.json'
SERVICE='trading-research.service'


def no_symlink(path):
    if path.is_symlink() or any(p.is_symlink() for p in path.parents): raise RuntimeError('Symlink: '+str(path))


def preflight(target,installed):
    for path,body in target.items():
        no_symlink(path)
        if installed:
            expected=installed['files'].get(str(path))
            if expected != hashlib.sha256(body).hexdigest(): raise RuntimeError('Изменение установленной версии требует отдельной миграции C/D')
            if not path.is_file() or deploy.digest(path)!=expected: raise RuntimeError('Локальные изменения: '+str(path))
        elif path.exists(): raise RuntimeError('Путь уже существует без записи установщика: '+str(path))


def health(start):
    for _ in range(20):
        try:
            r=json.loads((ROOT/'report.json').read_text())
            if r['updated']>=start and set(r['models'])=={'C','D'} and deploy.active(SERVICE): return r
        except (OSError,ValueError,KeyError): pass
        time.sleep(.5)
    raise RuntimeError('Новая служба не опубликовала свежий отчёт')


def install(target,revision,owner):
    installed=json.loads(MANIFEST.read_text()) if MANIFEST.exists() else None
    preflight(target,installed)
    if installed:
        if deploy.active(SERVICE): print('C/D уже установлены и работают. Перезапуска не было.');return
        deploy.system('start',SERVICE);r=health(time.time()-2)
        print('C/D запущены с сохранённым состоянием:',{k:v['phase'] for k,v in r['models'].items()});return
    # Refuse untracked prior state rather than silently adopt/reset an experiment.
    if ROOT.exists() and any(ROOT.iterdir()): raise RuntimeError('В каталоге C/D уже есть состояние; нужна проверка миграции')
    if CODE.exists() and any(CODE.iterdir()): raise RuntimeError('Каталог исходников C/D не пуст')
    known=subprocess.run(['systemctl','show',SERVICE,'-p','LoadState','--value'],capture_output=True,text=True,check=True,timeout=10)
    if known.stdout.strip() not in ('','not-found'): raise RuntimeError('Служба C/D уже существует')
    ROOT.mkdir(mode=0o700,exist_ok=True);os.chown(ROOT,owner.pw_uid,owner.pw_gid);os.chmod(ROOT,0o700)
    CODE.mkdir(mode=0o755,exist_ok=True)
    started=False
    try:
        for path,body in target.items(): deploy.atomic(path,body,0o644)
        deploy.system('daemon-reload');stamp=time.time();started=True;deploy.system('start',SERVICE)
        r=health(stamp)
        deploy.system('enable',SERVICE)
        manifest=dict(revision=revision,files={str(p):hashlib.sha256(b).hexdigest() for p,b in target.items()})
        deploy.atomic(MANIFEST,json.dumps(manifest,indent=2).encode(),0o600)
    except BaseException:
        if started:
            subprocess.run(['systemctl','disable','--now',SERVICE],timeout=30)
        for path in target:
            if path.exists(): path.unlink()
        subprocess.run(['systemctl','daemon-reload'],timeout=30)
        print('Установка отменена. Состояние C/D, если создано, сохранено для диагностики. A/B и VPN не затронуты.')
        raise
    print('C/D PAPER установлены:',{k:v['phase'] for k,v in r['models'].items()})
    print('SQLite-журнал:',ROOT/'journal.sqlite')


def main():
    if os.geteuid()!=0: raise SystemExit('Запусти от root')
    for path in (ROOT,CODE,UNIT,TRACK,MANIFEST): no_symlink(path)
    if not TRACK.is_dir(): raise SystemExit('Сначала установи панель через tools/update.sh')
    owner=pwd.getpwnam('tradingbot')
    with (TRACK/'deploy.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        revision=subprocess.check_output(['git','-C',str(REPO),'rev-parse','HEAD'],text=True).strip()
        if subprocess.check_output(['git','-C',str(REPO),'status','--porcelain'],text=True).strip(): raise RuntimeError('Checkout must be clean')
        registered=json.loads((TRACK/'installed.json').read_text())
        if registered['revision']!=revision: raise RuntimeError('Сначала обнови панель до этой версии')
        deploy.plan(registered['files'],deploy.inventory())
        source=REPO/'integrations/research'
        target={CODE/'engine.py':(source/'engine.py').read_bytes(),UNIT:(source/'trading-research.service').read_bytes()}
        ast.parse(target[CODE/'engine.py'])
        subprocess.run(['/usr/bin/python3','-B',str(source/'test_engine.py')],check=True,timeout=30)
        install(target,revision,owner)

if __name__=='__main__':main()
