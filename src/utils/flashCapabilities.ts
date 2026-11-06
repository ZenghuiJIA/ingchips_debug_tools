/** Capability restriction shared by SWD flash entry points, not serial ISP or reset. */
export function pyocdFlashUnsupportedReason(target: string): string | null {
  // Keep aliases aligned with the daemon's fail-closed ING20 flash guard.
  const normalized = target.trim().toLowerCase().replace(/[-_]/g, '');
  if (!['ing20', 'ing200', 'ing2000'].includes(normalized)) return null;
  return 'ING20 SWD 烧录暂不可用：内嵌烧录算法尚需验证；外部 pyocd CLI 无法保留取消、探针独占、所选 Pack 和烧录后状态契约，因此不会自动回退。此限制不影响其他芯片或 ING 串口 ISP 入口。';
}
