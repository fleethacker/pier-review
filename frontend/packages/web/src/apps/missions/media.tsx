import { useEffect, useRef, useState } from 'react';
import { describeError } from '../mooring/api';
import { fetchMissionBlob, missionsApi } from './api';

/** Protected images are fetched with Authorization; object URLs never contain credentials. */
export function AuthenticatedImage({ path, alt, sample = false }: { path: string; alt: string; sample?: boolean }) {
  if (sample && path.startsWith('data:image/')) return <img src={path} alt={alt} className="mt-2 max-h-56 w-full rounded-sm border border-mil-border object-contain" />;
  return <ProtectedImage key={path} path={path} alt={alt} />;
}

function ProtectedImage({ path, alt }: { path: string; alt: string }) {
  const [resource, setResource] = useState<{ url?: string; error?: string } | null>(null);
  useEffect(() => {
    const abort = new AbortController();
    let url: string | null = null;
    void fetchMissionBlob(path, abort.signal).then((blob) => {
      if (abort.signal.aborted) return;
      url = URL.createObjectURL(blob);
      setResource({ url });
    }).catch((error: unknown) => {
      if (!abort.signal.aborted) setResource({ error: describeError(error) });
    });
    return () => {
      abort.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [path]);
  const current = resource;
  const src = resource?.url;
  if (src) return <img src={src} alt={alt} className="mt-2 max-h-56 w-full rounded-sm border border-mil-border object-contain" />;
  return <p role={current?.error ? 'alert' : 'status'} className="mt-2 text-[11px] text-mil-dim">
    {current?.error ? `Image unavailable: ${current.error}` : 'Loading image…'}
  </p>;
}

export function GeoJsonDownload({ missionId, disabled = false }: { missionId: string; disabled?: boolean }) {
  return <ProtectedDownload key={missionId} missionId={missionId} disabled={disabled} />;
}

function ProtectedDownload({ missionId, disabled }: { missionId: string; disabled: boolean }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);
  const resources = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  useEffect(() => {
    const urls = resources.current;
    return () => {
      request.current?.abort();
      for (const [url, timer] of urls) {
        clearTimeout(timer);
        URL.revokeObjectURL(url);
      }
      urls.clear();
    };
  }, [missionId]);
  const download = async () => {
    if (busy || disabled) return;
    const abort = new AbortController();
    request.current?.abort();
    request.current = abort;
    setBusy(true);
    setError(null);
    try {
      const blob = await fetchMissionBlob(missionsApi.geojsonUrl(missionId), abort.signal);
      if (abort.signal.aborted) return;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `${missionId}.geojson`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      // Release after the browser has consumed the click, or immediately on unmount.
      resources.current.set(url, setTimeout(() => {
        URL.revokeObjectURL(url);
        resources.current.delete(url);
      }, 1000));
    } catch (error: unknown) {
      if (!abort.signal.aborted) setError(describeError(error));
    } finally {
      if (!abort.signal.aborted) setBusy(false);
    }
  };
  return <div className="mt-2 text-[11px]">
    <button type="button" onClick={() => void download()} disabled={disabled || busy}
      className="text-mil-cyan underline disabled:cursor-not-allowed disabled:opacity-50">
      {busy ? 'Preparing GeoJSON…' : 'Download GeoJSON'}
    </button>
    {disabled && <p className="text-mil-dim">Download unavailable for the offline sample.</p>}
    {error && <p role="alert" className="text-mil-amber">Download unavailable: {error}</p>}
  </div>;
}
