import json
import math
from pathlib import Path
from decimal import Decimal

def u64(value):
    if not isinstance(value,str) or not value.isascii() or not value.isdecimal() or int(value)>=2**64: raise ValueError('timestamp/seq must be uint64 decimal strings')
    return int(value)

def finite(value,name):
    if value is None:return None
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value): raise ValueError(f'{name} must be finite or null')
    return Decimal(str(value))

def analyze_power_capture(file_path,start_ns,end_ns,max_gap_ns='1000000000'):
    path=Path(file_path)
    if not path.is_file() or path.stat().st_size>256*1024*1024: raise ValueError('Power JSONL input limit is 256 MiB')
    start,end,gap=map(u64,(start_ns,end_ns,max_gap_ns))
    if end<=start or gap==0:raise ValueError('Invalid integration interval')
    groups={};count=0
    with path.open(encoding='utf-8-sig') as source:
        for line in source:
            if len(line)>65536:raise ValueError('Power sample line exceeds 64 KiB')
            if not line.strip():continue
            row=json.loads(line);count+=1
            if row.get('sample_kind','instantaneous')!='instantaneous':raise ValueError('Initial importer supports instantaneous samples only; interval averages need explicit boundaries')
            kind=row.get('source_kind')
            if kind not in ('hardware_capture','imported_measurement','synthetic_test'):raise ValueError('Invalid source_kind')
            for key in ('capture_id','channel_id','clock_id'):
                if not isinstance(row.get(key),str) or not row[key]:raise ValueError(f'{key} required')
            t=u64(row['timestamp_ns']);seq=u64(row['seq']);i=finite(row.get('current_a'),'current_a');v=finite(row.get('voltage_v'),'voltage_v')
            flags=row.get('quality_flags')
            if not isinstance(flags,list) or any(not isinstance(f,str) for f in flags):raise ValueError('quality_flags must be a string array')
            key=(row['capture_id'],row['channel_id'],row['clock_id'],kind)
            if key not in groups:
                if len(groups)>=64:raise ValueError('Maximum 64 power channels/time domains')
                groups[key]={'previous':None,'q':Decimal(0),'e':Decimal(0),'covered':0,'energy_covered':0,'gaps':0,'min':None,'max':None,'samples':0,'high_time':None}
            g=groups[key];g['samples']+=1
            monotonic=g['high_time'] is None or t>g['high_time']
            valid=i is not None and not flags and monotonic
            g['high_time']=max(t,g['high_time']) if g['high_time'] is not None else t
            if start<=t<=end and valid:
                g['min']=i if g['min'] is None else min(g['min'],i);g['max']=i if g['max'] is None else max(g['max'],i)
            previous=g['previous'];current=(t,seq,i,v,valid,row.get('voltage_synchronous') is True)
            if previous:
                pt,ps,pi,pv,pvalid,psync=previous;left=max(start,pt);right=min(end,t)
                interval_ok=t>pt and t-pt<=gap and seq==ps+1 and valid and pvalid
                if not interval_ok:
                    if min(pt,t)<=end and max(pt,t)>=start:g['gaps']+=1
                elif right>left:
                    span=Decimal(t-pt);alpha=Decimal(left-pt)/span;beta=Decimal(right-pt)/span
                    ia=pi+(i-pi)*alpha;ib=pi+(i-pi)*beta;seconds=Decimal(right-left)/Decimal(10**9)
                    g['q']+=(ia+ib)*seconds/2;g['covered']+=right-left
                    if pv is not None and v is not None and psync and current[5]:
                        # Trapezoidal integration of measured instantaneous P=V*I.
                        pa=pv*pi+(v*i-pv*pi)*alpha;pb=pv*pi+(v*i-pv*pi)*beta
                        g['e']+=(pa+pb)*seconds/2;g['energy_covered']+=right-left
            g['previous']=current
    results=[]
    for key,g in groups.items():
        capture,channel,clock,kind=key;coverage=g['covered']/(end-start)
        energy_complete=g['energy_covered']==g['covered'] and g['covered']>0
        results.append({'capture_id':capture,'channel_id':channel,'clock_id':clock,'source_kind':kind,'samples':g['samples'],
            'request_start_ns':str(start),'request_end_ns':str(end),'covered_ns':str(g['covered']),'coverage':coverage,'gap_count':g['gaps'],
            'minimum_a':str(g['min']) if g['min'] is not None else None,'maximum_a':str(g['max']) if g['max'] is not None else None,
            'time_weighted_mean_a':str(g['q']/(Decimal(g['covered'])/Decimal(10**9))) if g['covered'] else None,
            'charge_c':str(g['q']) if g['covered'] else None,'charge_mah':str(g['q']/Decimal('3.6')) if g['covered'] else None,
            'energy_j':str(g['e']) if energy_complete else None,'energy_covered_ns':str(g['energy_covered']),
            'analysis_status':'PASS' if coverage==1 and not g['gaps'] else 'INCONCLUSIVE'})
    return {'schema_version':1,'analysis_version':'power-1','source_kind':'offline_power_analysis','hardware_verified':False,
            'analysis_status':'PASS' if results and all(r['analysis_status']=='PASS' for r in results) else 'INCONCLUSIVE',
            'channels':results,'sample_count':count,'limitations':['Offline import is not current-board HIL evidence.','Missing or asynchronous voltage never produces energy.','No interpolation across invalid intervals; trapezoidal instantaneous-sample model.']}
