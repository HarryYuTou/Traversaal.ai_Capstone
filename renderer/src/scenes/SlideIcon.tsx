import React from 'react';
import {icons} from 'lucide-react';

type IconNode = [string, Record<string, string | number>][];

const pascal = (name: string) => name.split('-').map((part) => part[0].toUpperCase() + part.slice(1)).join('');

// lucide-react keeps each icon's shapes inside its component; this reads them back so the strokes can be
// drawn with pathLength. Falls back to the plain icon if a lucide-react update hides them.
const shapesOf = (component: unknown): IconNode | null => {
  const render = (component as {render?: (props: object, ref: null) => {props?: {icon?: {node?: unknown}}}}).render;
  const node = typeof render === 'function' ? render({}, null)?.props?.icon?.node : undefined;
  return Array.isArray(node) ? (node as IconNode) : null;
};

/**
 * A Lucide icon by its kebab-case name from schemas/icons.json; nothing when the name is missing or unknown.
 * With `draw` below 1 the strokes are only partly drawn, so an icon sketches itself in as it appears.
 */
export const SlideIcon: React.FC<{name?: string; size: number; color: string; draw?: number}> = (
  {name, size, color, draw = 1}) => {
  const Icon = name ? icons[pascal(name) as keyof typeof icons] : undefined;
  if (!Icon) {
    return null;
  }
  const shapes = draw < 1 ? shapesOf(Icon) : null;
  if (!shapes) {
    return <Icon size={size} color={color} strokeWidth={1.75} style={{flex: '0 0 auto'}} />;
  }
  const progress = Math.max(0, draw);
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={1.75}
      strokeLinecap="round" strokeLinejoin="round" style={{flex: '0 0 auto', opacity: Math.min(1, progress * 4)}}>
      {shapes.map(([tag, attributes], index) => React.createElement(tag, {
        ...attributes, key: index, pathLength: 1, strokeDasharray: 1, strokeDashoffset: 1 - progress,
      }))}
    </svg>
  );
};
