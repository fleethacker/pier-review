import { superstructureProfile } from '../mapping';

export type SectionView = 'side' | 'forward' | 'aft';
export type SectionPoint = [number, number];
export interface SectionShape { name: string; points: SectionPoint[]; fill: string; closed: boolean }

/** Illustration only: the map's class artwork, never hydrostatic/contact geometry. */
export function sectionSilhouette(hullType: string | undefined, view: SectionView, length: number, beam: number, deck: number): SectionShape[] {
  const type = hullType ?? 'DDG';
  const carrier = ['CVN', 'LHD', 'LHA'].includes(type);
  const side = view === 'side';
  const direction = view === 'aft' ? -1 : 1;
  const span = side ? length : beam;
  const shapes: SectionShape[] = [];
  const shape = (name: string, points: SectionPoint[], fill: string, closed = true) => shapes.push({ name, points, fill, closed });
  const line = (name: string, points: SectionPoint[]) => shape(name, points, 'none', false);
  const box = (name: string, left: number, right: number, bottom: number, top: number, fill: string) => shape(name, [[left, bottom], [left, top], [right, top], [right, bottom]], fill);
  box(carrier ? 'flight-deck' : 'main-deck', -span / 2, span / 2, deck - 1.6, deck, '#9eafbb');
  const blocks = superstructureProfile(type).map((block, index) => {
    const footprint: SectionPoint[] = block.poly ?? [[block.x - block.len / 2, block.y - block.w / 2], [block.x + block.len / 2, block.y + block.w / 2]];
    const along = footprint.map(([x, y]) => side ? x * length : direction * y * beam);
    const distance = footprint.reduce((sum, [x, y]) => sum + (side ? -y : direction * x), 0) / footprint.length;
    return { block, index, left: Math.min(...along), right: Math.max(...along), distance };
  }).sort((a, b) => a.distance - b.distance);
  for (const { block, index, left, right } of blocks) {
    // The shared map artwork uses meters vertically; this view uses feet.
    const bottom = deck + (block.lift ?? 0) / 0.3048;
    const top = bottom + block.h / 0.3048;
    if (block.h < 1) continue; // Horizontal deck markings are not walls in elevation.
    const inset = Math.min((right - left) * 0.14, 3);
    shape(`superstructure-${index}`, [[left, bottom], [left + inset, top], [right - inset, top], [right, bottom]], block.color ?? '#7ba3d1');
    if (block.h >= 4 && block.h <= 9 && (right - left) > span * 0.06) line(`bridge-${index}`, [[left + inset, top - 2], [right - inset, top - 2]]);
    if (block.h >= 8 && (right - left) < span * 0.09) {
      const middle = (left + right) / 2;
      const width = Math.max(right - left, span * 0.045);
      line(`radar-${index}`, [[middle - width, top - 4], [middle + width, top - 4]]);
      line(`antenna-${index}`, [[middle, top], [middle, top + 5]]);
    }
  }
  if (side && !carrier) {
    line('forward-gun-barrel', [[0.32 * length, deck + 7], [0.385 * length, deck + 10]]);
    if (type === 'CG') line('aft-gun-barrel', [[-0.31 * length, deck + 7], [-0.375 * length, deck + 10]]);
    line('helicopter-deck', [[-0.48 * length, deck + 1], [-0.38 * length, deck + 1]]);
  }
  if (!side) {
    if (view === 'forward') line('bow-centerline', [[0, deck], [0, 0]]);
    else if (type === 'DDG') {
      box('port-hangar', -0.27 * beam, -0.08 * beam, deck, deck + 12, '#263e51');
      box('starboard-hangar', 0.08 * beam, 0.27 * beam, deck, deck + 12, '#263e51');
    } else if (type === 'LHD' || type === 'LHA') box('well-deck-door', -0.22 * beam, 0.22 * beam, 1, deck * 0.65, '#263e51');
  }
  return shapes;
}
