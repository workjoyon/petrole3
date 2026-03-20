import { useRef, useEffect, useMemo, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useAppStore } from "../../store/appStore";
import { useCountries, useChokepoints } from "../../api/hooks";
import type { Country, Chokepoint, CountryImpact, StressStatus } from "../../types";

const STRESS_COLORS: Record<StressStatus, string> = {
  stable: "#22c55e",
  tension: "#eab308",
  critical: "#f97316",
  emergency: "#ef4444",
};
const DEFAULT_COLOR = "#7cc8fb";
const SELECTED_COLOR = "#3b82f6";
const MAP_STYLE = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";

/* ------------------------------------------------------------------ */
/*  GeoJSON builders — points from API data, zero external dependency  */
/* ------------------------------------------------------------------ */

function countriesToGeoJSON(
  countries: Country[],
  impactMap: Map<string, CountryImpact>,
  selectedCode: string | null,
): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: countries.map((c) => {
      const ci = impactMap.get(c.code);
      return {
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: [c.longitude, c.latitude] },
        properties: {
          code: c.code,
          name: c.name,
          color: ci ? STRESS_COLORS[ci.stress_status] : c.code === selectedCode ? SELECTED_COLOR : DEFAULT_COLOR,
          radius: ci ? Math.max(8, Math.min(18, 8 + ci.stress_score * 0.10)) : c.code === selectedCode ? 10 : 7,
          opacity: ci ? 0.9 : c.code === selectedCode ? 0.85 : 0.6,
          strokeColor: c.code === selectedCode ? "#ffffff" : ci ? STRESS_COLORS[ci.stress_status] : "transparent",
          strokeWidth: c.code === selectedCode ? 2.5 : ci ? 1.5 : 0,
          // Glow layer: larger translucent circle behind the main one
          glowRadius: ci ? Math.max(16, Math.min(32, 16 + ci.stress_score * 0.16)) : c.code === selectedCode ? 18 : 0,
          glowOpacity: ci ? 0.25 : c.code === selectedCode ? 0.2 : 0,
          status: ci?.stress_status ?? "",
          score: ci?.stress_score ?? 0,
        },
      };
    }),
  };
}

function chokepointsToGeoJSON(chokepoints: Chokepoint[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: chokepoints.map((cp) => ({
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [cp.longitude, cp.latitude] },
      properties: { id: cp.id, name: cp.name, throughput: cp.throughput_mbpd },
    })),
  };
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function MapView() {
  const mapContainer = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [mapReady, setMapReady] = useState(false);

  const { data: countries } = useCountries();
  const { data: chokepoints } = useChokepoints();
  const countryImpacts = useAppStore((s) => s.countryImpacts);
  const selectedCountryCode = useAppStore((s) => s.selectedCountryCode);
  const setSelectedCountryCode = useAppStore((s) => s.setSelectedCountryCode);
  const setSelectedChokepointId = useAppStore((s) => s.setSelectedChokepointId);

  const impactMap = useMemo(() => {
    const m = new Map<string, CountryImpact>();
    countryImpacts.forEach((ci) => m.set(ci.country_code, ci));
    return m;
  }, [countryImpacts]);

  // ---- Initialize map (once) ----
  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: mapContainer.current,
      style: MAP_STYLE,
      center: [40, 25],
      zoom: 2.2,
      minZoom: 1.5,
      maxZoom: 8,
      attributionControl: false,
    });
    map.addControl(new maplibregl.NavigationControl(), "bottom-left");
    mapRef.current = map;

    map.on("load", () => {
      // Country points — source + layers (data set later)
      map.addSource("country-pts", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });

      // 1. Glow layer (behind)
      map.addLayer({
        id: "country-glow",
        type: "circle",
        source: "country-pts",
        paint: {
          "circle-radius": ["get", "glowRadius"],
          "circle-color": ["get", "color"],
          "circle-opacity": ["get", "glowOpacity"],
          "circle-blur": 1,
        },
      });

      // 2. Main circle
      map.addLayer({
        id: "country-circle",
        type: "circle",
        source: "country-pts",
        paint: {
          "circle-radius": ["get", "radius"],
          "circle-color": ["get", "color"],
          "circle-opacity": ["get", "opacity"],
          "circle-stroke-color": ["get", "strokeColor"],
          "circle-stroke-width": ["get", "strokeWidth"],
        },
      });

      // Chokepoint points — source + layers
      map.addSource("chokepoint-pts", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "chokepoint-diamond",
        type: "circle",
        source: "chokepoint-pts",
        paint: {
          "circle-radius": 7,
          "circle-color": "rgba(239,68,68,0.7)",
          "circle-stroke-color": "rgba(239,68,68,0.9)",
          "circle-stroke-width": 1.5,
        },
      });

      // Click handlers
      map.on("click", "country-circle", (e) => {
        const code = e.features?.[0]?.properties?.code;
        if (code) setSelectedCountryCode(code);
      });
      map.on("click", "chokepoint-diamond", (e) => {
        const id = e.features?.[0]?.properties?.id;
        if (id) setSelectedChokepointId(id);
      });

      // Cursor
      for (const layer of ["country-circle", "chokepoint-diamond"]) {
        map.on("mouseenter", layer, () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", layer, () => { map.getCanvas().style.cursor = ""; });
      }

      setMapReady(true);
    });

    return () => { map.remove(); mapRef.current = null; setMapReady(false); };
  }, [setSelectedCountryCode, setSelectedChokepointId]);

  // ---- Update country data on the source whenever deps change ----
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !countries) return;
    const src = map.getSource("country-pts") as maplibregl.GeoJSONSource | undefined;
    if (!src) return;
    src.setData(countriesToGeoJSON(countries, impactMap, selectedCountryCode));
  }, [countries, impactMap, selectedCountryCode, mapReady]);

  // ---- Update chokepoint data ----
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !chokepoints) return;
    const src = map.getSource("chokepoint-pts") as maplibregl.GeoJSONSource | undefined;
    if (!src) return;
    src.setData(chokepointsToGeoJSON(chokepoints));
  }, [chokepoints, mapReady]);

  return <div ref={mapContainer} className="w-full h-full" />;
}
