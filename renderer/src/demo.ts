import type {Timeline} from './types';

// A two-scene timeline without audio, so Remotion Studio opens with something to show.
export const demo: Timeline = {
  schemaVersion: '1',
  projectId: 'demo',
  title: 'What happens after you enter a web address?',
  fps: 30,
  width: 1920,
  height: 1080,
  durationInFrames: 465,
  titleFrames: 60,
  audio: {path: '', sampleRate: 48000, channels: 1},
  chapters: [],
  scenes: [
    {
      id: 'scene-01', chapterId: null, template: 'concept', from: 60, durationInFrames: 195,
      visual: {title: 'A page is a conversation', statement: 'Your browser asks for the page and a server answers.',
        points: ['Find the server', 'Ask for the page', 'Show the result']},
      lines: [
        {id: 'scene-01-line-01', text: 'Loading a page is a short conversation.', from: 66, durationInFrames: 45},
        {id: 'scene-01-line-02', text: 'First, the browser finds the server.', from: 114, durationInFrames: 40,
          highlightPointIndex: 0},
        {id: 'scene-01-line-03', text: 'Then it asks for the page.', from: 157, durationInFrames: 40,
          highlightPointIndex: 1},
        {id: 'scene-01-line-04', text: 'Finally, it shows the result.', from: 200, durationInFrames: 49,
          highlightPointIndex: 2},
      ],
    },
    {
      id: 'scene-02', chapterId: null, template: 'flow', from: 255, durationInFrames: 210,
      visual: {title: 'Finding the server', nodes: [{id: 'browser', label: 'Browser'}, {id: 'dns', label: 'DNS server'},
        {id: 'web-server', label: 'Web server'}]},
      lines: [
        {id: 'scene-02-line-01', text: 'Your browser starts with a name.', from: 261, durationInFrames: 45,
          highlightNodeId: 'browser'},
        {id: 'scene-02-line-02', text: 'A DNS server turns the name into an address.', from: 309, durationInFrames: 60,
          highlightNodeId: 'dns'},
        {id: 'scene-02-line-03', text: 'Then the web server sends the page.', from: 372, durationInFrames: 57,
          highlightNodeId: 'web-server'},
      ],
    },
  ],
};
