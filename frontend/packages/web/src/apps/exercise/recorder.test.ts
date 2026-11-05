// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { canRecord, startRecording } from './recorder';

afterEach(() => vi.unstubAllGlobals());

function fakes(supported = ['video/webm;codecs=vp8', 'video/webm']) {
  const track = { stop: vi.fn() };
  const stream = { getTracks: () => [track] };
  const canvas = { captureStream: vi.fn(() => stream) } as unknown as HTMLCanvasElement;
  const made: FakeRecorder[] = [];
  class FakeRecorder {
    static isTypeSupported = (t: string) => supported.includes(t);
    state: 'inactive' | 'recording' = 'inactive';
    ondataavailable: ((e: { data: Blob }) => void) | null = null;
    onstop: ((e: Event) => void) | null = null;
    onerror: (() => void) | null = null;
    constructor(
      public stream: unknown,
      public options: { mimeType: string; videoBitsPerSecond: number },
    ) {
      made.push(this);
    }
    start = vi.fn(() => (this.state = 'recording'));
    stop = vi.fn(() => {
      this.ondataavailable?.({ data: new Blob(['frames']) });
      this.state = 'inactive';
      this.onstop?.(new Event('stop'));
    });
  }
  vi.stubGlobal('MediaRecorder', FakeRecorder);
  return { canvas, track, made };
}

describe('recording the map', () => {
  it('knows whether the browser can', () => {
    expect(canRecord()).toBe(false);
    fakes();
    expect(canRecord()).toBe(true);
    expect(canRecord({})).toBe(false);
    expect(canRecord({ captureStream: () => null })).toBe(true);
  });

  it('records the canvas at the asked frame rate in the best format available, and returns the video', async () => {
    const { canvas, track, made } = fakes();
    const rec = startRecording(canvas, 24, 5_000_000);
    expect(canvas.captureStream).toHaveBeenCalledWith(24);
    expect(made[0].options).toEqual({ mimeType: 'video/webm;codecs=vp8', videoBitsPerSecond: 5_000_000 });
    expect(made[0].start).toHaveBeenCalledWith(1000);
    const blob = await rec.stop();
    expect(blob.type).toBe('video/webm;codecs=vp8');
    expect(blob.size).toBe('frames'.length);
    expect(track.stop).toHaveBeenCalled();
  });

  it('prefers vp9, and can be stopped twice', async () => {
    const { canvas, made } = fakes(['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm']);
    const rec = startRecording(canvas);
    expect(made[0].options.mimeType).toBe('video/webm;codecs=vp9');
    const [a, b] = await Promise.all([rec.stop(), rec.stop()]);
    expect(a).toBe(b);
    expect(made[0].stop).toHaveBeenCalledTimes(1);
  });

  it('says why when it cannot', () => {
    expect(() => startRecording({} as HTMLCanvasElement)).toThrow(/cannot record the map/);
    const { canvas } = fakes([]);
    expect(() => startRecording(canvas)).toThrow(/cannot record WebM/);
    vi.stubGlobal('MediaRecorder', undefined);
    expect(() => startRecording(canvas)).toThrow(/cannot record the map/);
  });

  it('reports a recorder that fails', async () => {
    const { canvas, made } = fakes();
    const rec = startRecording(canvas);
    made[0].stop = vi.fn(() => made[0].onerror?.());
    await expect(rec.stop()).rejects.toThrow('The recording failed.');
  });
});
