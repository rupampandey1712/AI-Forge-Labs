/**
 * The agent graph, drawn from its real topology and animated along its real
 * execution path.
 *
 * WHY HAND-ROLLED SVG rather than a graph library: the graphs here have 4–8
 * nodes, and what the lab needs is not general graph layout — it is three
 * specific things a generic renderer will not give you:
 *
 *   1. **Back-edges must look different from forward edges.** A cycle is the
 *      single most important thing to see in an agent graph, because a cycle
 *      without a termination argument is the bug. They are drawn as dashed
 *      arcs that bow away from the spine, so they are unmissable.
 *   2. **The execution path replays over the topology.** Watching the active
 *      node walk the same diagram you were just reading is what connects "the
 *      graph" to "the trace".
 *   3. **Visit counts render on the node.** `think ×4` next to `act ×3` is the
 *      whole diagnosis of a runaway loop, in two numbers.
 *
 * LAYOUT is a longest-path layering: a node sits one level deeper than its
 * deepest forward predecessor. Cycles are excluded from the depth calculation
 * (otherwise it never terminates), which is also the honest rendering — a
 * back-edge is a return to an earlier level, and it should look like one.
 */

import { AnimatePresence, motion } from 'framer-motion';
import { useMemo } from 'react';
import { cn } from '@/lib/utils';
import { REDUCED_MOTION, quick, spring } from '@/lib/motion';
import type { GraphDiagram } from '@/types/labs';

const NODE_W = 132;
const NODE_H = 46;
const GAP_Y = 76;
const GAP_X = 26;

interface Placed {
  id: string;
  label: string;
  kind: string;
  description: string;
  interrupt: boolean;
  isEntry: boolean;
  x: number;
  y: number;
}

function layout(diagram: GraphDiagram): { nodes: Placed[]; width: number; height: number } {
  const ids = diagram.nodes.map((n) => n.id);
  const forward = new Map<string, string[]>(ids.map((id) => [id, []]));

  // A back-edge is one whose target we have already reached; detecting them by
  // BFS order is enough here and avoids a second traversal.
  const order = new Map<string, number>();
  const queue: string[] = [];
  const start = diagram.entry ?? ids[0];
  if (start !== undefined) {
    queue.push(start);
    order.set(start, 0);
  }
  let cursor = 0;
  while (cursor < queue.length) {
    const current = queue[cursor++];
    for (const edge of diagram.edges.filter((e) => e.source === current)) {
      if (!order.has(edge.target)) {
        order.set(edge.target, order.size);
        queue.push(edge.target);
      }
    }
  }
  for (const edge of diagram.edges) {
    const from = order.get(edge.source) ?? 0;
    const to = order.get(edge.target) ?? 0;
    if (to > from) forward.get(edge.source)?.push(edge.target);
  }

  const depth = new Map<string, number>();
  const resolve = (id: string, seen: Set<string>): number => {
    if (depth.has(id)) return depth.get(id)!;
    if (seen.has(id)) return 0;
    seen.add(id);
    const parents = ids.filter((other) => forward.get(other)?.includes(id));
    const value = parents.length ? Math.max(...parents.map((p) => resolve(p, seen) + 1)) : 0;
    depth.set(id, value);
    return value;
  };
  for (const id of ids) resolve(id, new Set());

  const rows = new Map<number, string[]>();
  for (const id of ids) {
    const level = depth.get(id) ?? 0;
    rows.set(level, [...(rows.get(level) ?? []), id]);
  }

  const widest = Math.max(...[...rows.values()].map((r) => r.length), 1);
  const width = widest * NODE_W + (widest - 1) * GAP_X + 40;
  const placed: Placed[] = [];
  for (const [level, members] of [...rows.entries()].sort((a, b) => a[0] - b[0])) {
    const rowWidth = members.length * NODE_W + (members.length - 1) * GAP_X;
    const startX = (width - rowWidth) / 2;
    members.forEach((id, index) => {
      const node = diagram.nodes.find((n) => n.id === id)!;
      placed.push({
        id,
        label: node.label,
        kind: node.kind,
        description: node.description,
        interrupt: node.interrupt_before,
        isEntry: node.is_entry,
        x: startX + index * (NODE_W + GAP_X),
        y: 20 + level * (NODE_H + GAP_Y),
      });
    });
  }
  const height = (Math.max(...depth.values()) + 1) * (NODE_H + GAP_Y) + 20;
  return { nodes: placed, width, height };
}

const KIND_FILL: Record<string, string> = {
  start: '#0891b2',
  end: '#3a4670',
  llm: '#a78bfa',
  tool: '#34d399',
  router: '#fbbf24',
  retrieve: '#22d3ee',
  human: '#f43f5e',
};

export function GraphCanvas({
  diagram,
  activeNode,
  visitedPath = [],
  visits = {},
  onSelectNode,
}: {
  diagram: GraphDiagram;
  /** Highlighted as currently executing during replay. */
  activeNode?: string | null;
  /** Node ids in execution order — edges along it are drawn as travelled. */
  visitedPath?: string[];
  visits?: Record<string, number>;
  onSelectNode?: (id: string) => void;
}) {
  const { nodes, width, height } = useMemo(() => layout(diagram), [diagram]);
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);

  const travelled = useMemo(() => {
    const set = new Set<string>();
    for (let i = 0; i < visitedPath.length - 1; i += 1) {
      set.add(`${visitedPath[i]}->${visitedPath[i + 1]}`);
    }
    return set;
  }, [visitedPath]);

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        style={{ width: '100%', minWidth: Math.min(width, 560), height }}
        role="img"
        aria-label={`Agent graph: ${diagram.name}`}
      >
        <defs>
          <marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M0,0 L8,4 L0,8 z" fill="#5b6a99" />
          </marker>
          <marker id="arrow-live" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M0,0 L8,4 L0,8 z" fill="#22d3ee" />
          </marker>
          <marker id="arrow-cycle" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M0,0 L8,4 L0,8 z" fill="#fbbf24" />
          </marker>
        </defs>

        {diagram.edges.map((edge, index) => {
          const from = byId.get(edge.source);
          const to = byId.get(edge.target);
          if (!from || !to) return null;

          const isBack = to.y <= from.y;
          const live = travelled.has(`${edge.source}->${edge.target}`);
          const x1 = from.x + NODE_W / 2;
          const y1 = from.y + NODE_H;
          const x2 = to.x + NODE_W / 2;
          const y2 = isBack ? to.y + NODE_H / 2 : to.y;

          // Back-edges bow out to the side so they never hide under the spine.
          const path = isBack
            ? `M ${x1} ${y1 - NODE_H / 2} C ${x1 + 130} ${y1}, ${x2 + 130} ${y2}, ${x2 + NODE_W / 2 + 4} ${y2}`
            : `M ${x1} ${y1} C ${x1} ${y1 + 34}, ${x2} ${y2 - 34}, ${x2} ${y2 - 4}`;

          const stroke = live ? '#22d3ee' : isBack ? '#fbbf24' : '#3a4670';
          return (
            <g key={`${edge.source}-${edge.target}-${index}`}>
              <motion.path
                d={path}
                fill="none"
                stroke={stroke}
                strokeWidth={live ? 2.2 : 1.4}
                strokeDasharray={isBack ? '5 4' : edge.kind === 'conditional' ? '2 3' : undefined}
                markerEnd={`url(#${live ? 'arrow-live' : isBack ? 'arrow-cycle' : 'arrow'})`}
                initial={REDUCED_MOTION ? false : { pathLength: 0, opacity: 0 }}
                animate={{ pathLength: 1, opacity: 1 }}
                transition={{ duration: 0.5, delay: index * 0.04 }}
              >
                <title>
                  {edge.source} → {edge.target}
                  {edge.label ? ` [${edge.label}]` : ''}
                  {isBack ? ' — back-edge: this is what makes the graph loop' : ''}
                </title>
              </motion.path>
              {edge.label && (
                <text
                  x={(x1 + x2) / 2 + (isBack ? 96 : 6)}
                  y={(y1 + y2) / 2}
                  className="font-mono"
                  fontSize={9}
                  fill={live ? '#67e8f9' : '#5b6a99'}
                >
                  {edge.label}
                </text>
              )}
            </g>
          );
        })}

        {nodes.map((node, index) => {
          const active = node.id === activeNode;
          const count = visits[node.id] ?? 0;
          const fill = KIND_FILL[node.kind] ?? '#273154';
          return (
            <motion.g
              key={node.id}
              initial={REDUCED_MOTION ? false : { opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ ...spring, delay: index * 0.05 }}
              style={{ transformOrigin: `${node.x + NODE_W / 2}px ${node.y + NODE_H / 2}px` }}
              onClick={() => onSelectNode?.(node.id)}
              className={onSelectNode ? 'cursor-pointer' : undefined}
            >
              <AnimatePresence>
                {active && (
                  <motion.rect
                    initial={{ opacity: 0, scale: 0.9 }}
                    animate={{ opacity: [0.5, 0.15, 0.5] }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 1.4, repeat: Infinity }}
                    x={node.x - 6}
                    y={node.y - 6}
                    width={NODE_W + 12}
                    height={NODE_H + 12}
                    rx={12}
                    fill="#22d3ee"
                  />
                )}
              </AnimatePresence>
              <rect
                x={node.x}
                y={node.y}
                width={NODE_W}
                height={NODE_H}
                rx={9}
                fill={active ? '#0f152a' : '#0b1020'}
                stroke={active ? '#22d3ee' : count > 0 ? fill : '#273154'}
                strokeWidth={active ? 2 : 1.3}
              />
              <rect x={node.x} y={node.y} width={4} height={NODE_H} rx={2} fill={fill} />
              <text
                x={node.x + 14}
                y={node.y + 20}
                fontSize={12}
                fill={active ? '#e3e8f7' : '#bcc6e3'}
                className="font-semibold"
              >
                {node.label.length > 15 ? `${node.label.slice(0, 14)}…` : node.label}
              </text>
              <text x={node.x + 14} y={node.y + 34} fontSize={9} fill="#5b6a99" className="font-mono">
                {node.kind}
                {node.isEntry ? ' · entry' : ''}
              </text>
              {node.interrupt && (
                <>
                  <circle cx={node.x + NODE_W - 14} cy={node.y + 14} r={5} fill="#f43f5e" />
                  <title>Interrupt: execution pauses here for human approval.</title>
                </>
              )}
              {count > 0 && (
                <motion.g
                  key={count}
                  initial={REDUCED_MOTION ? false : { scale: 1.6 }}
                  animate={{ scale: 1 }}
                  transition={quick}
                >
                  <rect
                    x={node.x + NODE_W - 34}
                    y={node.y + NODE_H - 18}
                    width={30}
                    height={15}
                    rx={7}
                    fill={count > 2 ? '#fbbf24' : '#273154'}
                  />
                  <text
                    x={node.x + NODE_W - 19}
                    y={node.y + NODE_H - 7}
                    fontSize={9}
                    textAnchor="middle"
                    fill={count > 2 ? '#0b1020' : '#bcc6e3'}
                    className="font-mono font-semibold"
                  >
                    ×{count}
                  </text>
                </motion.g>
              )}
            </motion.g>
          );
        })}
      </svg>

      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-forge-500">
        <LegendSwatch color="#3a4670">direct edge</LegendSwatch>
        <LegendSwatch color="#3a4670" dashed>
          conditional (a router picks)
        </LegendSwatch>
        <LegendSwatch color="#fbbf24" dashed>
          back-edge (the loop)
        </LegendSwatch>
        <LegendSwatch color="#f43f5e">interrupt — waits for a human</LegendSwatch>
      </div>
    </div>
  );
}

function LegendSwatch({
  color,
  dashed,
  children,
}: {
  color: string;
  dashed?: boolean;
  children: React.ReactNode;
}) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={cn('inline-block h-0 w-5 border-t-2', dashed && 'border-dashed')}
        style={{ borderColor: color }}
      />
      {children}
    </span>
  );
}
