import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  PanResponder,
  Pressable,
  LayoutChangeEvent,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import dayjs from "dayjs";
import { colors, spacing, radius, fs } from "@/src/theme";

type Bounds = { earliest?: string | null; latest?: string | null };

type Props = {
  bounds: Bounds;
  atMs: number; // current time position in unix ms
  onChange: (ms: number) => void; // fires continuously during drag
  onCommit: (ms: number) => void; // fires when drag ends (fetch replay)
  onReturnToNow: () => void;
};

const TRACK_HEIGHT = 48;
const HANDLE_SIZE = 28;

/**
 * A native, dependency-free horizontal scrubber for replaying the ledger.
 * The parent owns `atMs` and re-renders the scrubber on change. During a
 * drag we call `onChange` continuously (cheap — just updates local UI copy),
 * and only fire `onCommit` on release, so the network call to /api/replay
 * runs at most once per drag gesture.
 */
export default function TimeScrubber({
  bounds,
  atMs,
  onChange,
  onCommit,
  onReturnToNow,
}: Props) {
  const earliestMs = useMemo(
    () => (bounds.earliest ? dayjs(bounds.earliest).valueOf() : Date.now() - 24 * 3600_000),
    [bounds.earliest]
  );
  const latestMs = useMemo(
    () => (bounds.latest ? dayjs(bounds.latest).valueOf() : Date.now()),
    [bounds.latest]
  );
  const span = Math.max(1, latestMs - earliestMs);

  const [trackW, setTrackW] = useState(0);
  const dragStartRatioRef = useRef(0);
  const trackWRef = useRef(0);
  const spanRef = useRef(span);
  const earliestRef = useRef(earliestMs);
  const currentMsRef = useRef(atMs);

  useEffect(() => {
    trackWRef.current = trackW;
  }, [trackW]);
  useEffect(() => {
    spanRef.current = span;
    earliestRef.current = earliestMs;
  }, [span, earliestMs]);
  useEffect(() => {
    currentMsRef.current = atMs;
  }, [atMs]);

  const clampedAtMs = Math.min(Math.max(atMs, earliestMs), latestMs);
  const progress = trackW > 0 ? (clampedAtMs - earliestMs) / span : 0;
  const handleX = progress * Math.max(0, trackW - HANDLE_SIZE);

  const isAtLatest = latestMs - clampedAtMs < 1000; // within a second of latest = "now"

  const responder = useMemo(
    () =>
      PanResponder.create({
        onStartShouldSetPanResponder: () => true,
        onMoveShouldSetPanResponder: () => true,
        // Track the ratio at drag start so subsequent moves are delta-based.
        // This is the ONLY portable way — touch/mouse locationX semantics
        // differ across platforms, but dx is always relative to the grant.
        onPanResponderGrant: () => {
          const usable = Math.max(1, trackWRef.current - HANDLE_SIZE);
          const currentX =
            ((currentMsRef.current - earliestRef.current) / Math.max(1, spanRef.current)) * usable;
          dragStartRatioRef.current = Math.max(0, Math.min(1, currentX / usable));
        },
        onPanResponderMove: (_e, gestureState) => {
          const width = trackWRef.current;
          if (width <= 0) return;
          const usable = Math.max(1, width - HANDLE_SIZE);
          const deltaRatio = gestureState.dx / usable;
          const newRatio = Math.max(0, Math.min(1, dragStartRatioRef.current + deltaRatio));
          const ms = earliestRef.current + newRatio * spanRef.current;
          onChange(ms);
        },
        onPanResponderRelease: () => {
          onCommit(currentMsRef.current);
        },
        onPanResponderTerminate: () => {
          onCommit(currentMsRef.current);
        },
      }),
    // Stable — never rebuild the responder; refs carry latest values.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  const trackRef = useRef<View | null>(null);
  const trackPageXRef = useRef(0);

  const onTrackLayout = (ev: LayoutChangeEvent) => {
    setTrackW(ev.nativeEvent.layout.width);
    // Also measure the track's page position for accurate tap-to-jump on web,
    // where locationX semantics are inconsistent across react-native-web
    // element types.
    trackRef.current?.measureInWindow?.((pageX) => {
      trackPageXRef.current = pageX;
    });
  };

  const handleTapTrack = (ev: any) => {
    const width = trackWRef.current;
    if (!width) return;
    const pageX =
      (ev?.nativeEvent && (ev.nativeEvent.pageX ?? ev.nativeEvent.locationX)) ?? 0;
    // Prefer pageX minus the measured track origin; fall back to locationX.
    const localX =
      trackPageXRef.current > 0
        ? pageX - trackPageXRef.current
        : ev?.nativeEvent?.locationX ?? 0;
    const ratio = Math.max(
      0,
      Math.min(1, (localX - HANDLE_SIZE / 2) / Math.max(1, width - HANDLE_SIZE))
    );
    const ms = earliestRef.current + ratio * spanRef.current;
    onChange(ms);
    onCommit(ms);
  };

  return (
    <View style={styles.wrap}>
      <View style={styles.row}>
        <Text style={styles.side}>{dayjs(earliestMs).format("MMM D")}</Text>
        {isAtLatest ? (
          <View style={styles.livePill}>
            <View style={styles.liveDot} />
            <Text style={styles.liveT}>LIVE</Text>
          </View>
        ) : (
          <Pressable onPress={onReturnToNow} style={styles.nowBtn} testID="return-to-now">
            <Ionicons name="play-forward" size={12} color="#fff" />
            <Text style={styles.nowBtnT}>Return to Now</Text>
          </Pressable>
        )}
        <Text style={styles.side}>Now</Text>
      </View>
      <Pressable ref={trackRef as any} onLayout={onTrackLayout} onPress={handleTapTrack} style={styles.track} testID="scrubber-track">
        <View style={styles.trackLine} />
        <View style={[styles.trackFill, { width: Math.max(HANDLE_SIZE / 2, handleX + HANDLE_SIZE / 2) }]} />
        <View
          {...responder.panHandlers}
          style={[styles.handle, { transform: [{ translateX: handleX }] }]}
          testID="scrubber-handle"
        >
          <Ionicons name="reorder-three" size={14} color="#fff" />
        </View>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: spacing.xs,
  },
  side: { color: colors.muted, fontSize: fs.sm, fontWeight: "600" },
  livePill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.success + "22",
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 999,
  },
  liveDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.success },
  liveT: { color: colors.success, fontSize: fs.sm, fontWeight: "800", letterSpacing: 0.5 },
  nowBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.onSurface,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 999,
  },
  nowBtnT: { color: "#fff", fontSize: fs.sm, fontWeight: "800", letterSpacing: 0.3 },
  track: {
    height: TRACK_HEIGHT,
    justifyContent: "center",
    borderRadius: radius.md,
  },
  trackLine: {
    position: "absolute",
    left: HANDLE_SIZE / 2,
    right: HANDLE_SIZE / 2,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.border,
  },
  trackFill: {
    position: "absolute",
    left: 0,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.onSurface,
  },
  handle: {
    position: "absolute",
    left: 0,
    width: HANDLE_SIZE,
    height: HANDLE_SIZE,
    borderRadius: HANDLE_SIZE / 2,
    backgroundColor: colors.onSurface,
    alignItems: "center",
    justifyContent: "center",
    shadowColor: "#000",
    shadowOpacity: 0.25,
    shadowRadius: 4,
    shadowOffset: { width: 0, height: 2 },
    elevation: 4,
  },
});
