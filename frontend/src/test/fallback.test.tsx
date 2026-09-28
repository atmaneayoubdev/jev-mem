import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { CompareResponse, RecallOutcome } from '../api';
import { RichText } from '../components/RichText';
import { traceFromChat } from '../recall';
import { CompareColumns } from '../views/CompareColumns';
import { Inspector } from '../views/Inspector';
import { chat, compare, config } from './fixtures';

// The provider error the live server returned when the Jev key hit its limit.
const RAW =
  'candidate judgment failed: [jev] {"error":{"message":"Key limit exceeded (monthly limit).","code":403}} (HTTP 403)';

/** The fixture's hybrid outcome as the policy's fallback would return it (judge unavailable). */
function fallbackOutcome(o: RecallOutcome): RecallOutcome {
  const k = 5;
  return {
    ...o,
    judge_used: false,
    fallback_reason: RAW,
    intent: null,
    judge_calls: 0,
    judge_ms: 0,
    judge_cost: null,
    selected_ids: o.candidates.slice(0, k).map((c) => c.id),
    judgments: o.candidates.map((c) => ({
      id: c.id,
      relevance: null,
      utility: null,
      decision: c.rank < k ? 'unjudged' : 'drop',
      reason: `fallback: ${RAW}`,
      validity: c.status === 'superseded' ? 'superseded' : 'current',
      historical: false,
      annotations: [],
    })),
  };
}

describe('judge fallback', () => {
  it('summarises the provider error once per column and keeps rows readable', () => {
    const hybrid = compare.hybrid;
    if (!hybrid) throw new Error('fixture has no hybrid result');
    const results: CompareResponse = { embedding: compare.embedding, hybrid: fallbackOutcome(hybrid) };
    render(<CompareColumns results={results} order={config.modes} policy={config.policy} />);
    const col = screen.getByRole('region', { name: /^Hybrid/ });
    expect(within(col).getByText('Not used: Judge call failed (HTTP 403)')).toBeInTheDocument();
    expect(within(col).getAllByText('Unjudged')).toHaveLength(5);
    expect(within(col).getAllByText('Judge unavailable: kept in retriever order')).toHaveLength(5);
    expect(within(col).getAllByText('Judge unavailable: below the fallback cut-off')).toHaveLength(8);
    expect(within(col).getAllByRole('meter', { name: 'Relevance not judged' }).length).toBe(13);
    // The raw text is still available, once, behind a disclosure.
    expect(within(col).getAllByText(RAW)).toHaveLength(1);
  });

  it('marks the judge as not used in the inspector', () => {
    const debug = chat.memory_debug;
    if (!debug) throw new Error('fixture has no memory_debug');
    render(<Inspector trace={{ ...traceFromChat(chat), debug: fallbackOutcome(debug) }} policy={config.policy} />);
    expect(screen.getByText('Not used')).toBeInTheDocument();
    expect(screen.getByText('Judge call failed (HTTP 403); candidates kept in retriever order')).toBeInTheDocument();
    expect(screen.getByText('Not judged (judge unavailable)')).toBeInTheDocument();
  });
});

describe('RichText', () => {
  it('renders the Markdown subset models use, without interpreting HTML', () => {
    const { container } = render(
      <RichText text={'Your cloud is **Azure**.\n\n1. **Service**: which runtime?\n2. Region\n\n<img src=x onerror=alert(1)> `code`'} />,
    );
    expect(container.querySelector('strong')?.textContent).toBe('Azure');
    expect(container.querySelectorAll('ol > li')).toHaveLength(2);
    expect(container.querySelector('code')?.textContent).toBe('code');
    expect(container.querySelector('img')).toBeNull();
    expect(container.textContent).toContain('<img src=x onerror=alert(1)>');
  });
});
