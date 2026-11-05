// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ErrorBoundary } from './ErrorBoundary';

let explode = true;
function Bomb() {
  if (explode) throw new Error('boom in render');
  return <p>recovered</p>;
}

afterEach(() => {
  cleanup();
  explode = true;
  vi.restoreAllMocks();
});

describe('ErrorBoundary', () => {
  it('shows a message for the broken panel and leaves its siblings alone', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    render(
      <div>
        <ErrorBoundary name="Lines">
          <Bomb />
        </ErrorBoundary>
        <p>sibling panel</p>
      </div>,
    );
    expect(screen.getByRole('alert').textContent).toContain('“Lines” panel hit a problem');
    expect(screen.getByRole('alert').textContent).toContain('boom in render');
    expect(screen.getByText('sibling panel')).toBeTruthy();
  });

  it('recovers when the problem is gone and Try again is pressed', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    render(
      <ErrorBoundary name="Lines">
        <Bomb />
      </ErrorBoundary>,
    );
    explode = false;
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(screen.getByText('recovered')).toBeTruthy();
  });

  it('renders children untouched when nothing fails', () => {
    explode = false;
    render(
      <ErrorBoundary name="Lines">
        <Bomb />
      </ErrorBoundary>,
    );
    expect(screen.getByText('recovered')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
