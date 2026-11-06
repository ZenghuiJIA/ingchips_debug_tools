"""Offline debug jobs; all production instrument capabilities are explicit."""
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from hil.report import atomic_json
from hil.runner import terminate_worker

OPERATIONS={'analyze_instrumentation','analyze_crash_bundle','analyze_power_capture'}

def capabilities():
    return {'schema_version':1,'analysis_version':'embedded-debug-1','hili':{'major':1,'header_bytes':40,'max_payload':1024,'dictionary':1,'modes':['binary','text']},
            'offline_analysis':sorted(OPERATIONS),'production_instruments':{'power_supply':[],'power_measurement':[]},
            'instrumentation_control':False,'uart_passive_observation':True,'automatic_rtt':False,'crash_clear':False,
            'rtos_ports':['FreeRTOS 10/11 explicitly enabled port'],'hardware_verified':False,
            'limitations':['No power instrument drivers installed','Target capture/time/retention requires board validation','No logic-analyzer adapter or data breakpoint support']}

def perform(operation,args):
    if operation=='analyze_instrumentation':
        from instrumentation.analysis import analyze_file,analyze_instrumentation,analyze_task_snapshots
        if args.get('file_path'):return analyze_file(args['file_path'],args.get('mode','binary'),args.get('budgets'),args.get('device_id','offline'),args.get('session_id','import'))
        report=analyze_instrumentation(args.get('events',[]),args.get('budgets'),args.get('device_id','offline'),args.get('session_id','import'),args.get('errors'),args.get('source_kind','imported_recording'))
        report['task_analysis']=analyze_task_snapshots(report['task_snapshots']);return report
    if operation=='analyze_crash_bundle':
        from hil.crash import analyze_bundle
        return analyze_bundle(args['directory'],args.get('elf_path'),args.get('build_id'))
    if operation=='analyze_power_capture':
        from instruments.power import analyze_power_capture
        return analyze_power_capture(args['file_path'],args['start_ns'],args['end_ns'],args.get('max_gap_ns','1000000000'))
    raise ValueError('Unsupported offline debug operation')

class DebugJobs:
    def __init__(self):
        self.root=Path(os.environ.get('HIL_REPORT_DIR',Path(os.environ.get('LOCALAPPDATA','.') )/'AI-HIL-Debugger'/'reports'))/'debug'
        self.jobs={};self.lock=threading.Lock()
    def start(self,operation,arguments,timeout_ms=30000):
        if operation not in OPERATIONS or not isinstance(arguments,dict) or not isinstance(timeout_ms,int) or not 100<=timeout_ms<=120000:raise ValueError('Invalid analysis task')
        with self.lock:
            if any(not j['done'] for j in self.jobs.values()):raise RuntimeError('An offline analysis is active')
            if len(self.jobs)>=100:self.jobs.pop(next(iter(self.jobs)))
            ident=uuid.uuid4().hex;folder=self.root/ident;folder.mkdir(parents=True)
            atomic_json(folder/'request.json',{'operation':operation,'arguments':arguments})
            atomic_json(folder/'status.json',{'job_id':ident,'state':'RUNNING','source_kind':'offline_analysis','done':False,'report_dir':str(folder)})
            command=[sys.executable]
            if not getattr(sys,'frozen',False):command.append(str(Path(__file__).with_name('daemon_entry.py')))
            command.extend(['--debug-analysis-worker',str(folder)])
            with (folder/'worker.log').open('wb') as log:
                child=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=log,stderr=log,env={**os.environ,'PYINSTALLER_RESET_ENVIRONMENT':'1'},creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            info={'folder':folder,'process':child,'done':False,'cancel':False};self.jobs[ident]=info
            threading.Thread(target=self.watch,args=(ident,timeout_ms),daemon=True).start()
        return self.get(ident)
    def watch(self,ident,timeout):
        info=self.jobs[ident];child=info['process'];deadline=time.monotonic()+timeout/1000;error=None
        try:
            while child.poll() is None:
                if info['cancel'] or time.monotonic()>=deadline:
                    terminate_worker(child);error='Cancelled by user' if info['cancel'] else 'Offline analysis timeout';break
                time.sleep(.02)
            state=json.loads((info['folder']/'status.json').read_text(encoding='utf-8'))
            if error or not state.get('done'):
                state.update(state='CANCELLED' if info['cancel'] else 'ERROR',done=True,error=error or 'Analysis worker exited unexpectedly')
                atomic_json(info['folder']/'status.json',state)
        finally:info['done']=True
    def info(self,ident):
        if not isinstance(ident,str) or len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):raise ValueError('Invalid job_id')
        if ident not in self.jobs:raise ValueError('Unknown analysis job')
        return self.jobs[ident]
    def get(self,ident):
        info=self.info(ident);state=json.loads((info['folder']/'status.json').read_text(encoding='utf-8'));state['done']=state.get('done',False) and info['done'];return state
    def stop(self,ident):
        info=self.info(ident)
        if not info['done']:info['cancel']=True
        return self.get(ident)
    def result(self,ident):
        info=self.info(ident)
        if not info['done']:raise ValueError('Analysis still running')
        state=self.get(ident)
        if state['state']!='COMPLETED':return state
        path=info['folder']/'analysis.json'
        if not path.exists():return self.get(ident)
        return json.loads(path.read_text(encoding='utf-8'))

JOBS=DebugJobs()

def dispatch(name,args):
    if name=='get_debug_capabilities':return capabilities()
    if name=='start_debug_analysis':return JOBS.start(args['operation'],args['arguments'],args.get('timeout_ms',30000))
    if name=='get_debug_analysis_status':return JOBS.get(args['job_id'])
    if name=='stop_debug_analysis':return JOBS.stop(args['job_id'])
    if name=='get_debug_analysis_result':return JOBS.result(args['job_id'])
    if name in OPERATIONS:return perform(name,args)
    raise ValueError('Unknown debug operation')

def worker(folder):
    folder=Path(folder);request=json.loads((folder/'request.json').read_text(encoding='utf-8'));state=json.loads((folder/'status.json').read_text(encoding='utf-8'))
    try:
        result=perform(request['operation'],request['arguments']);result['job_id']=folder.name
        atomic_json(folder/'analysis.json',result);state.update(state='COMPLETED',done=True)
    except Exception as exc:
        state.update(state='ERROR',done=True,error={'code':'ANALYSIS_ERROR','operation':request['operation'],'target':request['arguments'].get('file_path',request['arguments'].get('directory')),'phase':'analysis','reason':str(exc),'partial_result':None,'resource_state':'NO_HARDWARE','retryable':False})
    atomic_json(folder/'status.json',state)
