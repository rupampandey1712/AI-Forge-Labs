/**
 * Shared motion vocabulary.
 *
 * WHY one module rather than inline `transition={{...}}` at every call site:
 * animation is a language, and a codebase where every card picks its own spring
 * reads as noise rather than as feedback. These are the six or so movements the
 * whole game uses, so a panel sliding in on the World Map feels like the same
 * product as a chunk boundary snapping in the RAG bench.
 *
 * REDUCED MOTION is honoured here, once, rather than in components. Every
 * variant below collapses to an opacity fade when the OS asks for it — the
 * information still arrives, it just stops moving. Note the check runs at module
 * load: a mid-session settings change needs a reload, which is an acceptable
 * trade for not threading a media-query hook through ~30 components.
 */

import type { Transition, Variants } from 'framer-motion';
import { prefersReducedMotion } from './utils';

const still = prefersReducedMotion();

/** Snappy default. Springs read as *physical*; eased tweens read as *UI*. */
export const spring: Transition = still
  ? { duration: 0 }
  : { type: 'spring', stiffness: 260, damping: 26, mass: 0.7 };

/** Heavier — for things with visual weight, like a panel or a modal. */
export const springSoft: Transition = still
  ? { duration: 0 }
  : { type: 'spring', stiffness: 150, damping: 22, mass: 0.9 };

/** For numbers and bars, where overshoot would misrepresent the value. */
export const ease: Transition = still
  ? { duration: 0 }
  : { duration: 0.34, ease: [0.22, 1, 0.36, 1] };

export const quick: Transition = still ? { duration: 0 } : { duration: 0.16, ease: 'easeOut' };

const move = (axis: 'x' | 'y', distance: number) => (still ? {} : { [axis]: distance });

// ── Entrances ───────────────────────────────────────────────────────────────
export const fadeUp: Variants = {
  hidden: { opacity: 0, ...move('y', 12) },
  show: { opacity: 1, y: 0, transition: spring },
  exit: { opacity: 0, ...move('y', -8), transition: quick },
};

export const fadeIn: Variants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: ease },
  exit: { opacity: 0, transition: quick },
};

export const slideRight: Variants = {
  hidden: { opacity: 0, ...move('x', -16) },
  show: { opacity: 1, x: 0, transition: spring },
  exit: { opacity: 0, ...move('x', 16), transition: quick },
};

export const popIn: Variants = {
  hidden: { opacity: 0, scale: still ? 1 : 0.92 },
  show: { opacity: 1, scale: 1, transition: spring },
  exit: { opacity: 0, scale: still ? 1 : 0.96, transition: quick },
};

/**
 * Parent for a list. Children inherit `hidden`/`show` automatically, so a grid
 * cascades in without any child needing to know its own index.
 *
 * `stagger` is small on purpose: 60ms across twelve cards is 720ms, which is
 * already at the edge of feeling slow rather than deliberate.
 */
export const stagger = (delay = 0.04): Variants => ({
  hidden: {},
  show: { transition: still ? {} : { staggerChildren: delay, delayChildren: 0.02 } },
  exit: { transition: still ? {} : { staggerChildren: 0.015, staggerDirection: -1 } },
});

/** Route-level transition: the page itself, not its contents. */
export const pageTransition: Variants = {
  hidden: { opacity: 0, ...move('y', 8) },
  show: { opacity: 1, y: 0, transition: { ...springSoft, when: 'beforeChildren' } },
  exit: { opacity: 0, ...move('y', -6), transition: quick },
};

// ── Interaction ─────────────────────────────────────────────────────────────
/** Spread onto an interactive card. No-ops under reduced motion. */
export const hoverLift = still
  ? {}
  : { whileHover: { y: -3, transition: quick }, whileTap: { scale: 0.985 } };

export const hoverGlow = still
  ? {}
  : { whileHover: { scale: 1.02, transition: quick }, whileTap: { scale: 0.97 } };

// ── Data viz ────────────────────────────────────────────────────────────────
/**
 * A heatmap cell appearing. Delay is derived from position so the matrix fills
 * diagonally — which is not decoration: it is the order an attention matrix is
 * actually computed in, and watching it fill makes the causal mask obvious.
 */
export const cellIn = (row: number, col: number, size: number) =>
  still
    ? { initial: { opacity: 1 }, animate: { opacity: 1 } }
    : {
        initial: { opacity: 0, scale: 0.6 },
        animate: { opacity: 1, scale: 1 },
        transition: { delay: Math.min(0.5, ((row + col) / Math.max(1, size * 2)) * 0.5), ...quick },
      };

/** Bars grow from their baseline rather than fading in — height *is* the datum. */
export const barGrow = (delay = 0): Variants => ({
  hidden: { scaleY: still ? 1 : 0, opacity: still ? 1 : 0.4 },
  show: {
    scaleY: 1,
    opacity: 1,
    transition: still ? { duration: 0 } : { ...ease, delay },
  },
});

export const REDUCED_MOTION = still;
