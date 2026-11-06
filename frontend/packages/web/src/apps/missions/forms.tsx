import { useState } from 'react';
import { Button, Field, Select, inputClass } from '../../shell/ui';
import { useController, useMissions } from './context';
import { Heading } from './parts';
import { TRACK_FORMATS, type TrackFormat } from './types';

const num = (s: string): number | null => (s.trim() === '' || !Number.isFinite(Number(s)) ? null : Number(s));

export function CreateMissionForm() {
  const c = useController();
  const busy = useMissions((s) => s.busy);
  const [name, setName] = useState('');
  const [vessel, setVessel] = useState('');
  return (
    <form
      aria-label="Create mission"
      className="space-y-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (!name.trim() || !vessel.trim()) return;
        void c.createMission(name.trim(), vessel.trim()).then((m) => m && (setName(''), setVessel('')));
      }}
    >
      <Heading>New mission</Heading>
      <Field label="Mission name">
        <input className={inputClass} value={name} maxLength={200} onChange={(e) => setName(e.target.value)} required />
      </Field>
      <Field label="Vessel id (hull number, MMSI)">
        <input className={inputClass} value={vessel} maxLength={120} onChange={(e) => setVessel(e.target.value)} required />
      </Field>
      <Button type="submit" size="sm" variant="secondary" disabled={!!busy}>
        Create
      </Button>
    </form>
  );
}

export function TrackUploadForm() {
  const c = useController();
  const busy = useMissions((s) => s.busy);
  const missionId = useMissions((s) => s.missionId);
  const [file, setFile] = useState<File | null>(null);
  const [format, setFormat] = useState<TrackFormat>('csv');
  const [offset, setOffset] = useState('');
  const [nmeaDate, setNmeaDate] = useState('');
  return (
    <form
      aria-label="Upload track file"
      className="space-y-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (file) void c.uploadTrack({ file, format, utcOffsetMin: num(offset), nmeaDate: format === 'nmea' ? nmeaDate || null : null });
      }}
    >
      <Heading>Upload track</Heading>
      <Field label="Track file (csv, gpx, nmea, geojson; max 20 MB)">
        <input type="file" className={inputClass} onChange={(e) => setFile(e.target.files?.[0] ?? null)} accept=".csv,.gpx,.nmea,.txt,.log,.geojson,.json" />
      </Field>
      <Field label="Format">
        <Select value={format} onChange={(v) => setFormat(v as TrackFormat)} options={TRACK_FORMATS.map((f) => ({ value: f, label: f }))} />
      </Field>
      <Field label="UTC offset of naive timestamps (minutes east, blank if the file has zones)">
        <input className={inputClass} inputMode="numeric" value={offset} onChange={(e) => setOffset(e.target.value)} placeholder="-300" />
      </Field>
      {format === 'nmea' && (
        <Field label="NMEA date (YYYY-MM-DD, for GGA-only files)">
          <input className={inputClass} type="date" value={nmeaDate} onChange={(e) => setNmeaDate(e.target.value)} />
        </Field>
      )}
      <Button type="submit" size="sm" variant="secondary" disabled={!file || !missionId || !!busy}>
        Upload track
      </Button>
    </form>
  );
}

export function TrackResult() {
  const r = useMissions((s) => s.trackResult);
  if (!r) return null;
  const rows: [string, number][] = [['accepted', r.accepted], ['rejected', r.rejected], ['duplicates', r.duplicates], ['reordered', r.reordered], ['stored fixes', r.fix_count]];
  return (
    <section aria-label="Track ingest result" className="mt-2 rounded-sm border border-mil-border p-2 text-[11px]">
      <p className="mil-label mb-1">Track result ({r.format})</p>
      <dl className="grid grid-cols-2 gap-x-3">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between">
            <dt className="text-mil-dim">{k}</dt>
            <dd className={k === 'rejected' && v > 0 ? 'text-mil-red' : 'text-white'}>{v}</dd>
          </div>
        ))}
      </dl>
      {(r.errors ?? []).length > 0 && (
        <ul className="mt-1 max-h-24 list-disc overflow-y-auto pl-4 text-mil-red">
          {(r.errors ?? []).map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function ImageUploadForm() {
  const c = useController();
  const busy = useMissions((s) => s.busy);
  const missionId = useMissions((s) => s.missionId);
  const [file, setFile] = useState<File | null>(null);
  const [captured, setCaptured] = useState('');
  const [exifOffset, setExifOffset] = useState('');
  const [clockOffset, setClockOffset] = useState('');
  const [caption, setCaption] = useState('');
  return (
    <form
      aria-label="Upload image"
      className="space-y-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (file) void c.uploadImage({ file, capturedUtc: captured || null, exifUtcOffsetMin: num(exifOffset), cameraClockOffsetS: num(clockOffset), caption });
      }}
    >
      <Heading>Add image</Heading>
      <Field label="Image (JPEG, PNG, WebP; max 8 MB)">
        <input type="file" className={inputClass} accept="image/jpeg,image/png,image/webp" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </Field>
      <Field label="Captured time override (UTC, replaces EXIF)">
        <input className={inputClass} type="datetime-local" step={1} value={captured} onChange={(e) => setCaptured(e.target.value)} />
      </Field>
      <Field label="EXIF UTC offset (minutes east, if EXIF has none)">
        <input className={inputClass} inputMode="numeric" value={exifOffset} onChange={(e) => setExifOffset(e.target.value)} placeholder="-300" />
      </Field>
      <Field label="Camera clock offset (seconds to add; camera slow = positive)">
        <input className={inputClass} inputMode="decimal" value={clockOffset} onChange={(e) => setClockOffset(e.target.value)} placeholder="0" />
      </Field>
      <Field label="Caption">
        <input className={inputClass} value={caption} maxLength={2000} onChange={(e) => setCaption(e.target.value)} />
      </Field>
      <Button type="submit" size="sm" variant="secondary" disabled={!file || !missionId || !!busy}>
        Upload image
      </Button>
    </form>
  );
}

export function ReportForm() {
  const c = useController();
  const busy = useMissions((s) => s.busy);
  const missionId = useMissions((s) => s.missionId);
  const [time, setTime] = useState('');
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [lat, setLat] = useState('');
  const [lon, setLon] = useState('');
  const la = num(lat);
  const lo = num(lon);
  const pairBad = (lat.trim() === '') !== (lon.trim() === '') || (la != null && Math.abs(la) > 90) || (lo != null && Math.abs(lo) > 180);
  return (
    <form
      aria-label="Add report"
      className="space-y-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (!time || !title.trim() || pairBad) return;
        const t = time.length === 16 ? `${time}:00Z` : `${time}Z`;
        void c.addReport({ t_utc: t, title: title.trim(), body, ...(la != null && lo != null ? { lat: la, lon: lo } : {}), tags: [] }).then((saved) => {
          if (!saved) return;
          setTitle((current) => current === title ? '' : current);
          setBody((current) => current === body ? '' : current);
        });
      }}
    >
      <Heading>Add report</Heading>
      <Field label="Time (UTC)">
        <input className={inputClass} type="datetime-local" step={1} value={time} onChange={(e) => setTime(e.target.value)} required />
      </Field>
      <Field label="Title">
        <input className={inputClass} value={title} maxLength={300} onChange={(e) => setTitle(e.target.value)} required />
      </Field>
      <Field label="Body">
        <textarea className={inputClass} rows={3} value={body} maxLength={20000} onChange={(e) => setBody(e.target.value)} />
      </Field>
      <div className="grid grid-cols-2 gap-2">
        <Field label="Stated latitude (optional)">
          <input className={inputClass} inputMode="decimal" value={lat} onChange={(e) => setLat(e.target.value)} />
        </Field>
        <Field label="Stated longitude (optional)">
          <input className={inputClass} inputMode="decimal" value={lon} onChange={(e) => setLon(e.target.value)} />
        </Field>
      </div>
      {pairBad && <p className="text-[11px] text-mil-red">Give latitude (-90..90) and longitude (-180..180) together, or neither.</p>}
      <Button type="submit" size="sm" variant="secondary" disabled={!missionId || !!busy || pairBad}>
        Add report
      </Button>
    </form>
  );
}
