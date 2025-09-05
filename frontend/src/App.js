import React, { useEffect, useMemo, useState } from "react";

const API = "http://localhost:8000";

export default function App() {
  // Controls
  const [days, setDays] = useState(30);
  const [k, setK] = useState(12);
  const [source, setSource] = useState("all"); // all|slack|zendesk|jira
  const [kind, setKind] = useState("all");     // all|issue|feature_request|unknown

  // Data
  const [themes, setThemes] = useState(null);
  const [top, setTop] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  const qs = useMemo(() => {
    const p = new URLSearchParams({ days: String(days), k: String(k), source, kind });
    return p.toString();
  }, [days, k, source, kind]);

  const fetchThemes = async () => {
    setLoading(true); setErr(null);
    try {
      const res = await fetch(`${API}/insights/themes/v2?${qs}`);
      const data = await res.json();
      setThemes(data.themes || []);
      setTop({ top_issues: data.top_issues || [], top_features: data.top_features || [], run_id: data.run_id });
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  };

  const fetchTop10 = async () => {
    setLoading(true); setErr(null);
    try {
      const res = await fetch(`${API}/insights/top10?${qs}`);
      const data = await res.json();
      setTop({ top_issues: data.top_issues || [], top_features: data.top_features || [], run_id: data.run_id });
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchThemes(); /* auto-load on first render */ }, []); // eslint-disable-line

  const runRefresh = async () => { await fetchThemes(); };
  const exportTop10 = () => window.open(`${API}/export/top10.csv?${qs}`, "_blank");
  const exportThemes = () => window.open(`${API}/export/themes.csv?${qs}`, "_blank");

  return (
    <div style={{ padding: 20, fontFamily: "Inter, system-ui, sans-serif" }}>
      <h1>PM Insight Dashboard</h1>

      {/* Controls */}
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 12 }}>
        <label>Days:
          <input type="number" min="1" max="365" value={days} onChange={e => setDays(Number(e.target.value))} style={{ marginLeft: 6, width: 80 }} />
        </label>
        <label>K (clusters):
          <input type="number" min="1" max="100" value={k} onChange={e => setK(Number(e.target.value))} style={{ marginLeft: 6, width: 80 }} />
        </label>
        <label>Source:
          <select value={source} onChange={e => setSource(e.target.value)} style={{ marginLeft: 6 }}>
            <option value="all">All</option>
            <option value="slack">Slack</option>
            <option value="zendesk">Zendesk</option>
            <option value="jira">JIRA</option>
          </select>
        </label>
        <label>Type:
          <select value={kind} onChange={e => setKind(e.target.value)} style={{ marginLeft: 6 }}>
            <option value="all">All</option>
            <option value="issue">Issue</option>
            <option value="feature_request">Feature Request</option>
            <option value="unknown">Unknown</option>
          </select>
        </label>

        <button onClick={runRefresh} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
        <button onClick={fetchTop10} disabled={loading}>
          {loading ? "Loading…" : "Load Top 10"}
        </button>
        <button onClick={exportTop10} disabled={!top}>Export Top 10 CSV</button>
        <button onClick={exportThemes} disabled={!themes}>Export Themes CSV</button>
      </div>

      {err && <div style={{ color: "crimson", marginBottom: 12 }}>{err}</div>}

      {/* Top 10 Section */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <Card title="Top 10 Issues (Next Sprint)">
          {!top ? <p>Loading…</p> : (
            <ol>
              {top.top_issues?.map((t, i) => (
                <li key={i}>
                  <a href={t.url} target="_blank" rel="noreferrer">{t.title || t.url}</a>
                  <span style={{ opacity: 0.6 }}> — {t.source}</span>
                </li>
              ))}
            </ol>
          )}
        </Card>
        <Card title="Top 10 Feature Requests (Next Quarter)">
          {!top ? <p>Loading…</p> : (
            <ol>
              {top.top_features?.map((t, i) => (
                <li key={i}>
                  <a href={t.url} target="_blank" rel="noreferrer">{t.title || t.url}</a>
                  <span style={{ opacity: 0.6 }}> — {t.source}</span>
                </li>
              ))}
            </ol>
          )}
        </Card>
      </div>

      {/* Themes Grid */}
      <h2 style={{ marginTop: 24 }}>Themes</h2>
      {!themes ? <p>Loading…</p> : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(320px,1fr))", gap: 12 }}>
          {themes.map((th, i) => <ThemeCard key={i} theme={th} />)}
          {themes.length === 0 && <p>No themes for the selected filters.</p>}
        </div>
      )}
    </div>
  );
}

function Card({ title, children }) {
  return (
    <div style={{ border: "1px solid #e5e5e5", borderRadius: 12, padding: 14, background: "#fff" }}>
      <h3 style={{ marginTop: 0 }}>{title}</h3>
      {children}
    </div>
  );
}

function ThemeCard({ theme }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ border: "1px solid #e5e5e5", borderRadius: 12, padding: 14, background: "#fff" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
        <div>
          <div style={{ fontSize: 14, opacity: 0.7 }}>Theme #{theme.label} · {theme.type}</div>
          <div style={{ fontWeight: 600 }}>{theme.hint || "(no hint)"}</div>
        </div>
        <div style={{ fontSize: 12, background: "#f5f5f5", padding: "4px 8px", borderRadius: 999 }}>
          {theme.size} items
        </div>
      </div>
      <button onClick={() => setOpen(v => !v)} style={{ marginTop: 8 }}>
        {open ? "Hide tickets" : "Show tickets"}
      </button>
      {open && (
        <ul style={{ marginTop: 8 }}>
          {theme.tickets.map((t, i) => (
            <li key={i}>
              <a href={t.url} target="_blank" rel="noreferrer">{t.title || t.url}</a>
              <span style={{ opacity: 0.6 }}> — {t.source} · {t.type}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
