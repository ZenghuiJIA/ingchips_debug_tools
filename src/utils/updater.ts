export const UPDATER_AUTO_CHECK_KEY = 'aihil.updater.autoCheck';
export const UPDATER_AUTO_DOWNLOAD_KEY = 'aihil.updater.autoDownload';

export function readUpdaterPref(key: string, fallback: boolean): boolean {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return fallback;
    return raw === 'true';
  } catch {
    return fallback;
  }
}

export function saveUpdaterPref(key: string, value: boolean): void {
  localStorage.setItem(key, value ? 'true' : 'false');
}

export function formatBytesMiB(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '0.0 MiB';
  return `${(bytes / 1048576).toFixed(1)} MiB`;
}

export function formatUpdateError(error: unknown): string {
  const detail = error instanceof Error ? error.message : String(error);
  if (/404|release.*not found/i.test(detail)) {
    return 'GitHub 发布页暂未提供 latest.json 更新清单，请前往发布页手动下载安装包。';
  }
  if (/could not fetch a valid release JSON/i.test(detail)) {
    return '无法读取有效的 latest.json 更新清单，请检查 GitHub 网络或前往发布页下载。';
  }
  if (/signature|pubkey|minisign|public key/i.test(detail)) {
    return '更新包签名校验失败，已终止安装。请重新检查更新或前往 GitHub 发布页下载。';
  }
  if (/timed?\s*out|timeout/i.test(detail)) {
    return '连接 GitHub 超时，请检查网络或系统代理后重试。';
  }
  return `更新失败，请重试或打开 GitHub 发布页。\n${detail.slice(0, 1200)}`;
}
