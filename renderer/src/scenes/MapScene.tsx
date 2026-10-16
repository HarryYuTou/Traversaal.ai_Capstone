import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
// Shared with the Python validator, which checks plans against the same region names.
import regions from '../../../schemas/map-regions.json';
import {useTheme} from '../theme';
import type {TimelineScene} from '../types';
import {Kicker, RisingWords} from './SceneFrame';
import {appear, ease, highlightLevel, revealFrame} from './timing';

type Props = {scene: Extract<TimelineScene, {template: 'map'}>; label: string};
type Bounds = {west: number; south: number; east: number; north: number};
type Point = [number, number];

// The region is fitted between the title block and the captions; the grid runs to the frame's edges.
const FIT = {left: 150, right: 150, top: 290, bottom: 230};
const RADIANS = Math.PI / 180;

// Unscaled projections, as in d3-geo: Natural Earth I for wide regions, Mercator for smaller ones.
const naturalEarth = (lon: number, lat: number): Point => {
  const [lambda, phi] = [lon * RADIANS, lat * RADIANS];
  const phi2 = phi * phi;
  const phi4 = phi2 * phi2;
  return [lambda * (0.8707 - 0.131979 * phi2 + phi4 * (-0.013791 + phi4 * (0.003971 * phi2 - 0.001529 * phi4))),
    phi * (1.007226 + phi2 * (0.015085 + phi4 * (-0.044475 + 0.028874 * phi2 - 0.005916 * phi4)))];
};
const mercator = (lon: number, lat: number): Point =>
  [lon * RADIANS, Math.log(Math.tan(Math.PI / 4 + (Math.max(-85, Math.min(85, lat)) * RADIANS) / 2))];

/** A lon/lat -> pixel function that fits the region's bounds into the frame's map area. */
const fitted = (region: string, width: number, height: number) => {
  const bounds: Bounds = (regions as Record<string, Bounds>)[region] ?? regions.world;
  const raw = bounds.east - bounds.west > 90 ? naturalEarth : mercator;
  const edge: Point[] = [];
  for (let step = 0; step <= 12; step++) {
    const lon = bounds.west + ((bounds.east - bounds.west) * step) / 12;
    const lat = bounds.south + ((bounds.north - bounds.south) * step) / 12;
    edge.push(raw(lon, bounds.south), raw(lon, bounds.north), raw(bounds.west, lat), raw(bounds.east, lat));
  }
  const xs = edge.map(([x]) => x);
  const ys = edge.map(([, y]) => y);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const boxWidth = width - FIT.left - FIT.right;
  const boxHeight = height - FIT.top - FIT.bottom;
  const scale = Math.min(boxWidth / (maxX - minX), boxHeight / (maxY - minY));
  const offsetX = FIT.left + (boxWidth - scale * (maxX - minX)) / 2 - scale * minX;
  const offsetY = FIT.top + (boxHeight - scale * (maxY - minY)) / 2 + scale * maxY;
  return (lon: number, lat: number): Point => {
    const [x, y] = raw(lon, lat);
    return [offsetX + scale * x, offsetY - scale * y];
  };
};

/** Lines of longitude and latitude every 10 degrees, as one SVG path. */
const graticule = (project: (lon: number, lat: number) => Point) => {
  const line = (points: Point[]) => points.map(([x, y], index) => `${index ? 'L' : 'M'} ${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
  const parts: string[] = [];
  for (let lon = -180; lon <= 180; lon += 10) {
    parts.push(line(Array.from({length: 33}, (_, step) => project(lon, -80 + step * 5))));
  }
  for (let lat = -80; lat <= 80; lat += 10) {
    parts.push(line(Array.from({length: 73}, (_, step) => project(-180 + step * 5, lat))));
  }
  return parts.join(' ');
};

type Label = {x: number; y: number; anchor: 'start' | 'middle' | 'end'; crowded: boolean};

/**
 * Where each place's label goes: right of its pin if that is free, otherwise left, above or below,
 * so labels of nearby places do not cover each other. Widths are estimated from the text length.
 */
const placeLabels = (points: Point[], texts: string[], width: number, size: number): Label[] => {
  const taken: [number, number, number, number][] = points.map(([x, y]) => [x - 16, y - 16, x + 16, y + 16]);
  const overlaps = (box: [number, number, number, number]) =>
    box[0] < 30 || box[2] > width - 30 || taken.some(([x1, y1, x2, y2]) => box[0] < x2 && box[2] > x1 && box[1] < y2 && box[3] > y1);
  return points.map(([x, y], index) => {
    const w = texts[index].length * size * 0.56;
    const options: [Label, [number, number, number, number]][] = [
      [{x: x + 22, y: y + 12, anchor: 'start', crowded: false}, [x + 22, y - size * 0.7, x + 22 + w, y + size * 0.4]],
      [{x: x - 22, y: y + 12, anchor: 'end', crowded: false}, [x - 22 - w, y - size * 0.7, x - 22, y + size * 0.4]],
      [{x, y: y - 26, anchor: 'middle', crowded: false}, [x - w / 2, y - 26 - size * 0.9, x + w / 2, y - 22]],
      [{x, y: y + 26 + size * 0.8, anchor: 'middle', crowded: false}, [x - w / 2, y + 24, x + w / 2, y + 30 + size]],
    ];
    const free = options.find(([, candidate]) => !overlaps(candidate));
    if (!free) {
      // No free spot: the label shows only while the narration is on this place.
      return {...options[0][0], crowded: true};
    }
    taken.push(free[1]);
    return free[0];
  });
};

/** A gently curved line between two points, as an SVG path with its approximate length. */
const arc = ([x1, y1]: Point, [x2, y2]: Point) => {
  const length = Math.hypot(x2 - x1, y2 - y1);
  const bend = Math.min(80, length * 0.16);
  const cx = (x1 + x2) / 2 + ((y1 - y2) / (length || 1)) * bend;
  const cy = (y1 + y2) / 2 - (Math.abs(x2 - x1) / (length || 1)) * bend;
  return {d: `M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}`, length: length * 1.08 + 4};
};

/**
 * A full-frame map of one region: a latitude and longitude grid with labelled places that drop in as the
 * narration names them, an optional route that draws itself leg by leg toward each new place, and the
 * country groups as colored labels. The whole map drifts slowly closer while the scene plays.
 */
export const MapScene: React.FC<Props> = ({scene, label}) => {
  const theme = useTheme();
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const project = fitted(scene.visual.region, width, height);
  const {areas, places, route} = scene.visual;
  const areaStates = areas.map((area, index) => {
    const matches = (line: {highlightId?: string}) => line.highlightId === area.id;
    const start = revealFrame(scene.lines, scene.from, matches, 8 + index * 12);
    return {shown: ease(frame, start, 22), level: highlightLevel(scene.lines, scene.from, frame, matches)};
  });
  const placeStates = places.map((place, index) => {
    const matches = (line: {highlightId?: string}) => line.highlightId === place.id;
    const start = revealFrame(scene.lines, scene.from, matches, 12 + index * 10);
    return {start, shown: appear(frame, start, fps), level: highlightLevel(scene.lines, scene.from, frame, matches),
      at: project(place.lon, place.lat)};
  });
  const labels = placeLabels(placeStates.map((state) => state.at), places.map((place) => place.label), width, 36);
  const zoom = interpolate(frame, [0, scene.durationInFrames], [1, 1.06]);
  const scrim = `${theme.backdrop[0]}e6`;
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{transform: `scale(${zoom})`, transformOrigin: '50% 58%'}}>
        <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
          <rect width={width} height={height} fill={theme.water} />
          <path d={graticule(project)} fill="none" stroke={theme.line} strokeWidth={1.5} opacity={0.8} />
          {route ? placeStates.slice(1).map((state, index) => {
            const leg = arc(placeStates[index].at, state.at);
            const drawn = ease(frame, state.start - 12, 26);
            return (
              <g key={index} fill="none" strokeLinecap="round">
                <path d={leg.d} stroke={theme.accent} strokeWidth={14} opacity={0.18 * drawn}
                  strokeDasharray={leg.length} strokeDashoffset={leg.length * (1 - drawn)} />
                <path d={leg.d} stroke={theme.accent} strokeWidth={5}
                  strokeDasharray={leg.length} strokeDashoffset={leg.length * (1 - drawn)} />
              </g>
            );
          }) : null}
          {places.map((place, index) => {
            const {shown, level, at: [x, y], start} = placeStates[index];
            const ripple = ((frame - start) % 36) / 36;
            const spot = labels[index];
            return (
              <g key={place.id} opacity={shown}>
                {level > 0 ? (
                  <circle cx={x} cy={y} r={14 + 30 * ripple} fill="none" stroke={theme.accent} strokeWidth={4}
                    opacity={level * (1 - ripple)} />
                ) : null}
                <circle cx={x} cy={y} r={(10 + 4 * level) * (0.4 + 0.6 * shown)} fill={theme.accent}
                  stroke={theme.backdrop[1]} strokeWidth={4} />
                <text x={spot.x} y={spot.y} textAnchor={spot.anchor} fill={theme.ink} opacity={spot.crowded ? level : 1}
                  fontSize={34 + 6 * level} fontWeight={level > 0.5 ? 800 : 650} stroke={theme.backdrop[1]}
                  strokeWidth={8} strokeLinejoin="round" paintOrder="stroke">
                  {place.label}
                </text>
              </g>
            );
          })}
        </svg>
      </AbsoluteFill>
      <AbsoluteFill style={{background: `linear-gradient(180deg, ${scrim} 0%, ${scrim} 14%, transparent 34%)`}} />
      <div style={{position: 'absolute', left: 140, top: 96, right: 140}}>
        <Kicker text={label} />
        <h1 style={{margin: '22px 0 0', fontSize: 76, lineHeight: 1.12, fontWeight: 750, maxWidth: 1560}}>
          <RisingWords text={scene.visual.title} start={2} />
        </h1>
      {areas.length > 0 ? (
        <div style={{marginTop: places.length ? 22 : 56, display: 'flex', flexWrap: 'wrap',
          flexDirection: places.length ? 'row' : 'column', gap: places.length ? 24 : 30}}>
          {areas.map((area, index) => {
            const {shown, level} = areaStates[index];
            return (
              <div key={area.id} style={{display: 'flex', flexDirection: 'column', gap: 10, opacity: shown,
                transform: `translateY(${(1 - shown) * 20}px)`}}>
                <div style={{display: 'flex', alignItems: 'center', gap: 16, fontSize: places.length ? 30 : 44,
                  fontWeight: 750, color: level > 0.5 ? theme.areas[index] : theme.ink}}>
                  <span style={{width: 26, height: 26, borderRadius: 7, background: theme.areas[index],
                    transform: `scale(${1 + 0.3 * level})`}} />
                  {area.label}
                </div>
                {places.length ? null : (
                  <div style={{fontSize: 28, lineHeight: 1.35, color: theme.muted, maxWidth: 1500, paddingLeft: 42}}>
                    {area.countries.join(' · ')}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ) : null}
      </div>
    </AbsoluteFill>
  );
};
