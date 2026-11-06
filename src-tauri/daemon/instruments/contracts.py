"""No production drivers. Tests inject adapters directly, never through configuration."""
import json
import time
from decimal import Decimal
from pathlib import Path
from typing import Protocol
from dataclasses import dataclass

class Unsupported(RuntimeError):pass

class PowerSupplyAdapter(Protocol):
    def describe(self): ...
    def open(self,binding,deadline): ...
    def query_state(self,deadline): ...
    def apply_setpoint(self,op_id,settings,deadline): ...
    def set_output(self,op_id,enabled,deadline): ...
    def cancel(self,op_id,deadline): ...
    def close(self,deadline): ...

class PowerMeasurementAdapter(Protocol):
    def describe(self): ...
    def open(self,binding,deadline): ...
    def configure(self,config,deadline): ...
    def start(self,capture_id,deadline): ...
    def read_batch(self,cursor,limit,deadline): ...
    def stop(self,capture_id,deadline): ...
    def close(self,deadline): ...

def describe_registry():return {'power_supplies':[],'power_measurement':[],'production_drivers_installed':False}
def open_production(binding):raise Unsupported('UNSUPPORTED: no power supply or measurement production drivers installed')

def persist(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value,indent=2),encoding='utf-8');temporary.replace(path)

class SupplyController:
    """Adapter confirmation, not RPC completion, determines device facts."""
    def __init__(self,adapter,binding,board,journal):
        self.adapter=adapter;self.binding=dict(binding);self.board=dict(board);self.journal=Path(journal)
        self.state='IDLE';self.output='UNKNOWN';self.initial=None;self.op_id=None;self.used=set()
        if self.journal.exists():
            previous=json.loads(self.journal.read_text())
            if previous.get('state') not in ('COMPLETED','CANCELLED','FAILED'):self.state='UNKNOWN'
    def deadline(self,end):
        if time.monotonic()>=end:raise TimeoutError('Device confirmation deadline exceeded')
    def validate(self,settings,policy):
        if set(policy)!= {'on_success','on_failure','on_cancel'} or any(v not in ('leave_as_is','output_off','restore_initial') for v in policy.values()):raise ValueError('Explicit exit policies required')
        if not self.binding.get('device_id') or not self.binding.get('board_id') or 'channel' not in self.binding:raise ValueError('Stable device/board/channel binding required')
        caps=self.adapter.describe();channel=self.binding['channel']
        if channel not in caps['channels'] or not caps.get('output_readback'):raise Unsupported('Channel/readback unsupported')
        for key,unit in [('voltage_v','voltage'),('current_limit_a','current')]:
            if key not in settings:raise ValueError('Explicit voltage and current limit required')
            value=Decimal(str(settings[key]));lower=max(Decimal(str(self.board[unit+'_min'])),Decimal(str(caps[unit+'_min'])));upper=min(Decimal(str(self.board[unit+'_max'])),Decimal(str(caps[unit+'_max'])));resolution=Decimal(str(caps[unit+'_resolution']))
            if not value.is_finite() or resolution<=0 or value<lower or value>upper or value%resolution:raise ValueError('Setpoint outside range/resolution')
        if 'restore_initial' in policy.values() and not caps.get('restore_supported'):raise Unsupported('Restore unsupported')
    def write_ahead(self,phase):
        self.state=phase;persist(self.journal,{'schema_version':1,'binding':self.binding,'op_id':self.op_id,'state':phase,'output':self.output})
    def confirm(self,end):
        self.deadline(end);actual=self.adapter.query_state(end);self.deadline(end)
        if actual.get('output') not in ('ON','OFF'):raise RuntimeError('Output readback unknown')
        self.output=actual['output'];return actual
    def recover(self,end):
        actual=self.confirm(end);self.write_ahead('COMPLETED');return actual
    def apply(self,op_id,settings,policy,end,cancelled=lambda:False):
        if self.state=='UNKNOWN':raise RuntimeError('Recovery query required before another write')
        if not op_id or op_id in self.used:raise ValueError('Duplicate/missing op_id')
        self.validate(settings,policy);self.op_id=op_id;self.used.add(op_id);reason='success';primary=None
        try:
            self.write_ahead('VALIDATING');self.deadline(end);identity=self.adapter.open(self.binding,end)
            if identity.get('device_id')!=self.binding['device_id']:raise RuntimeError('Device identity mismatch')
            self.initial=self.confirm(end)
            if cancelled():reason='cancel';raise InterruptedError('Cancelled before write')
            self.write_ahead('APPLYING');self.adapter.apply_setpoint(op_id,settings,end);self.deadline(end)
            self.write_ahead('VERIFYING');actual=self.confirm(end)
            if any(actual.get(k)!=v for k,v in settings.items()):raise RuntimeError('Setpoint verification mismatch')
            if cancelled():reason='cancel'
        except InterruptedError as exc:reason='cancel';primary=str(exc)
        except Exception as exc:reason='failure';primary=str(exc);self.state='UNKNOWN';self.output='UNKNOWN'
        cleanup_error=None
        try:
            strategy=policy['on_'+reason]
            if self.state=='UNKNOWN' and strategy!='leave_as_is':raise RuntimeError('Unknown output; automatic recovery write prohibited')
            if strategy=='output_off':
                self.write_ahead('STOPPING');self.adapter.set_output(op_id+':exit',False,end)
                if self.confirm(end)['output']!='OFF':raise RuntimeError('Output off not confirmed')
            elif strategy=='restore_initial':
                if self.initial is None:raise RuntimeError('No trusted initial state')
                self.write_ahead('STOPPING');self.adapter.apply_setpoint(op_id+':restore',{k:self.initial[k] for k in ('voltage_v','current_limit_a')},end);self.adapter.set_output(op_id+':restore-output',self.initial['output']=='ON',end)
                actual=self.confirm(end)
                if any(actual.get(k)!=v for k,v in self.initial.items()):raise RuntimeError('Initial state not restored')
            self.adapter.close(end);self.deadline(end)
        except Exception as exc:cleanup_error=str(exc);self.state='UNKNOWN';self.output='UNKNOWN'
        final='UNKNOWN' if self.state=='UNKNOWN' else 'CANCELLED' if reason=='cancel' else 'FAILED' if reason=='failure' else 'COMPLETED'
        self.write_ahead(final)
        return {'operation_state':final,'output_state':self.output,'primary_error':primary,'cleanup_error':cleanup_error,'stop_reason':reason,'resource_state':'UNKNOWN' if cleanup_error else 'CLOSED'}

class MeasurementController:
    def __init__(self,adapter):self.adapter=adapter;self.state='IDLE';self.capture_id=None
    def start(self,binding,config,capture_id,end):
        if self.state not in ('IDLE','COMPLETED','CANCELLED'):raise RuntimeError('Capture active/unknown; recover first')
        self.state='STARTING';self.capture_id=capture_id
        try:
            identity=self.adapter.open(binding,end)
            if identity.get('device_id')!=binding.get('device_id'):raise RuntimeError('Instrument identity mismatch')
            actual=self.adapter.configure(config,end)
            if actual!=config:raise ValueError('Instrument configuration not confirmed')
            state=self.adapter.start(capture_id,end)
            if state.get('state')!='CAPTURING' or time.monotonic()>=end:raise RuntimeError('Capture start not confirmed')
            self.state='CAPTURING';return state
        except Exception:self.state='UNKNOWN';raise
    def stop(self,capture_id,end,cancel=False):
        if capture_id!=self.capture_id or self.state!='CAPTURING':raise ValueError('Wrong capture identity/state')
        self.state='STOPPING'
        try:
            result=self.adapter.stop(capture_id,end)
            if result.get('state')!='COMPLETED':raise RuntimeError('Stop not confirmed')
            self.adapter.close(end)
            if time.monotonic()>=end:raise TimeoutError('Close deadline exceeded')
            self.state='CANCELLED' if cancel else 'COMPLETED';return {**result,'state':self.state,'stop_reason':'cancel' if cancel else 'normal'}
        except Exception:self.state='UNKNOWN';raise
