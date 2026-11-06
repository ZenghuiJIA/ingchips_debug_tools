"""Repeatable synthetic codec load. Never opens a device; records measured throughput/RSS."""
import json
import sys
import time
from pathlib import Path
import psutil
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src-tauri/daemon'))
from hil.codec import Codec
spec=json.loads((Path(__file__).resolve().parents[1]/'examples/hil/protocol-aa55.json').read_text(encoding='utf-8'))
results=[]
for batch in (1,16,128):
    with Codec(spec) as codec:
        wire=codec.encode({'seq':1,'value':-2,'status':0})*batch
        process=psutil.Process(codec.process.pid);before=process.memory_info().rss;peak=before
        count=0;start=time.monotonic()
        for i in range(300):
            frames=codec.feed(wire,i)
            assert len(frames)==batch and all(f['valid'] for f in frames)
            count+=len(frames);peak=max(peak,process.memory_info().rss)
        elapsed=time.monotonic()-start
        results.append({'mode':'SYNTHETIC_NO_HARDWARE','batch_frames':batch,'frames':count,'seconds':round(elapsed,3),'frames_per_second':round(count/elapsed),'peak_rss_mb':round(peak/1048576,2),'rss_growth_mb':round((peak-before)/1048576,2)})
print(json.dumps(results,indent=2))
