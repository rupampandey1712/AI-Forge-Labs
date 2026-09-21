/**
 * Renders matplotlib figures a submission produced.
 *
 * WHY THIS IS NOT JUST `<img src={url}>`: the artifact route is authenticated,
 * so a bare img tag sends no Authorization header and gets a 401. Each figure
 * is fetched through the API client (which owns token refresh) and turned into
 * an object URL.
 *
 * The lifecycle matters more than it looks. Every object URL pins its blob in
 * memory until `revokeObjectURL` is called, so a workbench session that runs
 * twenty plots would hold twenty bitmaps alive with nothing referencing them —
 * a leak that looks like "the tab got slow" rather than like a bug. The effect
 * below revokes on unmount *and* whenever the url list changes.
 */

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { ImageOff, Loader2 } from 'lucide-react';
import { api } from '@/lib/api';
import { Card } from '@/components/ui';
import { fadeUp, stagger } from '@/lib/motion';

interface LoadedFigure {
  path: string;
  objectUrl: string | null;
  failed: boolean;
}

export function FigureGallery({ paths }: { paths: string[] }) {
  const [figures, setFigures] = useState<LoadedFigure[]>([]);

  useEffect(() => {
    if (paths.length === 0) {
      setFigures([]);
      return;
    }

    // `cancelled` guards the classic async-effect bug: a fast second submission
    // resolves after the first and writes stale images into current state.
    let cancelled = false;
    const created: string[] = [];

    setFigures(paths.map((path) => ({ path, objectUrl: null, failed: false })));

    void Promise.all(
      paths.map(async (path) => {
        try {
          const objectUrl = await api.artifacts.objectUrl(path);
          created.push(objectUrl);
          return { path, objectUrl, failed: false };
        } catch {
          // A figure that will not load is worth showing as a gap rather than
          // as nothing: the player ran plotting code and should know it did
          // not come back.
          return { path, objectUrl: null, failed: true };
        }
      }),
    ).then((loaded) => {
      if (cancelled) {
        loaded.forEach((f) => f.objectUrl && URL.revokeObjectURL(f.objectUrl));
        return;
      }
      setFigures(loaded);
    });

    return () => {
      cancelled = true;
      created.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [paths]);

  if (paths.length === 0) return null;

  return (
    <Card
      title={paths.length === 1 ? 'Your figure' : `Your figures (${paths.length})`}
      subtitle="Rendered by your code inside the sandbox"
    >
      <motion.div
        variants={stagger(0.06)}
        initial="hidden"
        animate="show"
        className="grid gap-3 sm:grid-cols-2"
      >
        {figures.map((figure) => (
          <motion.div
            key={figure.path}
            variants={fadeUp}
            className="overflow-hidden rounded-lg border border-forge-700 bg-white"
          >
            {figure.objectUrl ? (
              <img
                src={figure.objectUrl}
                alt="Figure produced by your submission"
                className="block w-full"
                loading="lazy"
              />
            ) : (
              <div className="flex h-40 items-center justify-center gap-2 bg-forge-900 text-xs text-forge-500">
                {figure.failed ? (
                  <>
                    <ImageOff className="h-4 w-4" />
                    Could not load this figure
                  </>
                ) : (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Loading…
                  </>
                )}
              </div>
            )}
          </motion.div>
        ))}
      </motion.div>
    </Card>
  );
}
