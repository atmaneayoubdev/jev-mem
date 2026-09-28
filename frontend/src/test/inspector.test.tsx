import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { traceFromChat } from '../recall';
import { Inspector } from '../views/Inspector';
import { chat, compare, config } from './fixtures';

describe('Inspector (fixtures/chat.json)', () => {
  const debug = chat.memory_debug;
  if (!debug) throw new Error('fixture has no memory_debug');

  it('splits candidates into injected and withheld using selected_ids', () => {
    const { container } = render(<Inspector trace={traceFromChat(chat)} policy={config.policy} />);
    expect(screen.getByText(debug.query)).toBeInTheDocument();

    const injected = container.querySelectorAll('.cand.is-injected');
    const withheld = container.querySelectorAll('.cand.is-withheld');
    expect(injected).toHaveLength(debug.selected_ids.length); // 3
    expect(withheld).toHaveLength(debug.rejected_ids.length); // 10
    expect(screen.getByRole('heading', { name: /Injected into context\s*3/ })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Withheld\s*10/ })).toBeInTheDocument();

    // Injected rows are the three cloud memories, in retriever rank order.
    const injectedText = [...injected].map((li) => li.querySelector('.cand-content')?.textContent);
    expect(injectedText).toEqual([
      'We finished the migration: everything runs on Azure now, and Azure is our preferred cloud going forward.',
      'Our company has started moving some services from AWS to Azure.',
      'My preferred cloud provider is AWS; everything we run is on AWS.',
    ]);
  });

  it('shows each judgment: bars with numbers, decision badge, reason, validity and annotations', () => {
    const { container } = render(<Inspector trace={traceFromChat(chat)} policy={config.policy} />);

    // Relevance and utility meters carry value and threshold.
    expect(screen.getByRole('meter', { name: 'Relevance 0.82, threshold 0.50' })).toBeInTheDocument();
    expect(screen.getByRole('meter', { name: 'Utility 0.56, threshold 0.30' })).toBeInTheDocument();

    // The injected vendor email is dropped with the policy's reason; badge = icon + label.
    const vendor = [...container.querySelectorAll('.cand')].find((li) =>
      li.textContent?.includes('Pasted from a vendor email'),
    ) as HTMLElement;
    expect(vendor).toHaveClass('is-withheld');
    expect(within(vendor).getByText('Drop')).toBeInTheDocument();
    expect(within(vendor).getByText('instruction-like content (possible injection)')).toBeInTheDocument();
    expect(vendor.querySelector('.badge svg')).not.toBeNull();

    // Superseded AWS memory is used as history for this historical query.
    const aws = [...container.querySelectorAll('.cand')].find((li) =>
      li.textContent?.includes('My preferred cloud provider is AWS'),
    ) as HTMLElement;
    expect(within(aws).getByText('Use')).toBeInTheDocument();
    expect(within(aws).getByText('historical (superseded)')).toBeInTheDocument();
    expect(within(aws).getByText('possibly outdated')).toBeInTheDocument();
    expect(within(aws).getByText('Superseded')).toBeInTheDocument();

    // Source tags.
    expect(within(aws).getByText('bm25')).toBeInTheDocument();
    expect(within(aws).getByText('embedding')).toBeInTheDocument();

    // The uncertain Priya memory.
    expect(screen.getAllByText('Uncertain').length).toBeGreaterThan(0);
  });

  it('reports intent, judge usage, latency, tokens and the exact context text', () => {
    render(<Inspector trace={traceFromChat(chat)} policy={config.policy} />);
    expect(screen.getByText('Historical')).toBeInTheDocument();
    expect(screen.getByText('Historical 98%')).toBeInTheDocument();
    expect(screen.getByText(/14 calls, 1,316 ms/)).toBeInTheDocument();
    expect(screen.getByText('4.3 ms')).toBeInTheDocument();
    expect(screen.getByText('1,316 ms')).toBeInTheDocument();
    expect(screen.getByText('483 ms')).toBeInTheDocument();
    expect(screen.getAllByText('99 tokens')).toHaveLength(2); // context fact and summary

    const summary = screen.getByText('Context sent to the model');
    const details = summary.closest('details') as HTMLElement;
    expect(details.querySelector('pre')?.textContent).toBe(debug.context_text);
    expect(screen.getByText('No new memories in this turn.')).toBeInTheDocument();
  });

  it('explains when the server hides debug payloads', () => {
    render(<Inspector trace={{ ...traceFromChat(chat), debug: null }} policy={config.policy} />);
    expect(screen.getByText('Debug output is disabled on this server')).toBeInTheDocument();
    expect(screen.getByText('483 ms')).toBeInTheDocument();
  });

  it('shows ranked candidates and what was injected for a baseline mode', () => {
    const embedding = compare.embedding;
    if (!embedding) throw new Error('fixture has no embedding result');
    const { container } = render(
      <Inspector trace={{ debug: embedding, latency: null, extracted: null, extractionError: null }} />,
    );
    expect(screen.getByRole('heading', { name: /Ranked candidates\s*10/ })).toBeInTheDocument();
    expect(container.querySelectorAll('.cand.is-injected')).toHaveLength(10);
    expect(screen.getByText('Not used in Embedding mode')).toBeInTheDocument();
    expect(screen.getAllByText('Stored as superseded').length).toBe(4);
  });
});
