import type { components as M } from '../../api/modeling';

type S = M['schemas'];
export type Mission = S['Mission'];
export type MissionTrack = S['MissionTrack'];
export type MissionCreate = S['MissionCreate'];
export type Storyboard = S['Storyboard'];
export type StoryboardEvent = S['StoryboardEvent'];
export type LocatedAt = S['LocatedAt'];
export type LocateMethod = LocatedAt['method'];
export type TrackFix = S['TrackFix'];
export type TrackIngestResult = S['TrackIngestResult'];
export type MediaItem = S['MediaItem'];
export interface MediaMetadata {
  captured_utc?: string;
  exif_utc_offset_min?: number;
  camera_clock_offset_s?: number;
  caption?: string;
  tags?: string[];
}
export type Report = S['Report'];
export type ReportCreate = S['ReportCreate'];
export type Validity = S['Validity'];
export type TransitRequest = S['TransitRequest'];
export type VesselTransit = S['VesselTransit'];
export type TransitPreset = S['TransitPreset'];
export type TransitSeries = S['TransitSeries'];
export type TransitFrame = S['TransitFrame'];
export type TransitVesselState = S['TransitVesselState'];
export type TransitTugState = S['TransitTugState'];
export type TransitResponse = S['TransitResponse'];
export type TransitEvent = S['TransitEvent'];
export type TransitVesselSummary = S['TransitVesselSummary'];
export type JobAccepted = S['JobAccepted'];

export type TrackFormat = 'csv' | 'gpx' | 'nmea' | 'geojson';
export const TRACK_FORMATS: TrackFormat[] = ['csv', 'gpx', 'nmea', 'geojson'];

export type PredictionRequest = S['PredictionRequest'];
export type PredictionResponse = S['PredictionResponse'];
export type PredictionPreset = S['PredictionPreset'];
export type PredictionAlternative = S['PredictionAlternative'];
export type ObservedShipState = S['ObservedShipState'];
export type WhatIf = S['WhatIf'];
