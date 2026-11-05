import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, buildMediaForm, buildMediaMetadata, buildTrackForm, isUnavailable, missionsApi, runTransit, serviceUrl, toUtcIso } from './api';
import { samplePreset, sampleResponse } from './fixtures';

afterEach(() => vi.unstubAllGlobals());

const json = (status: number, body: unknown) => ({ ok: status < 400, status, statusText: 'x', json: async () => body });

describe('multipart construction', () => {
  it('builds the track form with only the fields given', () => {
    const f = buildTrackForm({ file: new Blob(['a,b']), filename: 't.csv', format: 'nmea', utcOffsetMin: -300, nmeaDate: '2026-11-05' });
    expect(f.get('format')).toBe('nmea');
    expect(f.get('utc_offset_min')).toBe('-300');
    expect(f.get('nmea_date')).toBe('2026-11-05');
    expect((f.get('file') as File).name).toBe('t.csv');
    const g = buildTrackForm({ file: new Blob(['x']), format: 'csv' });
    expect(g.has('utc_offset_min')).toBe(false);
    expect(g.has('nmea_date')).toBe(false);
  });
  it('builds the media form with an image part and JSON metadata', () => {
    const f = buildMediaForm({ file: new Blob(['x'], { type: 'image/png' }), filename: 'a.png', capturedUtc: '2026-11-05T12:03', exifUtcOffsetMin: -300, cameraClockOffsetS: 12.5, caption: ' dock ' });
    expect((f.get('image') as File).name).toBe('a.png');
    expect(JSON.parse(f.get('metadata') as string)).toEqual({ captured_utc: '2026-11-05T12:03:00Z', exif_utc_offset_min: -300, camera_clock_offset_s: 12.5, caption: 'dock' });
  });
  it('omits blank and zero metadata', () => {
    expect(buildMediaMetadata({ file: new Blob([]), capturedUtc: '', exifUtcOffsetMin: null, cameraClockOffsetS: 0, caption: '  ' })).toEqual({});
  });
  it('treats local datetimes as UTC and keeps explicit zones', () => {
    expect(toUtcIso('2026-11-05T12:03:09')).toBe('2026-11-05T12:03:09Z');
    expect(toUtcIso('2026-11-05T12:03:00-05:00')).toBe('2026-11-05T12:03:00-05:00');
  });
});

describe('requests', () => {
  it('routes service paths through the proxy prefix', () => {
    expect(serviceUrl('/api/v1/missions')).toBe('http://localhost:4000/api/modeling/api/v1/missions');
    expect(serviceUrl('data:image/svg+xml,x')).toBe('data:image/svg+xml,x');
  });
  it('maps non-2xx to ApiError and classifies unavailability', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(501, { detail: 'not implemented' })));
    const e = await missionsApi.listMissions().catch((x: unknown) => x);
    expect(e).toBeInstanceOf(ApiError);
    expect(isUnavailable(e)).toBe(true);
    expect(isUnavailable(new TypeError('Failed to fetch'))).toBe(true);
    expect(isUnavailable(new ApiError(422, 'bad'))).toBe(false);
  });
  it('sends multipart without a manual content type', async () => {
    const fetch = vi.fn().mockResolvedValue(json(200, {}));
    vi.stubGlobal('fetch', fetch);
    const form = buildTrackForm({ file: new Blob(['x']), format: 'csv' });
    await missionsApi.ingestTrackFile('m 1', form);
    const [url, init] = fetch.mock.calls[0];
    expect(url).toContain('/api/v1/missions/m%201/track/file');
    expect(init.body).toBe(form);
    expect(init.headers['Content-Type']).toBeUndefined();
  });
});

describe('transit job polling', () => {
  it('posts, polls until succeeded and returns the envelope', async () => {
    const accepted = { job_id: 'j1', kind: 'transit', status_url: '/api/v1/jobs/j1', events_url: '/api/v1/jobs/j1/events' };
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(json(202, accepted))
      .mockResolvedValueOnce(json(200, { state: 'running', progress: 0.4 }))
      .mockResolvedValueOnce(json(200, { state: 'succeeded', progress: 1, result: sampleResponse }));
    vi.stubGlobal('fetch', fetch);
    const progress: number[] = [];
    const res = await runTransit(samplePreset.request, (p) => progress.push(p));
    expect(res.result.series_url).toBe(sampleResponse.result.series_url);
    expect(progress).toEqual([0.4, 1]);
    expect(fetch.mock.calls[0][0]).toContain('/api/v1/transit/simulate');
    expect(fetch.mock.calls[0][1].method).toBe('POST');
    expect(fetch.mock.calls[1][0]).toContain('/api/v1/jobs/j1');
  });
  it('surfaces a failed job', async () => {
    const accepted = { job_id: 'j2', kind: 'transit', status_url: '/api/v1/jobs/j2', events_url: '' };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json(202, accepted)).mockResolvedValueOnce(json(200, { state: 'failed', progress: 0, error: 'bad route' })));
    await expect(runTransit(samplePreset.request)).rejects.toThrow('bad route');
  });
});
