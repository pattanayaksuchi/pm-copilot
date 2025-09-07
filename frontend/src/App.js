import React, { useEffect, useMemo, useState } from "react";

const API = "http://localhost:8000";

export default function App() {
  // Controls
  const [days, setDays] = useState(30);
  const [k, setK] = useState(12);
  const [source, setSource] = useState("all"); // all|slack|zendesk|jira
  const [kind, setKind] = useState("all");     // all|issue|feature_request|unknown
  const [vertical, setVertical] = useState("all"); // all or vertical slug/name
  const [includeInternal, setIncludeInternal] = useState(false); // exclude internal by default

  // Static list of product verticals (slugs) for filter UX; keep in sync with backend
  const VERTICAL_OPTIONS = [
    ["all", "All"],
    ["multicurrency-accounts-wallets", "Multicurrency Accounts and Wallets"],
    ["fee-engine-invoicing", "Fee Engine and Invoicing"],
    ["payins-direct-debits", "Payins and Direct Debits"],
    ["fx-service", "FX Service"],
    ["treasury-management-gl", "Treasury Management and GL Spoc"],
    ["payouts-reliability-api", "Payouts Reliability and API Experience"],
    ["swift-connect", "Swift Connect"],
    ["network-payouts", "Network Payouts"],
    ["global-wires", "Global wires"],
    ["verify", "Verify"],
    ["client-onboarding", "Client Onboarding"],
    ["customer-onboarding", "Customer Onboarding"],
    ["caas", "CaaS"],
    ["data-reporting", "Data and Reporting"],
    ["b2b-travel", "B2B Travel"],
    ["platform-issuing", "Platform Issuing"],
    ["api-docs", "API and API Docs"],
    ["client-portal", "Client Portal"],
  ];

  // Data
  const [themes, setThemes] = useState(null);
  const [top, setTop] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);
  const [review, setReview] = useState([]);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewPerBin, setReviewPerBin] = useState(20);
  const [reviewDays, setReviewDays] = useState(30);

  // Chat state
  const [chatQ, setChatQ] = useState("");
  const [chatAnswer, setChatAnswer] = useState("");
  const [chatResults, setChatResults] = useState([]);
  const [chatLoading, setChatLoading] = useState(false);

  const qs = useMemo(() => {
    const p = new URLSearchParams({ days: String(days), k: String(k), source, kind, vertical, include_internal: String(includeInternal) });
    return p.toString();
  }, [days, k, source, kind, vertical, includeInternal]);

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

  const askChat = async () => {
    if (!chatQ.trim()) return;
    setChatLoading(true); setErr(null); setChatAnswer(""); setChatResults([]);
    try {
      const res = await fetch(`${API}/chat/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: chatQ,
          days,
          top_k: 5,
          source,
          kind,
          vertical,
          include_internal: includeInternal,
        })
      });
      const data = await res.json();
      setChatAnswer(data.answer || "");
      setChatResults(data.results || []);
    } catch (e) {
      setErr(String(e));
    } finally {
      setChatLoading(false);
    }
  };

  const loadReview = async () => {
    setReviewLoading(true); setErr(null);
    try {
      const url = `${API}/review/sample?days=${reviewDays}&per_bin=${reviewPerBin}`;
      const res = await fetch(url);
      const data = await res.json();
      const items = (data.items || []).map(it => ({ ...it, gold_vertical_slug: it.pred_vertical_slug || "" }));
      setReview(items);
    } catch (e) {
      setErr(String(e));
    } finally {
      setReviewLoading(false);
    }
  };

  const saveReview = async () => {
    const items = review.filter(r => r.gold_vertical_slug && r.gold_vertical_slug !== r.pred_vertical_slug)
      .map(r => ({ ticket_id: r.ticket_id, vertical_slug: r.gold_vertical_slug }));
    if (items.length === 0) return;
    setReviewLoading(true);
    try {
      const res = await fetch(`${API}/review/labels`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reviewer: 'ui', items })
      });
      const data = await res.json();
      // Reload themes/top afterwards to reflect overrides if needed
      await fetchThemes();
    } catch (e) {
      setErr(String(e));
    } finally {
      setReviewLoading(false);
    }
  };

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
        <label>Product:
          <select value={vertical} onChange={e => setVertical(e.target.value)} style={{ marginLeft: 6 }}>
            {VERTICAL_OPTIONS.map(([val, label]) => (
              <option key={val} value={val}>{label}</option>
            ))}
          </select>
        </label>
        <label>
          <input type="checkbox" checked={includeInternal} onChange={e => setIncludeInternal(e.target.checked)} style={{ marginLeft: 6, marginRight: 6 }} />
          Include internal
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

      {/* Chat Section */}
      <Card title="Ask a Question">
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <input
            value={chatQ}
            onChange={e => setChatQ(e.target.value)}
            placeholder="Ask about issues, features, tickets…"
            style={{ flex: 1, padding: 8 }}
            onKeyDown={e => { if (e.key === 'Enter') askChat(); }}
          />
          <button onClick={askChat} disabled={chatLoading}>{chatLoading ? 'Thinking…' : 'Ask'}</button>
        </div>
        {chatAnswer && (
          <div style={{ marginTop: 10 }}>
            <div style={{ marginBottom: 6 }}>{chatAnswer}</div>
            {chatResults?.length > 0 && (
              <ol>
                {chatResults.map((r, i) => (
                  <li key={i}>
                    <a href={r.url} target="_blank" rel="noreferrer">{r.title || r.url}</a>
                    <span style={{ opacity: 0.6 }}> — {r.source} · {r.type} · sim {r.similarity?.toFixed(2)}</span>
                  </li>
                ))}
              </ol>
            )}
          </div>
        )}
      </Card>

      {/* Top 10 Section */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <Card title="Top 10 Issues (Next Sprint)">
          {!top ? <p>Loading…</p> : (
            <ol>
              {top.top_issues?.map((t, i) => (
                <li key={i}>
                  <a href={t.url} target="_blank" rel="noreferrer">{t.title || t.url}</a>
                  <span style={{ opacity: 0.6 }}> — {t.source}{t.product_vertical ? ` · ${t.product_vertical}` : ""}</span>
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
                  <span style={{ opacity: 0.6 }}> — {t.source}{t.product_vertical ? ` · ${t.product_vertical}` : ""}</span>
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

      {/* Review Section */}
      <h2 style={{ marginTop: 24 }}>Review Predictions</h2>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 8 }}>
        <label>Days:
          <input type="number" min="1" max="365" value={reviewDays} onChange={e => setReviewDays(Number(e.target.value))} style={{ marginLeft: 6, width: 80 }} />
        </label>
        <label>Per bin:
          <input type="number" min="1" max="200" value={reviewPerBin} onChange={e => setReviewPerBin(Number(e.target.value))} style={{ marginLeft: 6, width: 80 }} />
        </label>
        <button onClick={loadReview} disabled={reviewLoading}>{reviewLoading ? 'Loading…' : 'Load Sample'}</button>
        <button onClick={saveReview} disabled={reviewLoading || review.length === 0}>Save Labels</button>
      </div>
      {review.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ textAlign: 'left' }}>
                <th>Confidence</th>
                <th>Source</th>
                <th>Title</th>
                <th>Predicted</th>
                <th>Gold (edit)</th>
              </tr>
            </thead>
            <tbody>
              {review.map((r, i) => (
                <tr key={i}>
                  <td style={{ padding: 6 }}>{r.confidence.toFixed(2)}</td>
                  <td style={{ padding: 6 }}>{r.source}</td>
                  <td style={{ padding: 6 }}>
                    {r.url ? <a href={r.url} target="_blank" rel="noreferrer">{r.title || r.url}</a> : (r.title || '(no title)')}
                  </td>
                  <td style={{ padding: 6 }}>{r.pred_vertical_name || r.pred_vertical_slug || '(none)'}</td>
                  <td style={{ padding: 6 }}>
                    <select value={r.gold_vertical_slug}
                      onChange={e => setReview(curr => curr.map((x, j) => j === i ? { ...x, gold_vertical_slug: e.target.value } : x))}
                    >
                      {VERTICAL_OPTIONS.map(([val, label]) => (
                        <option key={val} value={val}>{label}</option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
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
              <span style={{ opacity: 0.6 }}> — {t.source} · {t.type}{t.product_vertical ? ` · ${t.product_vertical}` : ""}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
