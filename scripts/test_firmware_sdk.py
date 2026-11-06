import os, subprocess, tempfile, unittest, shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SRC=ROOT/'firmware/hil-instrumentation'
class FirmwareSDKTests(unittest.TestCase):
 def test_compile_host_and_disabled_macro(self):
  with tempfile.TemporaryDirectory() as folder:
   exe=Path(folder)/('test.exe' if os.name=='nt' else 'test')
   command=['gcc','-std=c11','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-I',str(SRC/'include'),str(SRC/'src/hil_instrumentation.c'),str(SRC/'tests/test_host.c'),'-o',str(exe)]
   subprocess.run(command,check=True,cwd=ROOT);subprocess.run([str(exe),str(Path(folder)/'frames.bin')],check=True)
   import json
   codec=ROOT/'src-tauri/target/debug/hil-protocol.exe'
   if codec.is_file():
    requests=[{'id':1,'operation':'hili_configure'}, {'id':2,'operation':'hili_feed','elapsed_ms':0,'data':(Path(folder)/'frames.bin').read_bytes().hex()}]
    result=subprocess.run([str(codec)],input='\n'.join(map(json.dumps,requests))+'\n',capture_output=True,text=True,check=True)
    decoded=json.loads(result.stdout.splitlines()[1])['result'];self.assertFalse(decoded['errors']);self.assertEqual(decoded['events'][0]['boot_id'],'7');self.assertEqual(decoded['events'][2]['event_type'],4)
   disabled=Path(folder)/'disabled.c';disabled.write_text('#define HIL_INSTRUMENTATION_DISABLED\n#include "hil_instrumentation.h"\nint main(void){int x=0;HIL_EVENT(++x,++x);hil_span_token_t t=HIL_SPAN_BEGIN(++x);HIL_SPAN_END(t);(void)t;return x;}\n',encoding='utf-8')
   subprocess.run(['gcc','-std=c11','-Wall','-Wextra','-Werror','-I',str(SRC/'include'),str(disabled),'-o',str(exe)],check=True,cwd=ROOT);subprocess.run([str(exe)],check=True)
   self.assertEqual(subprocess.run(['gcc','-std=c11','-Wall','-Wextra','-Werror','-I',str(SRC/'include'),'-c',str(SRC/'ports/cortex_m/hil_cortex_m.c'),'-o',str(Path(folder)/'cortex.o')],cwd=ROOT).returncode,0)
   for runtime in (0,1):
    subprocess.run(['gcc','-std=c11','-Wall','-Wextra','-Werror','-Wno-misleading-indentation',f'-DconfigGENERATE_RUN_TIME_STATS={runtime}','-I',str(SRC/'include'),'-I',str(SRC/'tests/freertos_stub'),'-c',str(SRC/'ports/freertos/hil_freertos.c'),'-o',str(Path(folder)/f'freertos-{runtime}.o')],check=True,cwd=ROOT)
if __name__=='__main__':unittest.main()
