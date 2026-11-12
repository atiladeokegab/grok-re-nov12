import { test } from 'node:test';
import assert from 'node:assert/strict';
import { clientRows } from './clients.js';

test('known MCP clients come first, in a fixed order, with their counts', () => {
  assert.deepEqual(clientRows({ mcp: { other: 1, cursor: 3, grok_bot: 7 } }), [['Cursor', 3], ['Other MCP clients', 1]]);
});

test('missing or malformed counts read as zero, and new clients are still shown', () => {
  assert.deepEqual(clientRows({}), [['Cursor', 0], ['Other MCP clients', 0]]);
  assert.deepEqual(clientRows({ mcp: { grok_bot: 'x', claude_code: 2 } }).slice(-1), [['claude code', 2]]);
  assert.deepEqual(clientRows({ mcp: [] })[0], ['Cursor', 0]);
});
