import { isTauri,safeInvoke } from './ipc';
export function debugCall<T>(operation:string,args:Record<string,unknown>={}):Promise<T>{
  if(!isTauri())return Promise.reject(new Error('浏览器预览不执行调试分析；请使用桌面程序'));
  return safeInvoke<T>('embedded_debug_command',{operation,arguments:args});
}
