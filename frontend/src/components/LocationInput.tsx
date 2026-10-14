import { useEffect, useId, useRef, useState } from "react";
import { api, type Place, type ResolvedPlace } from "../api";

interface Props {
  label: string;
  value: Place;
  onChange: (place: Place) => void;
  placeholder?: string;
  marker: "A" | "B";
}

/** Text input with debounced place autocomplete and keyboard navigation. */
export function LocationInput({ label, value, onChange, placeholder, marker }: Props) {
  const [results, setResults] = useState<ResolvedPlace[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [loading, setLoading] = useState(false);
  const typed = useRef(false);
  const id = useId();

  useEffect(() => {
    // Only search for text the user typed, not for a picked suggestion.
    if (!typed.current || value.label.trim().length < 2) {
      setResults([]);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const { results } = await api.geocode(value.label, controller.signal);
        setResults(results);
        setActive(0);
        setOpen(true);
      } catch {
        /* aborted or offline: keep the previous list */
      } finally {
        setLoading(false);
      }
    }, 280);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [value.label]);

  const pick = (place: ResolvedPlace) => {
    typed.current = false;
    onChange({ label: place.label, lat: place.lat, lon: place.lon });
    setOpen(false);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!open || results.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => (a + 1) % results.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => (a - 1 + results.length) % results.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      pick(results[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const resolved = value.lat !== undefined;
  return (
    <div className="field location">
      <label htmlFor={id}>{label}</label>
      <div className="location-input">
        <span className={`location-marker marker-${marker}`}>{marker}</span>
        <input
          id={id}
          value={value.label}
          placeholder={placeholder}
          autoComplete="off"
          role="combobox"
          aria-expanded={open}
          aria-controls={`${id}-list`}
          onChange={(e) => {
            typed.current = true;
            onChange({ label: e.target.value });
          }}
          onFocus={() => results.length && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={onKeyDown}
        />
        {loading && <span className="spinner small" aria-label="Searching" />}
        {!loading && resolved && <span className="resolved" title="Location confirmed">✓</span>}
      </div>
      {open && results.length > 0 && (
        <ul className="suggestions" id={`${id}-list`} role="listbox">
          {results.map((r, i) => (
            <li
              key={`${r.lat},${r.lon}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : ""}
              onMouseDown={(e) => {
                e.preventDefault();
                pick(r);
              }}
              onMouseEnter={() => setActive(i)}
            >
              {r.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
