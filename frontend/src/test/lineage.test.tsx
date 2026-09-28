import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { LineageTimeline } from '../views/LineageTimeline';
import { lineage, memories } from './fixtures';

const byId = new Map(memories.map((m) => [m.id, m]));

function nodes(container: HTMLElement): HTMLElement[] {
  return [...container.querySelectorAll<HTMLElement>('.lin-node')];
}

describe('LineageTimeline (fixtures/memory_lineage.json)', () => {
  it('draws the supersession chain in date order with each node’s date, content and state', () => {
    const { container } = render(<LineageTimeline lineage={lineage} memoriesById={byId} />);
    const list = nodes(container);
    expect(list.map((n) => n.querySelector('time')?.textContent)).toEqual([
      '6 Jan 2026',
      '21 Jan 2026',
      '5 Aug 2026',
      '1 Sep 2026',
      '14 Sep 2026',
    ]);
    expect(list.map((n) => n.querySelector('.lin-state')?.textContent)).toEqual([
      'Superseded',
      'Superseded',
      'Superseded',
      'Superseded',
      'Active',
    ]);
    const [first, , , vendor, last] = list as [HTMLElement, HTMLElement, HTMLElement, HTMLElement, HTMLElement];
    expect(first).toHaveClass('is-focal');
    expect(within(first).getByText('Selected')).toBeInTheDocument();
    expect(within(first).getByText(lineage.memory.content)).toBeInTheDocument();
    expect(within(vendor).getByText('Instruction-like')).toBeInTheDocument();
    expect(last.textContent).toContain('Azure is our preferred cloud going forward');
  });

  it('labels edges with the link type and the judge’s probability', () => {
    const { container } = render(<LineageTimeline lineage={lineage} memoriesById={byId} />);
    const [, priya, migrating, , azure] = nodes(container) as HTMLElement[];

    const azureEdge = within(azure as HTMLElement).getByRole('listitem');
    expect(within(azureEdge).getByText('supersedes')).toBeInTheDocument();
    expect(within(azureEdge).getByText('p 1.00')).toBeInTheDocument();
    expect(azureEdge.textContent).toContain('6 Jan: My preferred cloud provider is AWS');

    const migratingEdge = within(migrating as HTMLElement).getByRole('listitem');
    expect(within(migratingEdge).getByText('supersedes')).toBeInTheDocument();
    expect(within(migratingEdge).getByText('p 0.66')).toBeInTheDocument();

    const priyaEdge = within(priya as HTMLElement).getByRole('listitem');
    expect(within(priyaEdge).getByText('uncertain relation to')).toBeInTheDocument();
    expect(within(priyaEdge).getByText('unrelated 0.52, refines 0.44')).toBeInTheDocument();
  });

  it('works from the lineage payload alone (states from stored status)', () => {
    const { container } = render(<LineageTimeline lineage={lineage} />);
    expect(nodes(container)).toHaveLength(5);
    expect(screen.getAllByText('supersedes')).toHaveLength(2);
    expect(nodes(container).at(-1)?.querySelector('.lin-state')?.textContent).toBe('Active');
  });
});
