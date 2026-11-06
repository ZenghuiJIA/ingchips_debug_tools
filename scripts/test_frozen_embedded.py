"""Exercise native -> frozen Python -> Rust HILI analysis; no target hardware."""
import json,os,queue,struct,subprocess,sys,tempfile,threading,time,zlib,hashlib
from pathlib import Path
exe=Path(sys.argv[1]).resolve()
def frame(kind,sequence,ticks,payload):
    header=struct.pack('<4sBBHHHIQIQ',b'HILI',1,0,kind,40,0,len(payload),7,sequence,ticks)
    return header+struct.pack('<I',zlib.crc32(header+payload))+payload
with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary);record=root/'events.hili'
    record.write_bytes(frame(1,0,0,b'B'*16+struct.pack('<II',1,0))+frame(2,1,0,struct.pack('<IIIBBH',1,0,1000000,64,4,0))+frame(4,2,2**53+1,struct.pack('<III',1,1,42))+frame(5,3,2**53+11,struct.pack('<III',1,1,42)))
    env={**os.environ,'HIL_REPORT_DIR':str(root/'reports'),'HIL_FLASH_STATE_DIR':str(root/'flash')}
    process=subprocess.Popen([str(exe)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',env=env)
    responses=queue.Queue()
    def read():
        for line in process.stdout:
            try:responses.put(json.loads(line))
            except ValueError:pass
    threading.Thread(target=read,daemon=True).start();counter=0
    def rpc(name,args=None):
        global counter
        counter+=1;process.stdin.write(json.dumps({'jsonrpc':'2.0','id':counter,'method':name,'params':args or {}})+'\n');process.stdin.flush()
        response=responses.get(timeout=40);assert response['id']==counter,response
        if 'error' in response:raise RuntimeError(response['error'])
        return response['result']
    try:
        caps=rpc('get_debug_capabilities');assert caps['production_instruments']['power_supply']==[],caps
        job=rpc('start_debug_analysis',{'operation':'analyze_instrumentation','arguments':{'file_path':str(record),'budgets':{'42':{'metric':'elapsed','threshold':5,'unit':'us','min_samples':1}}},'timeout_ms':30000})
        limit=time.monotonic()+40
        while not job['done'] and time.monotonic()<limit:time.sleep(.1);job=rpc('get_debug_analysis_status',{'job_id':job['job_id']})
        assert job['done'] and job['state']=='COMPLETED',job
        report=rpc('get_debug_analysis_result',{'job_id':job['job_id']});assert report['analysis_status']=='FAIL',report;assert report['metrics'][0]['max_ns']=='10000',report
        plan={'schema_version':3,'steps':[{'action':'delay','params':{'delay_ms':1}},{'action':'power_cycle'}]}
        rejected=rpc('tools/call',{'name':'run_hiltest','arguments':{'document':plan}});assert rejected['isError'],rejected
        assert 'no production power' in rejected['content'][0]['text'],rejected
        # Verified pin reset must pass preflight without probing or opening a port.
        pins={'profile_id':'test','wiring_verified':True,'reset_asserted_dtr':True,'boot_asserted_rts':True,'settle_ms':50,'pulse_ms':100,'boot_hold_ms':50}
        plan={'schema_version':2,'steps':[{'action':'reset_target','params':{'reset_method':'bootloader_reset','port_name':'COM_NO_HARDWARE','pin_reset':pins}}]}
        validated=rpc('validate_hiltest',{'document':plan});assert validated['plan']['_resources']['probes']==[],validated
        # Persistent UNKNOWN rejection occurs before any hardware access.
        probe='frozen-test-only-probe';marker=root/'flash'/(hashlib.sha256(probe.encode()).hexdigest()+'.json');marker.parent.mkdir(exist_ok=True)
        marker.write_text(json.dumps({'state':'UNKNOWN','owner_pid':0}),encoding='utf-8')
        blocked=rpc('tools/call',{'name':'reset_target','arguments':{'probe_id':probe}})
        assert blocked['isError'] and 'FLASH_STATE_UNKNOWN' in blocked['content'][0]['text'],blocked
        cleared=rpc('acknowledge_flash_recovery',{'probe_id':probe,'confirmation':'board_recovery_verified'})
        assert cleared['state']=='RECOVERY_ACKNOWLEDGED',cleared
    finally:
        try:rpc('shutdown');process.wait(timeout=10)
        finally:
            if process.poll() is None:process.kill();process.wait()
            process.stdin.close();process.stdout.close()
print('PASS frozen embedded: native/Python/HILI bridge, uint64 timing, offline jobs, v3 no-driver preflight, pin reset validation')
