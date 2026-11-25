import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import {normalizeMath} from '../src/richText.js';
for(const input of [String.raw`\[ \text{Compression} = \frac{a}{b} \]`,String.raw`[ \text{Compression} = \frac{a}{b} ]`,String.raw`Inline \(x^2\) math.`]){
 test('renders common formula delimiters: '+input,()=>{const html=renderToStaticMarkup(React.createElement(ReactMarkdown,{remarkPlugins:[remarkMath],rehypePlugins:[rehypeKatex]},normalizeMath(input)));assert.match(html,/class="katex"/);assert.doesNotMatch(html,/katex-error/)});
}
test('preserves code and ordinary brackets',()=>{const input='```python\na = [1, 2]\nprint("\\\\[literal\\\\]")\n```\n\n[ordinary text]\n\n`\\(code\\)`';assert.equal(normalizeMath(input),input)});
