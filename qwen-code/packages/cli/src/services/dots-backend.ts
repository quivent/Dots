/**
 * @license
 * Copyright 2026 Dots contributors
 * SPDX-License-Identifier: Apache-2.0
 */

import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { existsSync } from 'node:fs';
import { registerCleanup } from '../utils/cleanup.js';

export interface DotMessage {
  id: string;
  text: string;
  mine: boolean;
}

export interface DotSnapshot {
  name: string;
  profile: { is_paused?: boolean; [key: string]: unknown };
  pending: boolean;
  messages: DotMessage[];
}

function dotsRoot(): string {
  if (process.env['DOTS_ROOT']) return process.env['DOTS_ROOT'];
  let directory = dirname(fileURLToPath(import.meta.url));
  while (!existsSync(resolve(directory, 'cli/tui_bridge.py'))) {
    const parent = dirname(directory);
    if (parent === directory)
      throw new Error(
        'Cannot find the Dots backend. Set DOTS_ROOT to the Dots checkout.',
      );
    directory = parent;
  }
  return directory;
}

export class DotsBackend {
  private child?: ChildProcessWithoutNullStreams;
  private nextId = 0;
  private closed = false;
  private closing?: Promise<void>;
  private exited = false;
  private readonly pending = new Map<
    number,
    { resolve: (value: unknown) => void; reject: (error: Error) => void }
  >();

  private start(): ChildProcessWithoutNullStreams {
    if (this.closed || this.closing) throw new Error('Dots backend is closed.');
    if (this.child) return this.child;
    const root = dotsRoot();
    const child = spawn(
      process.env['DOTS_PYTHON'] || 'python3',
      process.env['DOTS_BRIDGE_BINARY'] === '1'
        ? ['--tui-bridge']
        : ['-u', '-m', 'cli.tui_bridge'],
      {
        cwd: root,
        env: {
          ...process.env,
          PYTHONPATH:
            resolve(root) +
            (process.env['PYTHONPATH']
              ? (process.platform === 'win32' ? ';' : ':') +
                process.env['PYTHONPATH']
              : ''),
        },
        stdio: ['pipe', 'pipe', 'pipe'],
      },
    );
    this.child = child;
    // Diagnostics belong to the backend protocol; never write over Ink's frame.
    child.stderr.resume();
    const fail = (error: Error) => {
      this.closed = true;
      for (const request of this.pending.values()) request.reject(error);
      this.pending.clear();
    };
    child.on('error', fail);
    child.stdin.on('error', fail);
    child.on('exit', (code) => {
      this.exited = true;
      fail(new Error(`Dots backend exited (${code ?? 'signal'}).`));
    });
    child.on('close', () => {
      this.exited = true;
    });
    const lines = createInterface({ input: child.stdout });
    lines.on('line', (line) => {
      try {
        const response = JSON.parse(line) as {
          id: number;
          result?: unknown;
          error?: { message: string };
        };
        const request = this.pending.get(response.id);
        if (!request) return;
        this.pending.delete(response.id);
        if (response.error) request.reject(new Error(response.error.message));
        else request.resolve(response.result);
      } catch {
        fail(new Error('Invalid response from Dots backend.'));
        child.stdin.end();
      }
    });
    return child;
  }

  request<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    return new Promise<T>((resolveRequest, reject) => {
      let child: ChildProcessWithoutNullStreams;
      try {
        child = this.start();
      } catch (error) {
        reject(error);
        return;
      }
      const id = ++this.nextId;
      this.pending.set(id, {
        resolve: (value) => resolveRequest(value as T),
        reject,
      });
      child.stdin.write(JSON.stringify({ id, method, params }) + '\n');
    });
  }

  async close(): Promise<void> {
    if (!this.child || this.exited) return;
    if (this.closing) return this.closing;
    const child = this.child;
    // EOF lets the current operation finish before releasing its delivery lock.
    this.closing = new Promise<void>((resolveClose) => {
      child.once('close', () => resolveClose());
      child.stdin.end();
    });
    return this.closing;
  }
}

let backend: DotsBackend | undefined;

export function getDotsBackend(): DotsBackend {
  if (!backend) {
    backend = new DotsBackend();
    registerCleanup(() => backend!.close(), { waitForCompletion: true });
  }
  return backend;
}
