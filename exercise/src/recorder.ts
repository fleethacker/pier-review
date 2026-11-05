/** Record the map as a video: the canvas, as it is drawn, saved as a WebM file. Labels and panels (HTML) are not in it. */

export interface Recording {
  /** Stop and resolve with the video. */
  stop(): Promise<Blob>;
}

const TYPES = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'];

export function canRecord(canvas?: HTMLCanvasElement | { captureStream?: unknown }): boolean {
  return typeof MediaRecorder !== 'undefined' && (!canvas || typeof canvas.captureStream === 'function');
}

/** Start recording a canvas. Throws a readable error if this browser cannot. */
export function startRecording(canvas: HTMLCanvasElement, fps = 30, bitsPerSecond = 8_000_000): Recording {
  if (typeof MediaRecorder === 'undefined' || typeof canvas.captureStream !== 'function') {
    throw new Error('This browser cannot record the map. Try a recent Chrome, Edge or Firefox.');
  }
  const type = TYPES.find((t) => MediaRecorder.isTypeSupported(t));
  if (!type) throw new Error('This browser cannot record WebM video.');
  const stream = canvas.captureStream(fps);
  const chunks: Blob[] = [];
  const recorder = new MediaRecorder(stream, { mimeType: type, videoBitsPerSecond: bitsPerSecond });
  recorder.ondataavailable = (e) => e.data.size > 0 && chunks.push(e.data);
  recorder.start(1000);
  let stopped: Promise<Blob> | null = null;
  return {
    stop() {
      stopped ??= new Promise<Blob>((resolve, reject) => {
        recorder.onstop = () => {
          stream.getTracks().forEach((t) => t.stop());
          resolve(new Blob(chunks, { type }));
        };
        recorder.onerror = () => reject(new Error('The recording failed.'));
        if (recorder.state === 'inactive') recorder.onstop?.(new Event('stop'));
        else recorder.stop();
      });
      return stopped;
    },
  };
}
