import hashlib,json,subprocess,sys,time,uuid
from pathlib import Path
tooling=Path(__file__).resolve().parent
image=sys.argv[1];r=Path(sys.argv[2]).resolve();r.mkdir(parents=True,exist_ok=True);arch=sys.argv[3]
name='zondarr-validation-'+arch+'-'+uuid.uuid4().hex[:8];volume=name;network=name+'-network'
result={'architecture':arch,'volume':volume,'checks':[]}
def docker(*args,check=True):
 p=subprocess.run(['docker',*args],capture_output=True,text=True,timeout=90)
 if check and p.returncode:raise RuntimeError('docker '+args[0]+' failed: '+p.stderr[:1000])
 return (p.stdout+p.stderr if args[0]=='logs' else p.stdout).strip()
def js(code):return json.loads(docker('exec',name,'bun','-e',code))
def py(code):return json.loads(docker('exec',name,'/app/backend/.venv/bin/python','-c',code))
def ready(expected):
 for _ in range(60):
  try:
   v=js("const b=await fetch('http://127.0.0.1:8765/health/ready',{signal:AbortSignal.timeout(1000)});const f=await fetch('http://127.0.0.1:4321/api/auth/methods',{signal:AbortSignal.timeout(1000)});console.log(JSON.stringify({backend:b.status,frontend:f.status,health:await b.json(),methods:await f.json()}))")
   if v['backend']==200 and v['frontend']==200 and v['health']['status']=='ready' and v['methods']['setup_required']==expected:return v
  except Exception:pass
  time.sleep(1)
 raise RuntimeError('readiness failed')
def save_log(label):
 p=r/(name+'-'+label+'.log');p.write_text(docker('logs',name,check=False));p.chmod(0o600)
def stop():
 start=time.monotonic();docker('stop','--time','20',name);state=json.loads(docker('inspect',name))[0]['State'];elapsed=time.monotonic()-start
 assert state['ExitCode']==0 and not state['OOMKilled'] and elapsed<20,state
 return round(elapsed,3)
def start():docker('run','-d','--name',name,'--network',network,'-e','PUID=12345','-e','PGID=12345','-e','FRONTEND_PORT=4321','-e','BACKEND_PORT=8765','-e','TZ=UTC','-v',volume+':/config',image)
def state():
 return py("import hashlib,json,sqlite3,pathlib; d=pathlib.Path('/config/data');c=sqlite3.connect(d/'zondarr.db'); print(json.dumps({'integrity':c.execute('pragma integrity_check').fetchone()[0],'migration':c.execute('select version_num from alembic_version').fetchone()[0],'files':{n:{'hash':hashlib.sha256((d/n).read_bytes()).hexdigest(),'mode':oct((d/n).stat().st_mode&0o777),'uid':(d/n).stat().st_uid,'gid':(d/n).stat().st_gid} for n in ['.secret_key','.bootstrap_token']}}))")
try:
 docker('network','create','--internal',network);docker('volume','create',volume);start()
 result['checks'].append({'fresh':ready(True)})
 info=py("import json,sys,sysconfig,zondarr,msgspec,granian,cryptography,argon2,greenlet,asyncpg;print(json.dumps({'python':sys.version.split()[0],'platform':sysconfig.get_platform(),'package':zondarr.__path__[0]}))")
 assert info['python']=='3.14.7' and '/site-packages/zondarr' in info['package'],info
 runtime=js("import {readFileSync,readdirSync} from 'node:fs';let services=[];for(const p of readdirSync('/proc').filter(n=>/^\\d+$/.test(n))){try{const cmd=readFileSync('/proc/'+p+'/cmdline','utf8').split('\\0');if((cmd[0]==='bun'&&cmd[1]==='./build/index.js')||(cmd[0]==='/app/backend/.venv/bin/python'&&cmd[1]==='-m'))services.push({cmd,uid:readFileSync('/proc/'+p+'/status','utf8').match(/Uid:\\s+(\\d+)/)[1]})}catch{}}console.log(JSON.stringify({bun:Bun.version,arch:process.arch,production:process.env.NODE_ENV,services}))")
 assert runtime['bun']=='1.4.2' and runtime['production']=='production' and runtime['arch']=={'amd64':'x64','arm64':'arm64'}[arch],runtime
 assert len(runtime['services'])>=2 and all(s['uid']=='12345' for s in runtime['services']),runtime
 expected=json.loads((tooling/'migration-checksums.json').read_text())
 actual=py("import json,pathlib,hashlib;p=pathlib.Path('/app/backend/migrations');print(json.dumps({str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in p.rglob('*') if f.is_file() and '__pycache__' not in str(f)}))")
 assert expected==actual,(expected.keys(),actual.keys())
 initial=state();assert initial['integrity']=='ok'
 assert all(f['mode']=='0o600' and f['uid']==12345 and f['gid']==12345 for f in initial['files'].values()),initial
 setup=js("const token=(await Bun.file('/config/data/.bootstrap_token').text()).trim();const page=await fetch('http://127.0.0.1:4321/setup?token='+encodeURIComponent(token));const html=await page.text();const body={username:'prototypeadmin',password:'Isolated-test-password-123456',bootstrap_token:token};const options={method:'POST',headers:{'Content-Type':'application/json',Origin:'http://127.0.0.1:4321'},body:JSON.stringify(body)};const response=await fetch('http://127.0.0.1:4321/api/auth/setup',options);console.log(JSON.stringify({page:page.status,html:html.includes('Zondarr'),setup:response.status}))")
 assert setup=={'page':200,'html':True,'setup':201},setup
 ready(False)
 result['checks'].append({'python':info,'runtime':runtime,'exact_migrations':True,'persistent_state':initial,'setup_proxy':setup,'stop_seconds':stop()});save_log('fresh')
 docker('start',name);ready(False);assert state()==initial
 result['checks'].append({'restart_persisted':True,'stop_seconds':stop()});save_log('restart')
 docker('cp',name+':/config/data',str(r/(name+'-backup')));docker('rm',name)
 start();ready(False);assert state()==initial
 result['checks'].append({'replacement_persisted':True,'stop_seconds':stop()});save_log('replacement')
 result['passed']=True
finally:
 save_log('final');docker('stop','--time','20',name,check=False);docker('rm',name,check=False);docker('network','rm',network,check=False)
 (r/'runtime-result.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
