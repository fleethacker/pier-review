import { useState } from 'react';
import { credentialState, GATEWAY_REQUIRED, setRuntimeCredential } from '../lib/credentials';
import { Button, inputClass } from './ui';

/** Optional direct-service access. Domino users normally rely on the private gateway session. */
export function RuntimeAccess() {
  const configured = credentialState.use((state) => state.configured);
  const [value, setValue] = useState('');
  return <details className="relative text-[11px]">
    <summary className="cursor-pointer text-mil-cyan">Access: {configured ? 'API credential' : 'gateway / local'}</summary>
    <form className="absolute right-0 top-6 z-50 w-80 space-y-2 rounded border border-mil-border bg-mil-panel p-3 shadow-lg"
      onSubmit={(event) => { event.preventDefault(); setRuntimeCredential(value); setValue(''); }}>
      <p>Private deployments use the signed-in gateway session. For a directly protected service, enter your own API credential here.</p>
      <label className="block">API credential
        <input type="password" className={inputClass} autoComplete="off" value={value} onChange={(event) => setValue(event.target.value)} />
      </label>
      <p className="text-mil-dim">Kept only in this tab's memory; refreshing clears it. Changing access restarts the workspaces and discards unsaved work.</p>
      <p className="text-mil-amber">{GATEWAY_REQUIRED}</p>
      <div className="flex gap-2"><Button size="sm" disabled={!value.trim()}>Apply credential</Button>
        {configured && <Button size="sm" type="button" variant="secondary" onClick={() => { setRuntimeCredential(''); setValue(''); }}>Clear credential</Button>}</div>
    </form>
  </details>;
}
