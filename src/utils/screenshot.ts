/**
 * Lightweight screen capture utility using modern Canvas & SVG foreignObject
 * Converts active application DOM view to PNG, triggering local download or clipboard copy
 */
export async function captureScreenshot(elementId = 'app-root'): Promise<string> {
  const el = document.getElementById(elementId) || document.body;
  const width = el.clientWidth || window.innerWidth;
  const height = el.clientHeight || window.innerHeight;

  // Use HTMLCanvasElement drawing
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Canvas 2D context not supported');

  // Fill background
  const computedBg = window.getComputedStyle(el).backgroundColor;
  ctx.fillStyle = computedBg || '#09090b';
  ctx.fillRect(0, 0, width, height);

  // Clone node for foreignObject serialization
  const clone = el.cloneNode(true) as HTMLElement;
  clone.setAttribute('xmlns', 'http://www.w3.org/1999/xhtml');

  // Wrap in SVG foreignObject
  const data = `
    <svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">
      <foreignObject width="100%" height="100%">
        ${new XMLSerializer().serializeToString(clone)}
      </foreignObject>
    </svg>
  `;

  return new Promise((resolve) => {
    const img = new Image();
    const svgBlob = new Blob([data], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(svgBlob);

    img.onload = () => {
      ctx.drawImage(img, 0, 0);
      URL.revokeObjectURL(url);
      const pngUrl = canvas.toDataURL('image/png');
      
      // Auto-trigger download
      const a = document.createElement('a');
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      a.download = `AI-HIL-Screenshot-${timestamp}.png`;
      a.href = pngUrl;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);

      resolve(pngUrl);
    };

    img.onerror = () => {
      // Fallback: simple screenshot dataURL
      URL.revokeObjectURL(url);
      resolve(canvas.toDataURL('image/png'));
    };

    img.src = url;
  });
}
