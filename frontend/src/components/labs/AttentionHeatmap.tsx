/**
 * The attention matrix, drawn cell by cell.
 *
 * WHAT IT SHOWS: row `i`, column `j` is "how much does token *i* attend to
 * token *j*". Every row sums to 1 — it is a probability distribution over which
 * earlier words this word is looking at.
 *
 * WHY A GRID OF DIVS rather than canvas or a chart library: the matrices here
 * are at most ~32×32 (the input is capped at 400 characters), so DOM cost is
 * irrelevant, and in exchange every cell is individually hoverable, focusable
 * and announceable. The player needs to point at a cell and ask "why is *that*
 * one bright?" — which a canvas cannot answer.
 *
 * THE TEACHING MOMENT is the causal toggle. With `causal` on, the entire upper
 * triangle is exactly zero, and seeing that black wedge appear is what makes
 * "a decoder cannot see the future" stop being a sentence and start being a
 * shape.
 */

import { motion } from 'framer-motion';
import { useState } from 'react';
import { cn } from '@/lib/utils';
import { cellIn, quick } from '@/lib/motion';
import type { AttentionHead, LabToken } from '@/types/labs';

/**
 * Weight -> colour. Deliberately NOT linear.
 *
 * Softmax output over ~10 tokens clusters near 1/n, so a linear ramp renders
 * every interesting matrix as uniform grey. The square root expands the low end
 * where the variation actually lives. This is a display transform only — the
 * printed number in each cell is always the true weight, because a visualiser
 * that quietly rescales its own data is worse than no visualiser.
 */
function cellColor(weight: number, max: number): string {
  if (weight <= 0) return 'rgb(10 14 26)';
  const normalised = Math.sqrt(Math.min(1, weight / (max || 1)));
  return `rgb(34 211 238 / ${(0.06 + normalised * 0.84).toFixed(3)})`;
}

export function AttentionHeatmap({
  head,
  tokens,
  causal,
  showRaw = false,
}: {
  head: AttentionHead;
  tokens: LabToken[];
  causal: boolean;
  /** Show pre-softmax scores instead — where `scaled` becomes visible. */
  showRaw?: boolean;
}) {
  const [hover, setHover] = useState<{ row: number; col: number } | null>(null);
  const matrix = showRaw ? head.raw_scores : head.weights;
  const size = tokens.length;
  const max = Math.max(...matrix.flat().map(Math.abs), 1e-9);

  if (!size) return null;

  // Cells shrink as the sequence grows so a long sentence still fits without
  // a scrollbar, which would break the "see the whole shape at once" point.
  const cell = size > 20 ? 20 : size > 14 ? 26 : size > 9 ? 34 : 42;

  return (
    <div className="overflow-x-auto">
      <div className="inline-block min-w-min">
        <div className="flex">
          {/* Corner spacer: the row-label gutter. */}
          <div style={{ width: 74 }} />
          <div className="flex">
            {tokens.map((token, col) => (
              <div
                key={col}
                style={{ width: cell }}
                className={cn(
                  'pb-1 text-center font-mono text-[10px] transition-colors',
                  hover?.col === col ? 'text-accent' : 'text-forge-500',
                )}
              >
                <span className="block truncate">{token.text.slice(0, 4)}</span>
              </div>
            ))}
          </div>
        </div>

        {matrix.map((row, i) => (
          <div key={i} className="flex items-center">
            <div
              style={{ width: 74 }}
              className={cn(
                'pr-2 text-right font-mono text-[10px] transition-colors',
                hover?.row === i ? 'text-accent' : 'text-forge-400',
              )}
            >
              <span className="block truncate">{tokens[i]?.text}</span>
            </div>
            {row.map((weight, j) => {
              const masked = causal && j > i;
              const active = hover?.row === i || hover?.col === j;
              return (
                <motion.button
                  key={j}
                  type="button"
                  {...cellIn(i, j, size)}
                  onMouseEnter={() => setHover({ row: i, col: j })}
                  onMouseLeave={() => setHover(null)}
                  onFocus={() => setHover({ row: i, col: j })}
                  onBlur={() => setHover(null)}
                  style={{
                    width: cell,
                    height: cell,
                    backgroundColor: showRaw
                      ? weight >= 0
                        ? `rgb(34 211 238 / ${(Math.abs(weight) / max) * 0.8 + 0.05})`
                        : `rgb(244 63 94 / ${(Math.abs(weight) / max) * 0.8 + 0.05})`
                      : cellColor(weight, max),
                  }}
                  className={cn(
                    'relative border border-forge-950/60 outline-none',
                    active && 'z-10 ring-1 ring-accent',
                    masked && 'bg-forge-950',
                  )}
                  aria-label={`${tokens[i]?.text} attends to ${tokens[j]?.text}: ${weight.toFixed(3)}${masked ? ' (masked)' : ''}`}
                  title={`${tokens[i]?.text} → ${tokens[j]?.text} = ${weight.toFixed(4)}${masked ? '  (masked: future token)' : ''}`}
                >
                  {cell >= 34 && !masked && (
                    <span
                      className={cn(
                        'pointer-events-none absolute inset-0 flex items-center justify-center font-mono text-[9px] tabular-nums',
                        weight / max > 0.55 ? 'text-forge-950' : 'text-forge-300',
                      )}
                    >
                      {showRaw ? weight.toFixed(1) : weight.toFixed(2)}
                    </span>
                  )}
                  {masked && cell >= 26 && (
                    <span className="pointer-events-none absolute inset-0 flex items-center justify-center text-[10px] text-forge-700">
                      ×
                    </span>
                  )}
                </motion.button>
              );
            })}
            {!showRaw && (
              <motion.span
                animate={{ opacity: hover?.row === i ? 1 : 0.4 }}
                transition={quick}
                className="pl-2 font-mono text-[10px] tabular-nums text-forge-500"
                title="Entropy of this row: low = this token is focused on one place, high = it is looking everywhere."
              >
                H={head.entropy[i]?.toFixed(2)}
              </motion.span>
            )}
          </div>
        ))}

        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-forge-500">
          <span>
            Row = <span className="text-forge-300">querying</span> token · Column ={' '}
            <span className="text-forge-300">attended</span> token
          </span>
          {hover && (
            <motion.span
              initial={{ opacity: 0, x: -4 }}
              animate={{ opacity: 1, x: 0 }}
              className="font-mono text-accent"
            >
              {tokens[hover.row]?.text} → {tokens[hover.col]?.text} ={' '}
              {matrix[hover.row]?.[hover.col]?.toFixed(4)}
            </motion.span>
          )}
        </div>
      </div>
    </div>
  );
}
