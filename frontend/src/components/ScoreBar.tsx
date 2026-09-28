interface ScoreBarProps {
  label: string;
  value: number | null;
  /** Policy threshold (drawn as a tick) and the uncertainty band just below it. */
  threshold?: number;
  band?: number;
}

const clamp = (x: number) => Math.max(0, Math.min(1, x));

/** A thin 0 to 1 meter with the policy threshold and uncertainty band marked. */
export function ScoreBar({ label, value, threshold, band }: ScoreBarProps) {
  const has = value !== null && Number.isFinite(value);
  const v = has ? clamp(value) : 0;
  const passes = has && threshold !== undefined ? v >= threshold : undefined;
  const aria = has
    ? `${label} ${v.toFixed(2)}${threshold !== undefined ? `, threshold ${threshold.toFixed(2)}` : ''}`
    : `${label} not judged`;
  return (
    <div className="score">
      <span className="score-label">{label}</span>
      <span
        className="score-track"
        role="meter"
        aria-label={aria}
        aria-valuemin={0}
        aria-valuemax={1}
        aria-valuenow={has ? Number(v.toFixed(2)) : undefined}
      >
        {threshold !== undefined && band !== undefined && band > 0 && (
          <span
            className="score-band"
            style={{ left: `${clamp(threshold - band) * 100}%`, width: `${Math.min(band, threshold) * 100}%` }}
          />
        )}
        {has && <span className={`score-fill${passes === false ? ' is-below' : ''}`} style={{ width: `${v * 100}%` }} />}
        {threshold !== undefined && <span className="score-tick" style={{ left: `${clamp(threshold) * 100}%` }} />}
      </span>
      <span className="score-num">{has ? v.toFixed(2) : 'n/a'}</span>
    </div>
  );
}
