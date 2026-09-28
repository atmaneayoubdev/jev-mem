import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { fmtPct } from '../format';
import { BenchmarkResults } from '../views/BenchmarkView';
import { benchmarkRuns } from './fixtures';

describe('BenchmarkResults (fixtures/benchmark_runs.json)', () => {
  it('highlights test-main and shows only the numbers the API returned', () => {
    const { container } = render(<BenchmarkResults runs={benchmarkRuns} />);
    const testMain = benchmarkRuns.find((r) => r.run_id === 'test-main');
    const acc = testMain?.answer_accuracy ?? {};

    expect(screen.getByRole('heading', { name: /test-main\s*Highlighted run/ })).toBeInTheDocument();
    const bars = [...container.querySelectorAll('.bench-bar-row')];
    expect(bars).toHaveLength(Object.keys(acc).length);
    // Highest first, formatted straight from the API value.
    const top = Object.entries(acc).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0];
    expect(bars[0]?.querySelector('.bench-sys')?.textContent).toBe(top?.[0]);
    expect(bars[0]?.querySelector('.bench-val')?.textContent).toBe(fmtPct(top?.[1] ?? 0));

    // The matrix marks the featured column and uses a dash where a run lacks a system.
    const table = screen.getByRole('table');
    const featured = within(table).getByRole('columnheader', { name: 'test-main' });
    expect(featured).toHaveClass('is-featured');
    expect(within(table).getAllByText('–').length).toBeGreaterThan(0);
    const cells = [...table.querySelectorAll('tbody td')].filter((td) => td.textContent !== '–');
    const expected = benchmarkRuns.reduce((n, r) => n + Object.keys(r.answer_accuracy ?? {}).length, 0);
    expect(cells).toHaveLength(expected);
  });
});
