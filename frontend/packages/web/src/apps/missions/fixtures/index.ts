import storyboardJson from './storyboard.sample.json';
import seriesJson from './transit_series.sample.json';
import responseJson from './transit_response.sample.json';
import presetJson from './transit_preset.sample.json';
import predictRequestJson from './predict_request.sample.json';
import predictResponseJson from './predict_response.sample.json';
import type {
  PredictionRequest,
  PredictionResponse,
  Storyboard,
  TransitPreset,
  TransitResponse,
  TransitSeries,
} from '../types';

/** MOCK data for "sample data" mode, shown when the backend is unreachable or returns 501. Not a real mission or run. */
export const sampleStoryboard = storyboardJson as Storyboard;
export const sampleSeries = seriesJson as TransitSeries;
export const sampleResponse = responseJson as TransitResponse;
export const samplePreset = presetJson as TransitPreset;

/** Contract example prediction (authored placeholder or recorded result); shown with a banner when the endpoint is unavailable. */
export const samplePredictRequest = predictRequestJson as PredictionRequest;
export const samplePrediction = predictResponseJson as PredictionResponse;
