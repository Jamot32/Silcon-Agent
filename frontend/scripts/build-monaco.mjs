import { build } from 'esbuild';
import { createRequire } from 'node:module';
import { copyFile, mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';

const require = createRequire(import.meta.url);
const root = resolve(import.meta.dirname, '..');
const output = resolve(root, 'public/monaco');
await mkdir(output, { recursive: true });
const shared = {
  bundle: true,
  minify: true,
  target: ['es2022'],
  platform: 'browser',
  format: 'iife',
  absWorkingDir: root,
  legalComments: 'external',
  loader: { '.ttf': 'file' },
  assetNames: '[name]-[hash]',
  plugins: [{
    name: 'patched-dompurify',
    setup(builder) {
      // Monaco ships a vendored copy. Resolve that import to our pinned, fixed npm dependency.
      builder.onResolve({ filter: /(?:^|\/)dompurify\/dompurify\.js$/ }, () => ({
        path: resolve(dirname(require.resolve('dompurify')), 'purify.es.mjs'),
      }));
    },
  }],
};
await build({
  ...shared,
  stdin: {
    contents: `import * as monaco from 'monaco-editor/editor/editor.api.js';
import 'monaco-editor/editor/browser/widget/diffEditor/diffEditor.contribution.js';
import 'monaco-editor/editor/contrib/bracketMatching/browser/bracketMatching.js';
import 'monaco-editor/languages/definitions/python/register.js';
import 'monaco-editor/languages/definitions/systemverilog/register.js';
window.SiliconMonaco = monaco;`,
    resolveDir: root,
    sourcefile: 'silicon-monaco.js',
    loader: 'js',
  },
  outfile: resolve(output, 'editor.js'),
});
await build({
  ...shared,
  entryPoints: ['node_modules/monaco-editor/esm/vs/editor/editor.worker.js'],
  outfile: resolve(output, 'editor.worker.js'),
});
await Promise.all([
  copyFile(resolve(root, 'node_modules/monaco-editor/LICENSE'), resolve(output, 'LICENSE.monaco.txt')),
  copyFile(resolve(root, 'node_modules/monaco-editor/ThirdPartyNotices.txt'), resolve(output, 'THIRD-PARTY-NOTICES.txt')),
  copyFile(resolve(root, 'node_modules/dompurify/LICENSE'), resolve(output, 'LICENSE.dompurify.txt')),
]);
console.log('Built local Monaco editor, stylesheet, and worker (DOMPurify 3.4.17).');
