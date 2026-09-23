"""Read the effective limits inside the exact deployed sandbox image."""
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from forgerl.sandbox import docker_command

probe='''import errno,json,os,socket
from pathlib import Path
status=dict(line.split(":",1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
try:
 Path("/tmp/forgerl-write-probe").write_text("x")
 readonly=False
except OSError as e:
 readonly=e.errno==errno.EROFS
print(json.dumps({"uid":os.getuid(),"memory_max":Path("/sys/fs/cgroup/memory.max").read_text().strip(),"cpu_max":Path("/sys/fs/cgroup/cpu.max").read_text().strip(),"pids_max":Path("/sys/fs/cgroup/pids.max").read_text().strip(),"interfaces":[name for _,name in socket.if_nameindex()],"read_only":readonly,"cap_eff":status["CapEff"].strip(),"no_new_privs":status["NoNewPrivs"].strip(),"seccomp":status["Seccomp"].strip()}))
'''
image=Path('/etc/forgerl/sandbox-image').read_text().strip()
name='forgerl-isolation-'+uuid.uuid4().hex[:12]
command=docker_command(image,name)
command=command[:-1]+['--entrypoint','python',command[-1],'-I','-B','-c',probe]
try:
 result=json.loads(subprocess.check_output(command,timeout=20))
finally:
 subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5,check=False)
assert result['uid']==65534
assert result['memory_max']=='134217728' and result['pids_max']=='32'
quota,period=map(int,result['cpu_max'].split());assert quota/period==0.5
assert result['interfaces']==['lo'] and result['read_only']
assert int(result['cap_eff'],16)==0 and result['no_new_privs']=='1' and result['seccomp']=='2'
info=json.loads(subprocess.check_output(['docker','info','--format','{{json .}}'],timeout=15))
assert 'name=rootless' in info['SecurityOptions']
result.update(rootless=True,image=image,host_mounts=False,verified=True)
print(json.dumps(result,indent=2))
