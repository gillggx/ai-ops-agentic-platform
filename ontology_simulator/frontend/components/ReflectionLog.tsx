"use client";
import { useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { BrainCircuit } from "lucide-react";

interface Reflection {
  id: string;
  msg: string;
  time: string;
}

export default function ReflectionLog({ reflections }: { reflections: Reflection[] }) {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Smooth-scroll to latest without causing flicker
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [reflections.length]);

  return (
    <div className="border border-[#334155] rounded-xl bg-[#1E293B]/60 p-4">
      <div className="flex items-center gap-2 mb-3">
        <BrainCircuit size={14} className="text-amber-400" />
        <span className="text-amber-400 text-xs font-semibold tracking-widest uppercase">
          Agent Reflection Log
        </span>
        <span className="ml-auto text-slate-600 text-xs">{reflections.length} events</span>
      </div>

      <div className="smooth-scroll max-h-36 overflow-y-auto space-y-1.5 pr-1">
        {reflections.length === 0 ? (
          <p className="text-slate-600 text-xs text-center py-4">No OOC events yet…</p>
        ) : (
          <AnimatePresence initial={false}>
            {reflections.map((r, i) => (
              <motion.div
                key={`${r.id}-${r.time}-${i}`}
                initial={{ opacity: 0, y: -6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3 }}
                className="flex gap-3 text-xs"
              >
                <span className="text-slate-600 font-mono shrink-0 tabular-nums">{r.time}</span>
                <span className="text-orange-400 font-mono shrink-0">[{r.id}]</span>
                <span className="text-slate-300 leading-relaxed">{r.msg}</span>
              </motion.div>
            ))}
          </AnimatePresence>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
