"""Untrusted offline evidence validation. Never falls back to live memory."""
import hashlib
import json
from pathlib import Path

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as source:
        while data:=source.read(65536): h.update(data)
    return h.hexdigest()

def contained(root,name):
    relative=Path(name)
    if relative.is_absolute() or '..' in relative.parts or ':' in name: raise ValueError('Evidence path escapes bundle')
    path=(root/relative).resolve()
    if root not in path.parents: raise ValueError('Evidence path escapes bundle')
    return path

class MemorySource:
    def __init__(self,root,regions): self.root,self.regions=Path(root).resolve(),regions
    def read(self,address,count):
        if count<1 or count>1024*1024 or address<0 or address+count>2**32: raise ValueError('Memory request outside bounds')
        result=bytearray();cursor=address
        while cursor<address+count:
            region=next((r for r in self.regions if r['address']<=cursor<r['address']+r['length']),None)
            if region is None: raise ValueError(f'Captured memory unavailable at {cursor:#x}')
            take=min(address+count-cursor,region['address']+region['length']-cursor)
            with contained(self.root,region['file']).open('rb') as source:
                source.seek(cursor-region['address']);block=source.read(take)
            if len(block)!=take: raise ValueError('Captured memory short read')
            result.extend(block);cursor+=take
        return bytes(result)

def analyze_bundle(directory,elf_path=None,build_id=None):
    root=Path(directory).resolve()
    if not root.is_dir(): raise ValueError('Crash bundle directory missing')
    total=0;actual={};quality=[]
    for path in root.rglob('*'):
        if path.is_symlink(): raise ValueError('Symlinks are not accepted in evidence bundles')
        if not path.is_file(): continue
        contained(root,str(path.relative_to(root)));total+=path.stat().st_size
        if total>64*1024*1024 or len(actual)>=256: raise ValueError('Bundle size/file limit exceeded')
        actual[str(path.relative_to(root)).replace('\\','/')]={'size':path.stat().st_size,'sha256':digest(path)}
    manifest_path=root/'manifest.json'
    if not manifest_path.is_file(): return {'schema_version':1,'analysis_status':'INCONCLUSIVE','completeness':'partial','source_kind':'offline_crash_bundle','hardware_verified':False,'limitations':['Manifest missing'],'files':actual}
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('schema_version')!=1: raise ValueError('Unsupported evidence schema')
    declared=manifest.get('files')
    if not isinstance(declared,dict): raise ValueError('Manifest files must map names to size/sha256')
    verified=set()
    for name,info in declared.items():
        path=contained(root,name)
        if not path.is_file():quality.append(f'Missing file: {name}');continue
        if not isinstance(info,dict) or info.get('size')!=path.stat().st_size or info.get('sha256')!=digest(path): raise ValueError(f'Evidence digest/length mismatch: {name}')
        verified.add(name)
    if any(name not in verified and name!='manifest.json' for name in actual): quality.append('Unmanifested files are not trusted')
    regions=[];registers={}
    if 'regions.json' in verified:
        regions=json.loads((root/'regions.json').read_text(encoding='utf-8'))
        if not isinstance(regions,list) or len(regions)>64: raise ValueError('Invalid region count')
        for region in regions:
            address=region.get('address');length=region.get('length');name=region.get('file')
            if not isinstance(address,int) or isinstance(address,bool) or not isinstance(length,int) or length<1 or address<0 or address+length>2**32: raise ValueError('Invalid memory mapping')
            if name not in verified: quality.append('Region file not verified');continue
            if contained(root,name).stat().st_size!=length: raise ValueError('Region length mismatch')
        sorted_regions=sorted(regions,key=lambda r:r['address'])
        if any(a['address']+a['length']>b['address'] for a,b in zip(sorted_regions,sorted_regions[1:])): raise ValueError('Overlapping captured memory regions')
    else: quality.append('Verified regions.json missing')
    if 'registers.json' in verified: registers=json.loads((root/'registers.json').read_text(encoding='utf-8'))
    else: quality.append('Verified registers.json missing')
    matched=False
    if elf_path:
        elf=Path(elf_path)
        if not elf.is_file():quality.append('ELF missing')
        elif manifest.get('elf_sha256')==digest(elf) and build_id and build_id==manifest.get('build_id'): matched=True
        else: quality.append('ELF/build identity mismatch; source attribution disabled')
    else:quality.append('No matched ELF supplied; raw evidence only')
    complete=manifest.get('completeness')=='complete' and not any('ELF' not in q and 'identity' not in q for q in quality)
    return {'schema_version':1,'analysis_version':'crash-1','analysis_status':'PASS' if complete else 'INCONCLUSIVE',
            'source_kind':'offline_crash_bundle','hardware_verified':False,'completeness':'complete' if complete else 'partial',
            'record_id':manifest.get('record_id'),'build_id':manifest.get('build_id'),'elf_matched':matched,
            'registers':registers,'regions':regions,'files':actual,'limitations':quality,
            'unwind':{'exception_frame':registers.get('exception_frame'),'verified_frames':[], 'stack_scan_candidates':[],
                      'reason':'No verified unwind rules applied; candidate addresses are not a call stack'}}
