"""Frozen native codec + daemon integration, no device access."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
daemon=Path(sys.argv[1]).resolve()
codec=daemon.parent/'hil-protocol.exe'
spec=json.loads((root/'examples/hil/protocol-aa55.json').read_text(encoding='utf-8'))
values={'seq':1,'value':-2,'status':0}
requests=[{'id':1,'operation':'encode','protocol':spec,'values':values},
          {'id':2,'operation':'configure','protocol':spec},
          {'id':3,'operation':'feed','data':'aa5501feff00fd','elapsed_ms':0}]
result=subprocess.run([str(codec)],input='\n'.join(json.dumps(r) for r in requests)+'\n',capture_output=True,text=True,encoding='utf-8',timeout=30,check=True)
responses=[json.loads(line) for line in result.stdout.splitlines()]
assert responses[0]['result']['data']=='aa5501feff00fd',responses
assert responses[2]['result']['frames'][0]['fields']['value']==-2,responses
with tempfile.TemporaryDirectory() as temporary:
    folder=Path(temporary)
    plan=folder/'protocol.json'
    plan.write_text(json.dumps({'schema_version':2,'steps':[{'action':'protocol_request','params':{'port_name':'COM_NO_HARDWARE','protocol':spec,'values':values,'expected':{'seq':1}}}]}),encoding='utf-8')
    result=subprocess.run([str(daemon),'--validate','--file',str(plan)],capture_output=True,text=True,encoding='utf-8',timeout=60)
    assert result.returncode==0,result.stderr+result.stdout
    assert json.loads(result.stdout)['valid'],result.stdout
    plugin=folder/'decoder.py'
    plugin.write_text('def decode(payload):\n return {"samples":[{"t":1,"channel":"温度","value":23.5}]}\n',encoding='utf-8')
    request={'jsonrpc':'2.0','id':1,'method':'protocol_plugin_analyze','params':{'plugin_path':str(plugin),'payload':{},'timeout_ms':10000}}
    shutdown={'jsonrpc':'2.0','id':2,'method':'shutdown'}
    result=subprocess.run([str(daemon)],input=json.dumps(request)+'\n'+json.dumps(shutdown)+'\n',capture_output=True,text=True,encoding='utf-8',timeout=60,check=True)
    response=json.loads(result.stdout.splitlines()[0])
    assert response['result']['samples'][0]['value']==23.5,response
    assert response['result']['hardware_verified'] is False,response
print('PASS frozen ABC: native codec golden vector, HIL validation bridge, UTF-8 isolated plugin')
