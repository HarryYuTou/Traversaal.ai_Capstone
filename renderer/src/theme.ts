import React from 'react';

// Two looks: `light` follows the browser preview (capstone_script/preview.html); `night` is a darker,
// documentary look. A render picks one with `--theme`; components read it with useTheme().
export type ThemeName = 'light' | 'night';

export type Theme = {
  name: ThemeName;
  bg: string;
  // The moving backdrop: a diagonal gradient, three soft lights drifting over it and a faint dot grid.
  backdrop: [string, string];
  glows: [string, string, string];
  dots: string;
  card: string;
  ink: string;
  muted: string;
  accent: string;
  accentSoft: string;
  line: string;
  caption: string;
  // Map areas in order (also the second and third colors anywhere a scene needs more than one).
  areas: [string, string, string];
  land: string;
  border: string;
  water: string;
  shadow: (alpha: number) => string;
  font: string;
  serif: string;
};

const font = 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';
const serif = 'Georgia, "Times New Roman", Times, serif';

export const themes: Record<ThemeName, Theme> = {
  light: {
    name: 'light',
    bg: '#f3f4f7',
    backdrop: ['#f7f8fb', '#e8ebf2'],
    glows: ['rgba(47, 111, 222, 0.11)', 'rgba(240, 150, 60, 0.08)', 'rgba(46, 158, 122, 0.08)'],
    dots: 'rgba(29, 36, 51, 0.07)',
    card: '#ffffff',
    ink: '#1d2433',
    muted: '#5b6475',
    accent: '#2f6fde',
    accentSoft: '#e4edfc',
    line: '#d6dae2',
    caption: 'rgba(29, 36, 51, 0.88)',
    areas: ['#2f6fde', '#d6574c', '#2e9e7a'],
    land: '#d9dee8',
    border: '#f7f8fb',
    water: 'rgba(206, 220, 242, 0.45)',
    shadow: (alpha) => `rgba(29, 36, 51, ${alpha})`,
    font,
    serif,
  },
  night: {
    name: 'night',
    bg: '#0e1524',
    backdrop: ['#132039', '#090e19'],
    glows: ['rgba(80, 130, 255, 0.17)', 'rgba(242, 184, 75, 0.11)', 'rgba(64, 196, 164, 0.10)'],
    dots: 'rgba(255, 255, 255, 0.055)',
    card: '#17223a',
    ink: '#f1f4fa',
    muted: '#a1abc0',
    accent: '#f2b84b',
    accentSoft: '#25324f',
    line: '#2b3a59',
    caption: 'rgba(5, 9, 17, 0.84)',
    areas: ['#f2b84b', '#e2685c', '#4cc4a0'],
    land: '#22314f',
    border: '#0f1729',
    water: 'rgba(6, 10, 20, 0.45)',
    shadow: (alpha) => `rgba(0, 0, 0, ${Math.min(1, alpha * 3)})`,
    font,
    serif,
  },
};

export const ThemeContext = React.createContext<Theme>(themes.light);

export const useTheme = () => React.useContext(ThemeContext);

// Frame durations for in-shot fades and item reveals; scene intervals never overlap.
export const motion = {enter: 16, exit: 14, reveal: 10};
