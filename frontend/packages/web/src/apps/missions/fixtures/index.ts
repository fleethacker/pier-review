import storyboardJson from './storyboard.sample.json';
import seriesJson from './transit_series.sample.json';
import responseJson from './transit_response.sample.json';
import presetJson from './transit_preset.sample.json';
import type { Storyboard, TransitPreset, TransitResponse, TransitSeries } from '../types';

/** MOCK data for "sample data" mode, shown when the backend is unreachable or returns 501. Not a real mission or run. */
export const sampleStoryboard = storyboardJson as Storyboard;
export const sampleSeries = seriesJson as TransitSeries;
export const sampleResponse = responseJson as TransitResponse;
export const samplePreset = presetJson as TransitPreset;
