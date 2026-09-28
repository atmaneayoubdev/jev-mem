import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CompareColumns } from '../views/CompareColumns';
import { compare, config } from './fixtures';

const AWS = 'My preferred cloud provider is AWS; everything we run is on AWS.';
const VENDOR = 'Pasted from a vendor email';
const AZURE = 'We finished the migration: everything runs on Azure now, and Azure is our preferred cloud going forward.';

function rowIn(section: HTMLElement, text: string): HTMLElement {
  const row = [...section.querySelectorAll<HTMLElement>('.cand')].find((li) => li.textContent?.includes(text));
  if (!row) throw new Error(`row not found: ${text}`);
  return row;
}

describe('CompareColumns (fixtures/compare.json)', () => {
  it('renders one column per mode in config order, with judge latency and call count', () => {
    render(<CompareColumns results={compare} order={config.modes} policy={config.policy} />);
    const cols = screen.getAllByRole('region').filter((r) => r.classList.contains('cmp-col'));
    expect(cols.map((c) => c.querySelector('h3')?.textContent)).toEqual([
      'BM25',
      'Embedding',
      'Hybrid(judged by Jev)',
    ]);

    const hybrid = screen.getByRole('region', { name: /^Hybrid/ });
    expect(within(hybrid).getByText(/14 calls, 1,737 ms/)).toBeInTheDocument();
    expect(within(hybrid).getByText('1 of 13')).toBeInTheDocument();
    const embedding = screen.getByRole('region', { name: /^Embedding/ });
    expect(within(embedding).getByText('none')).toBeInTheDocument();
    expect(within(embedding).getByText('10 of 10')).toBeInTheDocument();
  });

  it('distinguishes injected USE from withheld STALE / DROP rows, with reasons', () => {
    render(<CompareColumns results={compare} order={config.modes} policy={config.policy} />);
    const hybrid = screen.getByRole('region', { name: /^Hybrid/ });

    const azure = rowIn(hybrid, AZURE);
    expect(azure).toHaveClass('is-injected');
    expect(within(azure).getByText('Use')).toBeInTheDocument();

    const aws = rowIn(hybrid, AWS);
    expect(aws).toHaveClass('is-withheld');
    expect(within(aws).getByText('Stale')).toBeInTheDocument();
    expect(within(aws).getByText('superseded and query is about the present')).toBeInTheDocument();
    expect(within(aws).getByRole('meter', { name: 'Relevance 0.95, threshold 0.50' })).toBeInTheDocument();

    const vendor = rowIn(hybrid, VENDOR);
    expect(vendor).toHaveClass('is-withheld');
    expect(within(vendor).getByText('Drop')).toBeInTheDocument();
    expect(within(vendor).getByText('instruction-like content (possible injection)')).toBeInTheDocument();
  });

  it('highlights what the similarity column injected but JevMem withheld', () => {
    render(<CompareColumns results={compare} order={config.modes} policy={config.policy} />);

    // Summary: the superseded AWS preference and the vendor email lead the list.
    const summary = screen.getByRole('region', { name: 'Where the modes disagree' });
    expect(within(summary).getByText('Embedding injected 10 memories. Hybrid injected 1 and withheld 9 of Embedding’s.')).toBeInTheDocument();
    const list = within(summary).getByRole('heading', { name: 'Injected by Embedding, withheld by Hybrid' })
      .nextElementSibling as HTMLElement;
    const items = [...list.querySelectorAll('.diff-item')];
    expect(items).toHaveLength(9);
    expect(items[0]?.textContent).toContain(AWS);
    expect(items[0]?.textContent).toContain('Stale');
    expect(items[0]?.textContent).toContain('(Embedding rank 1)');
    expect(items.some((i) => i.textContent?.includes(VENDOR) && i.textContent.includes('Drop'))).toBe(true);

    // Row flags in both columns.
    const embedding = screen.getByRole('region', { name: /^Embedding/ });
    const awsEmb = rowIn(embedding, AWS);
    expect(awsEmb).toHaveClass('is-contested');
    expect(within(awsEmb).getByText(/Withheld by Hybrid/)).toBeInTheDocument();
    expect(within(awsEmb).getByText('Stored as superseded')).toBeInTheDocument();
    expect(rowIn(embedding, AZURE)).not.toHaveClass('is-contested');

    const hybrid = screen.getByRole('region', { name: /^Hybrid/ });
    expect(within(rowIn(hybrid, VENDOR)).getByText('Injected by Embedding')).toBeInTheDocument();
  });
});
