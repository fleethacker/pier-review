import type { AppDefinition } from '../../scene/app';
import type { SceneEdit, SceneEntity, SceneLink } from '../../scene/types';
import { Panel } from '../../shell/ui';

/** A tiny non-mooring app that exercises the shell: shapes, links, dragging and selection. Dev builds only. */
export const demoApp: AppDefinition = {
  id: 'demo',
  title: 'Shell demo',
  description: 'Generic shapes to exercise the shell; not part of the mooring application.',
  start({ store }) {
    const pier: SceneEntity = {
      id: 'deck',
      kind: 'structure',
      label: 'Deck',
      pose: { x: 0, y: 0, z: 0, headingDeg: 0 },
      geometry: { type: 'polygon', points: [[0, 0], [400, 0], [400, -80], [0, -80]], heightM: 3 },
      color: '#8a8f98',
      selectable: false,
    };
    const post = (id: string, x: number): SceneEntity => ({
      id,
      kind: 'post',
      label: id,
      pose: { x, y: -2, z: 3, headingDeg: 0 },
      geometry: { type: 'point', sizePx: 9 },
      color: '#ffd54f',
      selectable: true,
      props: [{ label: 'x', value: `${x} m` }],
    });
    const barge: SceneEntity = {
      id: 'barge',
      kind: 'vessel',
      label: 'Barge',
      pose: { x: 200, y: 14, z: 0, headingDeg: 0 },
      geometry: { type: 'polygon', points: [[-60, -9], [60, -9], [70, 0], [60, 9], [-60, 9]], heightM: 5 },
      color: '#3b6ea5',
      editable: { moveAxis: 'x', bounds: { minX: 70, maxX: 330 }, snapM: 1 },
      selectable: true,
    };
    const links = (): SceneLink[] =>
      ['p1', 'p2'].map((id, i) => ({
        id: `line-${id}`,
        kind: 'line',
        from: { x: i === 0 ? 100 : 300, y: -2, z: 3 },
        to: { entityId: 'barge', x: i === 0 ? -50 : 50, y: -9, z: 5 },
        status: 'GREEN',
      }));
    store.setContent({
      frame: { lonDeg: -76.3305, latDeg: 36.9585, xBearingTrueDeg: 105 },
      entities: [pier, post('p1', 100), post('p2', 300), barge],
      links: links(),
      vectors: [],
    });
    return {
      Sidebar: () => (
        <Panel title="Shell demo" className="p-4">
          <p className="text-xs text-mil-text">Drag the barge along the deck. Click a post or the barge to inspect.</p>
        </Panel>
      ),
      onEdit(edit: SceneEdit) {
        if (edit.type === 'move' && edit.final) store.patchEntity(edit.entityId, { status: 'AMBER' });
      },
      dispose() {},
    };
  },
};
