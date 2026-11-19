import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import ts from 'typescript';

const load = async (file) => {
  const source = await readFile(new URL(file, import.meta.url), 'utf8');
  let {outputText} = ts.transpileModule(source, {compilerOptions: {
    module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022,
  }});
  for (const match of [...outputText.matchAll(/from (['"])([^'"]+)\1/g)]) {
    outputText = outputText.replace(match[0], `from '${import.meta.resolve(match[2])}'`);
  }
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
};
const json = async (path) => JSON.parse(await readFile(new URL(path, import.meta.url), 'utf8'));

const {buildBasemap} = await load('../src/scenes/basemap.ts');
const world = await json('../node_modules/world-atlas/countries-50m.json');
const countries = await json('../../schemas/map-countries.json');
const regions = await json('../../schemas/map-regions.json');
const frame = {width: 1920, height: 1080};

// A plain equirectangular fit of a region's bounds into the frame, standing in for MapScene's projections.
const fit = ({west, south, east, north}) => (lon, lat) =>
  [150 + ((lon - west) / (east - west)) * 1620, 290 + ((north - lat) / (north - south)) * 560];
const numbers = (path) => (path.match(/-?\d+(\.\d+)?/g) ?? []).map(Number);

test('the shared country list names exactly the countries in the map data', () => {
  const names = new Set(world.objects.countries.geometries.map((geometry) => geometry.properties.name));
  assert.deepEqual([...countries.names].sort(), [...names].sort());
  for (const name of Object.values(countries.aliases)) assert.ok(names.has(name), name);
});

test('every region gets land, borders and finite coordinates', () => {
  for (const [region, bounds] of Object.entries(regions)) {
    const map = buildBasemap(world, fit(bounds), frame);
    assert.match(map.land, /^M[^Z]+Z/, region);
    assert.match(map.borders, /^M/, region);
    for (const value of [...numbers(map.land), ...numbers(map.borders)]) assert.ok(Number.isFinite(value), region);
  }
});

test('countries are shaded by their map names, and an unknown name draws nothing', () => {
  const map = buildBasemap(world, fit(regions['south-asia']), frame);
  const india = numbers(map.country('India'));
  assert.ok(india.length > 200);
  const xs = india.filter((_, index) => index % 2 === 0);
  const ys = india.filter((_, index) => index % 2 === 1);
  // India lies inside the South Asia frame, away from its edges.
  assert.ok(Math.min(...xs) > 150 && Math.max(...xs) < 1770 && Math.min(...ys) > 290 && Math.max(...ys) < 850);
  assert.equal(map.country('India'), map.country('India'));
  assert.equal(map.country('Soviet Union'), '');
});

test('pieces far outside the frame are left out', () => {
  const nearby = buildBasemap(world, fit(regions['mediterranean']), frame);
  const everything = buildBasemap(world, fit(regions['mediterranean']), {width: 1e6, height: 1e6});
  assert.ok(nearby.land.length < everything.land.length / 2);
  assert.equal(nearby.country('Australia'), '');
});
