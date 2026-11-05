// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchMissionBlob } from './api';
import { AuthenticatedImage, GeoJsonDownload } from './media';

const imagePath = '/api/v1/missions/A/media/photo';
const blobResponse = () => ({ ok: true, blob: async () => new Blob(['image bytes'], { type: 'image/png' }) });
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
};

beforeEach(() => {
  vi.stubEnv('VITE_API_BEARER_TOKEN', 'test-secret');
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(blobResponse()));
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn().mockReturnValue('blob:test-image') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe('protected mission media', () => {
  it('loads images with the bearer header and releases the object URL on unmount', async () => {
    const view = render(<AuthenticatedImage path={imagePath} alt="Approach" />);
    const img = await screen.findByRole('img', { name: 'Approach' });
    expect(img.getAttribute('src')).toBe('blob:test-image');
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(String(url)).not.toContain('test-secret');
    expect(init?.headers).toEqual({ Authorization: 'Bearer test-secret' });
    expect(init?.redirect).toBe('error');
    view.unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test-image');
    expect(init?.signal?.aborted).toBe(true);
  });

  it('aborts previous images and ignores their late responses after the selected event changes', async () => {
    const first = deferred<ReturnType<typeof blobResponse>>();
    vi.mocked(fetch).mockReturnValueOnce(first.promise as Promise<Response>);
    const view = render(<AuthenticatedImage path={imagePath} alt="Old event" />);
    view.rerender(<AuthenticatedImage path="/api/v1/missions/B/media/photo" alt="New event" />);
    await screen.findByRole('img', { name: 'New event' });
    await act(async () => { first.resolve(blobResponse()); });
    expect(screen.queryByRole('img', { name: 'Old event' })).toBeNull();
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fetch).mock.calls[0][1]?.signal?.aborted).toBe(true);
  });

  it('revokes the old image when switching between loaded events', async () => {
    const view = render(<AuthenticatedImage path={imagePath} alt="Old event" />);
    await screen.findByRole('img', { name: 'Old event' });
    view.rerender(<AuthenticatedImage path="/api/v1/missions/B/media/photo" alt="New event" />);
    expect(screen.queryByRole('img', { name: 'Old event' })).toBeNull();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test-image');
    await screen.findByRole('img', { name: 'New event' });
  });

  it('shows authorization failure instead of a broken image', async () => {
    vi.mocked(fetch).mockResolvedValue({ ok: false, status: 401 } as Response);
    render(<AuthenticatedImage path={imagePath} alt="Approach" />);
    expect((await screen.findByRole('alert')).textContent).toContain('Image unavailable');
    expect(screen.queryByRole('img')).toBeNull();
  });

  it('renders the labeled sample image without sending a credentialed request', () => {
    render(<AuthenticatedImage path="data:image/svg+xml,sample" alt="Sample" sample />);
    expect(screen.getByRole('img').getAttribute('src')).toMatch(/^data:image/);
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each(['https://untrusted.example/photo', 'http://localhost:4000/untrusted', 'data:image/svg+xml,x'])('never forwards the bearer token to %s', async (path) => {
    await expect(fetchMissionBlob(path)).rejects.toThrow(/outside/);
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe('protected GeoJSON download', () => {
  it('fetches with bearer auth, downloads a blob without a token URL, and releases it', async () => {
    const clicked: { href: string; filename: string }[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push({ href: this.href, filename: this.download });
    });
    const view = render(<GeoJsonDownload missionId="A" />);
    fireEvent.click(screen.getByRole('button', { name: 'Download GeoJSON' }));
    await waitFor(() => expect(clicked).toHaveLength(1));
    expect(clicked[0]).toEqual({ href: 'blob:test-image', filename: 'A.geojson' });
    expect(vi.mocked(fetch).mock.calls[0][1]?.headers).toEqual({ Authorization: 'Bearer test-secret' });
    expect(document.querySelector('a[download]')).toBeNull();
    view.unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test-image');
  });

  it('does not download a stale mission after switching selection', async () => {
    const pending = deferred<ReturnType<typeof blobResponse>>();
    vi.mocked(fetch).mockReturnValueOnce(pending.promise as Promise<Response>);
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    const view = render(<GeoJsonDownload missionId="A" />);
    fireEvent.click(screen.getByRole('button', { name: 'Download GeoJSON' }));
    view.rerender(<GeoJsonDownload missionId="B" />);
    await act(async () => { pending.resolve(blobResponse()); });
    expect(click).not.toHaveBeenCalled();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect((screen.getByRole('button', { name: 'Download GeoJSON' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('shows a readable error and permits retry when download fails', async () => {
    vi.mocked(fetch).mockResolvedValueOnce({ ok: false, status: 401 } as Response);
    render(<GeoJsonDownload missionId="A" />);
    fireEvent.click(screen.getByRole('button', { name: 'Download GeoJSON' }));
    expect((await screen.findByRole('alert')).textContent).toContain('Download unavailable');
    expect((screen.getByRole('button', { name: 'Download GeoJSON' }) as HTMLButtonElement).disabled).toBe(false);
  });
});
