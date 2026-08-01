import React from "react";
import { View, StyleSheet } from "react-native";
import Svg, { Circle, Line, G, Text as SvgText } from "react-native-svg";
import { colors } from "@/src/theme";

type Node = { id: string; kind: string; label: string; weight: number };
type Edge = { src: string; dst: string; kind: string };

export default function GraphCanvas({ nodes, edges, width, height, selectedId }: {
  nodes: Node[]; edges: Edge[]; width: number; height: number; selectedId?: string | null;
}) {
  // Deterministic pseudo-random layout by hashing id
  const hash = (s: string) => {
    let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return Math.abs(h);
  };
  const positions: Record<string, { x: number; y: number }> = {};
  const notes = nodes.filter(n => n.kind === "note");
  const concepts = nodes.filter(n => n.kind === "concept");
  const cx = width / 2, cy = height / 2;

  notes.forEach((n, i) => {
    const angle = (i / Math.max(notes.length, 1)) * Math.PI * 2;
    const rad = Math.min(width, height) * 0.28;
    positions[n.id] = { x: cx + Math.cos(angle) * rad, y: cy + Math.sin(angle) * rad };
  });
  concepts.forEach((c) => {
    const seed = hash(c.id);
    positions[c.id] = {
      x: 30 + (seed % (width - 60)),
      y: 40 + ((seed >> 4) % (height - 80)),
    };
  });

  return (
    <Svg width={width} height={height}>
      <G>
        {edges.map((e, idx) => {
          const a = positions[e.src]; const b = positions[e.dst];
          if (!a || !b) return null;
          const isSel = selectedId && (e.src === selectedId || e.dst === selectedId);
          return (
            <Line
              key={idx}
              x1={a.x} y1={a.y} x2={b.x} y2={b.y}
              stroke={isSel ? colors.onSurface : colors.borderStrong}
              strokeWidth={isSel ? 1.5 : 0.6}
              opacity={isSel ? 1 : 0.5}
            />
          );
        })}
        {nodes.map((n) => {
          const p = positions[n.id]; if (!p) return null;
          const isNote = n.kind === "note";
          const size = isNote ? Math.min(18, 8 + n.weight) : Math.min(10, 5 + n.weight);
          const fill = isNote ? colors.onSurface : (selectedId === n.id ? colors.info : colors.agentPlanner);
          return (
            <G key={n.id}>
              <Circle cx={p.x} cy={p.y} r={size} fill={fill} opacity={selectedId && selectedId !== n.id ? 0.35 : 1} />
              {isNote && (
                <SvgText x={p.x + size + 4} y={p.y + 3} fontSize={9} fill={colors.onSurface}>
                  {n.label.slice(0, 14)}
                </SvgText>
              )}
            </G>
          );
        })}
      </G>
    </Svg>
  );
}
