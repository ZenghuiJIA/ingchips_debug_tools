"""Per-run cooperative flash cancellation at completed algorithm boundaries.

Halting a core while its flash controller is busy is not proof that erase stopped.
We let the active algorithm return, prevent the next call, then halt and confirm.
Persistent write-ahead markers survive process termination and quarantine unknown
outcomes until the operator explicitly acknowledges board-specific recovery.
"""
import hashlib
import json
import os
import threading
from pathlib import Path
from hil.report import atomic_json


class FlashCancelled(Exception):
    pass


def marker_path(probe_id):
    root=Path(os.environ.get('HIL_FLASH_STATE_DIR',Path(os.environ.get('LOCALAPPDATA','.') )/'AI-HIL-Debugger'/'flash-state'))
    return root/(hashlib.sha256(str(probe_id).encode()).hexdigest()+'.json')


def require_recovered(probe_id):
    if not probe_id:return
    path=marker_path(probe_id)
    if path.exists():
        record=json.loads(path.read_text(encoding='utf-8'))
        if record.get('state') in ('WRITING','CANCELLING','UNKNOWN'):
            raise RuntimeError(f'FLASH_STATE_UNKNOWN: probe {probe_id} has an unfinished erase/program record; verify board-specific recovery before another write')


def acknowledge_recovery(probe_id,confirmation):
    if confirmation!='board_recovery_verified':raise ValueError('Explicit board_recovery_verified confirmation required')
    path=marker_path(probe_id)
    if not path.is_file():return {'state':'NO_UNFINISHED_FLASH','probe_id':probe_id}
    record=json.loads(path.read_text(encoding='utf-8'))
    if record.get('owner_pid') and int(record['owner_pid']) > 0:
        import psutil
        try:
            process=psutil.Process(record['owner_pid'])
            if process.is_running() and process.create_time()==record.get('owner_created'):
                raise RuntimeError('Flash owner is still alive; stop that task before recovery acknowledgement')
        except psutil.NoSuchProcess:pass
    from probe_lease import ProbeLease
    lease=ProbeLease(probe_id)
    try:
        record.update(state='RECOVERY_ACKNOWLEDGED',recovery_basis='operator_board_verification')
        atomic_json(path,record)
    finally:lease.close()
    return record


class FlashControl:
    def __init__(self,session,probe_id,cancel_path,state_path,run_id):
        import psutil
        self.session=session;self.target=session.board.target;self.probe_id=probe_id
        self.cancel_path=Path(cancel_path);self.state_path=Path(state_path);self.run_id=run_id
        self.originals=[];self.inflight=set();self.known=False;self.cleaning=False
        self.lock=threading.RLock()
        self.record={'schema_version':1,'run_id':run_id,'probe_id':probe_id,'state':'PREPARING',
                     'erase_program_stopped':False,'target_halted':False,'firmware_complete':False,
                     'owner_pid':os.getpid(),'owner_created':psutil.Process().create_time()}

    def cancelled(self):return self.cancel_path.is_file()

    def publish(self,state,**details):
        with self.lock:
            self.record.update(state=state,**details)
            marker=marker_path(self.probe_id);marker.parent.mkdir(parents=True,exist_ok=True)
            temp=marker.with_suffix('.tmp')
            with temp.open('w',encoding='utf-8') as out:
                json.dump(self.record,out);out.flush();os.fsync(out.fileno())
            os.replace(temp,marker)
            atomic_json(self.state_path,self.record)

    def __enter__(self):
        require_recovered(self.probe_id)
        flashes=[]
        for region in self.target.memory_map:
            flash=getattr(region,'flash',None)
            if flash is not None and all(flash is not f for f in flashes):flashes.append(flash)
        if not flashes:raise RuntimeError('Cancellable flash requires a target flash algorithm')
        # Feature-detect the installed pyOCD interface. Never silently disable cancellation.
        for flash in flashes:
            if not callable(getattr(flash,'_call_function',None)) or not callable(getattr(flash,'wait_for_completion',None)):
                raise RuntimeError('Installed flash algorithm does not support boundary cancellation')
        self.publish('PREPARING')
        for flash in flashes:
            call=flash._call_function;wait=flash.wait_for_completion
            self.originals.append((flash,call,wait))
            def guarded_call(*args,_flash=flash,_call=call,**kwargs):
                if self.cancelled() and not self.cleaning:raise FlashCancelled('Cancel requested before next flash algorithm')
                pc=args[0] if args else kwargs.get('pc')
                self.publish('WRITING',phase='algorithm',algorithm_pc=pc)
                self.inflight.add(id(_flash))
                return _call(*args,**kwargs)
            def guarded_wait(*args,_flash=flash,_wait=wait,**kwargs):
                result=_wait(*args,**kwargs)
                if result!=0:
                    self.publish('UNKNOWN',reason='Flash algorithm did not return success',algorithm_result=result)
                    return result
                self.inflight.discard(id(_flash))
                if self.cancelled() and not self.cleaning:
                    self.publish('CANCELLING',phase='completed_algorithm_boundary')
                    raise FlashCancelled('Active algorithm completed; no further erase/program will start')
                return result
            flash._call_function=guarded_call;flash.wait_for_completion=guarded_wait
        return self

    def stop_confirmed(self):
        if self.inflight:raise RuntimeError('Cannot confirm cancellation while flash algorithm outcome is unknown')
        # Restore hooks before cleanup. UnInit is allowed only after the active
        # algorithm completed, and no reset/run is performed.
        self.restore();self.cleaning=True
        for flash,_,_ in self.originals:flash.cleanup()
        self.target.halt()
        from pyocd.core.target import Target
        if self.target.get_state()!=Target.State.HALTED:raise RuntimeError('Target halt was not confirmed')
        self.known=True
        self.publish('CANCELLED',phase='cleanup_complete',erase_program_stopped=True,target_halted=True,
                     firmware_complete=False,reason='Stopped at a completed flash algorithm boundary; image may be partial')
        return dict(self.record)

    def completed(self):
        self.known=True;self.publish('COMPLETED',phase='program_complete',erase_program_stopped=True,firmware_complete=True)

    def restore(self):
        for flash,call,wait in self.originals:flash._call_function=call;flash.wait_for_completion=wait

    def __exit__(self,typ,error,tb):
        self.restore()
        if error and not self.known:
            self.publish('UNKNOWN',reason=str(error),phase='exception',erase_program_stopped=False)
