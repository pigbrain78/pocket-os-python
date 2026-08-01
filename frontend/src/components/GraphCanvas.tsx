import React from "react";
import Svg, { Circle, Line, G, Text as SvgText } from "react-native-svg";
import { colors } from "@/src/theme";

type Node = { id: string; kind: string; label: string; weight: number };
type Edge = { src: string; dst: string; kind: string };

export default function GraphCanvas({ nodes, edges, width, height, selectedId, onNodePress }: {
  nodes: Node[]; edges: Edge[]; width: number; height: number;
  selectedId?: string | null;
  onNodePress?: (n: Node) => void;
}) {
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

  // Compute neighbor set of selected
  const neighbors = new Set<string>();
  if (selectedId) {
    edges.forEach(e => {
      if (e.src === selectedId) neighbors.add(e.dst);
      if (e.dst === selectedId) neighbors.add(e.src);
    });
    neighbors.add(selectedId);
  }

  const isDim = (id: string) => !!selectedId && !neighbors.has(id);

  return (
    <Svg width={width} height={height}>
      <G>
        {edges.map((e, idx) => {
          const a = positions[e.src]; const b = positions[e.dst];
          if (!a || !b) return null;
          const isSel = selectedId && (e.src === selectedId || e.dst === selectedId);
          const isDimmed = !!selectedId && !isSel;
          return (
            <Line
              key={idx}
              x1={a.x} y1={a.y} x2={b.x} y2={b.y}
              stroke={isSel ? colors.onSurface : colors.borderStrong}
              strokeWidth={isSel ? 1.8 : 0.6}
              opacity={isDimmed ? 0.08 : (isSel ? 1 : 0.5)}
            />
          );
        })}
        {nodes.map((n) => {
          const p = positions[n.id]; if (!p) return null;
          const isNote = n.kind === "note";
          const size = isNote ? Math.min(18, 8 + n.weight) : Math.min(10, 5 + n.weight);
          const isSelf = selectedId === n.id;
          const inNeighborhood = neighbors.has(n.id);
          const fill = isNote ? colors.onSurface : (isSelf ? colors.info : colors.agentPlanner);
          const nodeOpacity = !selectedId ? 1 : (isSelf ? 1 : (inNeighborhood ? 0.9 : 0.15));
          const r = isSelf ? size + 3 : size;
          return (
            <G key={n.id} onPress={() => onNodePress?.(n)}>
              {isSelf ? (
                <Circle cx={p.x} cy={p.y} r={r + 6} fill={colors.info} opacity={0.15} />
              ) : null}
              <Circle cx={p.x} cy={p.y} r={r} fill={fill} opacity={nodeOpacity} />
              {isNote && !selectedId ? (
                <SvgText x={p.x + size + 4} y={p.y + 3} fontSize={9} fill={colors.onSurface}>
                  {n.label.slice(0, 14)}
                </SvgText>
              ) : null}
              {isSelf ? (
                <SvgText x={p.x + r + 6} y={p.y + 3} fontSize={11} fill={colors.onSurface} fontWeight="bold">
                  {n.label.slice(0, 18)}
                </SvgText>
              ) : null}
            </G>
          );
        })}
      </G>
    </Svg>
  );
}
