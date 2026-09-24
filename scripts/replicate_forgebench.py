#!/usr/bin/env python3
"""Plan/freeze/execute a separate exposed-catalog replication; no auto reruns."""
import argparse,asyncio,fcntl,json,os,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from forgerl.bench import replication

def main():
 p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
 g.add_argument('--freeze',action='store_true');g.add_argument('--execute',action='store_true')
 p.add_argument('--prior',type=Path);p.add_argument('--snapshot',type=Path);p.add_argument('--frozen',type=Path)
 p.add_argument('--output',type=Path);p.add_argument('--db',type=Path)
 a=p.parse_args()
 if a.freeze:
  if not all([a.prior,a.snapshot,a.output]):p.error('Prior validated freeze, endpoint snapshot and new output required')
  commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=replication.ROOT,text=True).strip()
  # Verify all executable bytes are actually present in the reviewed commit.
  for rel,expected in replication.sources().items():
   import hashlib
   raw=subprocess.check_output(['git','show',f'{commit}:{rel}'],cwd=replication.ROOT)
   if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('Uncommitted runtime source')
  value=replication.freeze(json.loads(a.prior.read_text()),commit,json.loads(a.snapshot.read_text()))
  a.output.parent.mkdir(parents=True,exist_ok=True)
  with a.output.open('x') as f:json.dump(value,f,indent=2,sort_keys=True);f.write('\n')
  print(json.dumps({'frozen':True,'sha256':value['sha256'],'episodes':value['configuration']['planned_episodes']}));return
 if not a.execute:print(json.dumps(replication.plan(),indent=2));return
 if not a.db or not a.db.is_file() or not a.frozen or not a.output or a.output.exists():p.error('Existing ledger, freeze and new output required; no automatic resume')
 with a.db.with_suffix('.forgebench.lock').open('a') as lock:
  fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
  from forgerl.bench.provider import make_provider
  provider=make_provider(db_path=a.db,profile='openrouter')
  async def execute():
   try:return await replication.run(provider,a.output,json.loads(a.frozen.read_text()))
   finally:await provider.close()
  result=asyncio.run(execute());print(json.dumps({'status':result['status'],'completed':result['completed']}))
  if result['status']!='complete':sys.exit(2)
if __name__=='__main__':main()
