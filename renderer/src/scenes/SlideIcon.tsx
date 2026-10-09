import React from 'react';
import {icons} from 'lucide-react';

const pascal = (name: string) => name.split('-').map((part) => part[0].toUpperCase() + part.slice(1)).join('');

/** A Lucide icon by its kebab-case name from schemas/icons.json; nothing when the name is missing or unknown. */
export const SlideIcon: React.FC<{name?: string; size: number; color: string}> = ({name, size, color}) => {
  const Icon = name ? icons[pascal(name) as keyof typeof icons] : undefined;
  return Icon ? <Icon size={size} color={color} strokeWidth={1.75} style={{flex: '0 0 auto'}} /> : null;
};
