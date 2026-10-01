"""Version-checked updates for panel/report/signals only. Never restarts trading models."""
import argparse
import ast
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from urllib.request import urlopen

REPO=Path(__file__).resolve().parents[1]
TRACK=Path('/var/lib/trading-lab-deploy')
ALLOWED={'trading-panel','trading-report','trading-signals'}

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

def destination(name):
    bits=Path(name).parts
    if len(bits)==3 and bits[0]=='src' and bits[1] in (
        'trading-panel','trading-report','trading-signals','trading-bot','trading-live',
        'trading-scanner','trading-scalp','scalp-paper','scalp-model-b'):
        if bits[2].startswith('.') or Path(bits[2]).suffix not in ('.py','.js','.css','.html'):
            raise ValueError('Invalid source: '+name)
        return Path('/opt')/bits[1]/bits[2]
    if len(bits)==2 and bits[0]=='deploy' and Path(bits[1]).suffix in ('.service','.timer'):
        return Path('/etc/systemd/system')/bits[1]
    raise ValueError('Invalid deployment path: '+name)

def inventory():
    result={}
    for folder in ('src','deploy'):
        for p in sorted((REPO/folder).rglob('*')):
            if '__pycache__' in p.parts or p.suffix=='.pyc' or p.name=='baseline.json':continue
            if p.is_symlink():raise RuntimeError('Symlink in source')
            if p.is_file():
                name=str(p.relative_to(REPO));destination(name);result[name]=digest(p)
    return result

def plan(expected,target):
    changed=[]
    for name in sorted(expected.keys() | target.keys()):
        p=destination(name)
        if p.is_symlink() or any(x.is_symlink() for x in p.parents):raise RuntimeError('Symlink: '+str(p))
        if digest(p)!=expected.get(name):raise RuntimeError('Server differs from recorded version: '+str(p))
        if expected.get(name)!=target.get(name):
            parts=Path(name).parts
            if parts[0]!='src' or parts[1] not in ALLOWED:
                raise RuntimeError('Separate model/unit migration required: '+name)
            changed.append(name)
    return changed

def atomic(path,body,mode=0o644):
    fd,name=tempfile.mkstemp(prefix='.lab-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(body);f.flush();os.fsync(f.fileno())
        os.chmod(name,mode);os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

def system(*args):
    subprocess.run(['systemctl',*args],check=True,timeout=130)

def active(unit):
    return subprocess.run(['systemctl','is-active','--quiet',unit],timeout=10).returncode==0

def health(changed):
    paths=['/','/api/paper','/api/model-b']
    if any('/trading-report/' in p for p in changed):paths+=['/api/lab-report','/api/journal-a','/api/journal-b']
    if any('/trading-signals/' in p for p in changed):paths+=['/api/signals']
    for attempt in range(20):
        try:
            for path in paths:
                with urlopen('http://127.0.0.1:8787'+path,timeout=3) as r:
                    data=r.read()
                    if path.startswith('/api/'):
                        obj=json.loads(data)
                        if not isinstance(obj,dict):raise ValueError(path)
                        # Halted models may be intentional; never reset or restart them.
            return
        except Exception:
            if attempt==19:raise
            time.sleep(1)

def apply(expected,target,changed,revision):
    services=[]
    if any('/trading-panel/' in p for p in changed):services.append('trading-panel.service')
    if any('/trading-signals/' in p for p in changed):services.append('trading-signals.service')
    reports=any('/trading-report/' in p for p in changed)
    for unit in services:
        if not active(unit):raise RuntimeError('Service is not active: '+unit)
    if reports and not active('trading-report.timer'):raise RuntimeError('Report timer is not active')
    backup=TRACK/('backup-'+time.strftime('%Y%m%dT%H%M%S')+'-'+revision[:8])
    backup.mkdir(mode=0o700)
    old={}
    for name in changed:
        p=destination(name)
        old[name]=(p.read_bytes(),p.stat().st_mode & 0o777) if p.exists() else None
        if old[name]:
            saved=backup/name;saved.parent.mkdir(parents=True,exist_ok=True);saved.write_bytes(old[name][0])
    (backup/'manifest.json').write_text(json.dumps(dict(expected=expected,target=target,changed=changed,revision=revision),indent=2))
    stopped=[];report_stopped=False
    try:
        if reports:
            report_stopped=True;system('stop','trading-report.timer');system('stop','trading-report.service')
        for unit in services:
            stopped.append(unit);system('stop',unit)
        # Detect writes made since preflight before touching installed code.
        plan(expected,target)
        for name in changed:
            p=destination(name)
            if name in target:atomic(p,(REPO/name).read_bytes(),old[name][1] if old[name] else 0o644)
            else:p.unlink()
        for unit in services:system('start',unit)
        if reports:system('start','trading-report.service')
        health(changed)
        if reports:system('start','trading-report.timer')
        atomic(TRACK/'installed.json',json.dumps(dict(revision=revision,files=target,backup=str(backup)),indent=2).encode(),0o600)
    except BaseException:
        for unit in stopped:
            subprocess.run(['systemctl','stop',unit],timeout=30)
        for name in changed:
            p=destination(name)
            if old[name]:atomic(p,*old[name])
            elif p.exists():p.unlink()
        for unit in stopped:system('start',unit)
        if report_stopped:system('start','trading-report.timer')
        print('Update failed. Previous source restored. Backup:',backup,flush=True)
        raise
    print('UPDATED',revision,'Backup:',backup)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if os.geteuid()!=0:raise SystemExit('Run on the server as root')
    TRACK.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (TRACK/'deploy.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        revision=subprocess.check_output(['git','-C',str(REPO),'rev-parse','HEAD'],text=True).strip()
        if subprocess.check_output(['git','-C',str(REPO),'status','--porcelain'],text=True).strip():
            raise SystemExit('Checkout must be clean')
        state=TRACK/'installed.json'
        expected=json.loads(state.read_text())['files'] if state.exists() else json.loads((REPO/'deploy/baseline.json').read_text())
        target=inventory();changed=plan(expected,target)
        for name in changed:
            if name.endswith('.py') and name in target:ast.parse((REPO/name).read_text(),filename=name)
        print('Revision:',revision,'Changed files:',len(changed))
        for name in changed:print(name)
        if not args.apply:
            print('CHECK ONLY. Use --apply after review.');return
        if not changed:
            atomic(state,json.dumps(dict(revision=revision,files=target),indent=2).encode(),0o600)
            print('BASELINE REGISTERED. No services restarted.');return
        apply(expected,target,changed,revision)

if __name__=='__main__':main()
