import {feature, mesh} from 'topojson-client';
import type {GeometryCollection, Topology} from 'topojson-specification';

/**
 * The base map under a map scene: land, coastlines, country borders and country shapes, as SVG path data
 * projected with the scene's own projection. The data is Natural Earth's 1:50m Admin 0 countries
 * (public domain), packaged as TopoJSON by world-atlas. Everything here is computed once per scene.
 */
export type Point = [number, number];
export type Project = (lon: number, lat: number) => Point;
type Frame = {width: number; height: number};
type Ring = number[][];
type Wobble = (point: Point) => Point;

// Pieces wholly this far outside the frame are left out; the scene's slow zoom stays well inside it.
const MARGIN = 120;
// A point closer than this (in pixels) to the last one kept adds nothing visible at 1080p.
const TOLERANCE = 0.8;
// Islands smaller than this many pixels across are dropped.
const SPECK = 1.5;

/**
 * The sketch look's hand-drawn wobble: a smooth offset of a few pixels that depends only on where a point is,
 * so land, borders and shaded countries move together, and is computed once instead of filtering every frame.
 * Different seeds give different strokes, for lines drawn twice.
 */
export const wobble = (seed: number, amplitude = 2.6): Wobble => {
  const [a, b, c] = [0.9 + 0.37 * seed, 2.1 + 0.53 * seed, 4.3 + 0.71 * seed];
  return ([x, y]) => [
    x + amplitude * (0.6 * Math.sin(0.071 * x + 0.043 * y + a) + 0.4 * Math.sin(0.137 * y - 0.029 * x + b)),
    y + amplitude * (0.6 * Math.sin(0.067 * y - 0.051 * x + c) + 0.4 * Math.sin(0.149 * x + 0.031 * y + a + b)),
  ];
};

/** One ring or line as SVG path data, or "" when it is off-frame or too small to see. */
const piece = (ring: Ring, project: Project, {width, height}: Frame, closed: boolean, shift?: Wobble): string => {
  const kept: Point[] = [];
  let [minX, minY, maxX, maxY] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const [lon, lat] of ring) {
    const [x, y] = shift ? shift(project(lon, lat)) : project(lon, lat);
    minX = Math.min(minX, x); maxX = Math.max(maxX, x);
    minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    const last = kept[kept.length - 1];
    if (!last || Math.abs(x - last[0]) + Math.abs(y - last[1]) >= TOLERANCE) kept.push([x, y]);
  }
  if (maxX < -MARGIN || minX > width + MARGIN || maxY < -MARGIN || minY > height + MARGIN) return '';
  if (closed && (maxX - minX < SPECK && maxY - minY < SPECK)) return '';
  if (kept.length < 2) return '';
  const d = kept.map(([x, y], index) => `${index ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join('');
  return closed ? `${d}Z` : d;
};

type Shape = {type: string; coordinates: unknown};

/** Every ring of a (multi)polygon, or every line of a (multi)line string. */
const rings = (geometry: Shape | null): Ring[] => {
  if (!geometry) return [];
  switch (geometry.type) {
    case 'Polygon': case 'MultiLineString': return geometry.coordinates as Ring[];
    case 'MultiPolygon': return (geometry.coordinates as Ring[][]).flat();
    case 'LineString': return [geometry.coordinates as Ring];
    default: return [];
  }
};

const path = (geometry: Shape | null, project: Project, frame: Frame, closed: boolean, shift?: Wobble) =>
  rings(geometry).map((ring) => piece(ring, project, frame, closed, shift)).filter(Boolean).join('');

export type Basemap = {
  /** Land, filled; its outline is the coastline. */
  land: string;
  /** Borders between two countries, without coastlines. */
  borders: string;
  /** Each country's shape by its Natural Earth name, for shading map areas. */
  country: (name: string) => string;
};

/** `shift`, such as a `wobble`, moves every projected point; without it the lines are exact. */
export const buildBasemap = (topology: Topology, project: Project, frame: Frame, shift?: Wobble): Basemap => {
  const countries = topology.objects.countries as GeometryCollection<{name: string}>;
  const land = feature(topology, topology.objects.land as GeometryCollection);
  const shapes = new Map<string, Shape[]>();
  for (const country of feature(topology, countries).features) {
    const name = country.properties?.name;
    if (name) shapes.set(name, [...(shapes.get(name) ?? []), country.geometry as Shape]);
  }
  const cache = new Map<string, string>();
  return {
    land: land.features.map((item) => path(item.geometry as Shape, project, frame, true, shift)).join(''),
    borders: path(mesh(topology, countries, (a, b) => a !== b) as Shape, project, frame, false, shift),
    country: (name) => {
      if (!cache.has(name)) {
        cache.set(name, (shapes.get(name) ?? []).map((shape) => path(shape, project, frame, true, shift)).join(''));
      }
      return cache.get(name)!;
    },
  };
};
