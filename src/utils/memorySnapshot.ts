export async function readMemoryRange(
  invoke: (command: string, args: Record<string, any>) => Promise<any>,
  address: number, count: number, probeId: string,
): Promise<number[]> {
  if (!probeId) throw new Error('请明确选择探针');
  if (!Number.isInteger(count) || count < 1 || count > 1024 * 1024 || address + count > 2 ** 32) {
    throw new Error('快照大小必须为 1 B~1 MB，且不能超出地址范围');
  }
  const bytes: number[] = [];
  while (bytes.length < count) {
    const size = Math.min(4096, count - bytes.length);
    const result = await invoke('pyocd_read_memory', {
      address: '0x' + (address + bytes.length).toString(16), count: size, probeId, targetOverride: null,
    });
    if (!Array.isArray(result.bytes) || result.bytes.length !== size) throw new Error('快照读取不完整');
    bytes.push(...result.bytes);
  }
  return bytes;
}
