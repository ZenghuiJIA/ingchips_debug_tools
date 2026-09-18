// Web Worker for high-frequency serial stream parsing (up to 921600 baud)
// Prevents UI thread blocking and keeps frame rate at 60 FPS

self.onmessage = (e: MessageEvent<{ rawBytes: Uint8Array; mode: 'string' | 'hex'; timestamp: string }>) => {
  const { rawBytes, mode, timestamp } = e.data;
  if (!rawBytes || rawBytes.length === 0) return;

  if (mode === 'hex') {
    let hexStr = '';
    for (let i = 0; i < rawBytes.length; i++) {
      hexStr += rawBytes[i].toString(16).padStart(2, '0').toUpperCase() + ' ';
    }
    self.postMessage({
      type: 'formatted_chunk',
      text: hexStr.trim(),
      timestamp,
      rawLength: rawBytes.length
    });
  } else {
    try {
      const decoded = new TextDecoder('utf-8', { fatal: false }).decode(rawBytes);
      self.postMessage({
        type: 'formatted_chunk',
        text: decoded,
        timestamp,
        rawLength: rawBytes.length
      });
    } catch {
      // Fallback if decoding error
      const fallback = Array.from(rawBytes).map(b => String.fromCharCode(b)).join('');
      self.postMessage({
        type: 'formatted_chunk',
        text: fallback,
        timestamp,
        rawLength: rawBytes.length
      });
    }
  }
};
