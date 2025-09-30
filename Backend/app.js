// src/App.js
import React, { useState ,  useEffect, useRef} from "react";
import { BrowserRouter, Routes, Route, Link } from "react-router-dom";
import MetricsPage from "./MetricsPage";
import bg1 from "./assets/bg1.png";
import bg3 from "./assets/bg3.png";
import "./App.css";
import PhotoSlideshow from "./PhotoSlideshow.jsx";
/*
  Full, defensive App.js that:
   - Uses safe helpers to avoid "object null is not iterable" errors
   - Renders OCR results, editable matches, macros, micronutrients & %DV
   - Calls backend endpoints:
       POST /analyze/            (CSV)
       POST /analyze_image/      (image -> mapping only)
       POST /analyze_image_with_micronutrients/ (image -> mapping + FDC micronutrients)
       POST /analyze_items/      (confirm list -> micronutrients & macros)
       POST /confirm_mappings/   (legacy macros-only confirm)
   - Shows raw response details for debugging
*/

// ---------- Safe helpers ----------
const safeEntries = (obj) => (obj && typeof obj === "object" ? Object.entries(obj) : []);
const safeArray = (arr) => (Array.isArray(arr) ? arr : []);
const safeObject = (obj) => (obj && typeof obj === "object" ? obj : {});
const pctToLabel = (pct) => {
  if (pct === null || pct === undefined) return { label: "No data", category: "unknown" };
  if (pct >= 20) return { label: "High", category: "high" };
  if (pct >= 5) return { label: "Moderate", category: "moderate" };
  return { label: "Low", category: "low" };
};

// small badge component
function Badge({ category, label }) {
  const base = { padding: "4px 8px", borderRadius: 12, fontSize: 12, display: "inline-block" };
  const style =
    category === "high"
      ? { background: "#dff8e6", color: "#12621a" }
      : category === "moderate"
      ? { background: "#fff4d0", color: "#7a5a00" }
      : category === "low"
      ? { background: "#ffecec", color: "#7a231f" }
      : { background: "#eee", color: "#333" };
  return <span style={{ ...base, ...style }}>{label}</span>;
}

const backgrounds = [bg1,bg3]

/* ----------------------------
   RENAME NOTE:
   We rename the big component to MainApp so the bottom wrapper can render <MainApp />
   without name conflicts. This is the minimal change required to enable routing.
   ---------------------------- */
function MainApp() {
  const [report, setReport] = useState(null); // csv analyze result
  const [mapped, setMapped] = useState(null); // mapping_result from backend
  const [loading, setLoading] = useState(false);
  const [confirmed, setConfirmed] = useState([]);
  const [final, setFinal] = useState(null); // confirm mappings result
  const [micros, setMicros] = useState(null); // micronutrients response (or analyze_items)
  const [debugOpen, setDebugOpen] = useState(false);

  // ---------- network helpers ----------
  const handleFetchJson = async (url, options) => {
    const res = await fetch(url, options);
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(`HTTP ${res.status}: ${txt}`);
    }
    return res.json();
  };

  // ---------- CSV upload ----------
  const uploadCSV = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);
    setLoading(true);
    try {
      const data = await handleFetchJson("http://127.0.0.1:8000/analyze/", { method: "POST", body: formData });
      console.log("CSV analyze:", data);
      setReport(data);
      setMapped(null);
      setFinal(null);
      setMicros(null);
    } catch (err) {
      console.error("CSV upload failed", err);
      alert("CSV upload failed — see console");
    } finally {
      setLoading(false);
    }
  };

  // ---------- Image upload that requests micronutrients (preferred) ----------
  const uploadImageWithMicros = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);
    setLoading(true);
    try {
      // call the micronutrients endpoint (includes mapping + FDC lookup)
      const data = await handleFetchJson(
        "http://127.0.0.1:8000/analyze_image_with_micronutrients/?include_low_confidence=true",
        { method: "POST", body: formData }
      );
      console.log("analyze_image_with_micronutrients response:", data);
      setMapped(safeObject(data.mapping_result));
      
      // also populate editable confirmed items from mapping_result
      const items = safeArray(data.mapping_result && data.mapping_result.mapped_items).map((m, idx) => ({
        id: idx,
        raw_text: m.raw_text || m.extracted_text || "",
        extracted_text: m.extracted_text || "",
        quantity: m.quantity || 1,
        portion_mult: m.portion_mult || 1,
        candidates: m.candidates || [],
        selected: (m.candidates && m.candidates.length) ? m.candidates[0].db_item : (m.extracted_text || ""),
        selected_score: (m.candidates && m.candidates.length) ? m.candidates[0].score : 0,
        manual_calories: null,
        model_prob: m.model_prob ?? null
      }));
      setConfirmed(items);
      setFinal(null);
    } catch (err) {
      console.error("Image micronutrients upload failed", err);
      alert("Image upload failed — check backend (see console).");
    } finally {
      setLoading(false);
    }
  };

  // ---------- Image upload that requests mapping only (legacy) ----------
  const uploadImage = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);
    setLoading(true);
    try {
      const data = await handleFetchJson("http://127.0.0.1:8000/analyze_image/", { method: "POST", body: formData });
      console.log("analyze_image response:", data);
      setMapped(safeObject(data.mapping_result || data)); // some variants return mapping_result at root
      setMicros(null);
      const items = safeArray((data.mapping_result && data.mapping_result.mapped_items) || data.mapped_items).map((m, idx) => ({
        id: idx,
        raw_text: m.raw_text || m.extracted_text || "",
        extracted_text: m.extracted_text || "",
        quantity: m.quantity || 1,
        portion_mult: m.portion_mult || 1,
        candidates: m.candidates || [],
        selected: (m.candidates && m.candidates.length) ? m.candidates[0].db_item : (m.extracted_text || ""),
        selected_score: (m.candidates && m.candidates.length) ? m.candidates[0].score : 0,
        manual_calories: null,
        model_prob: m.model_prob ?? null
      }));
      setConfirmed(items);
      setFinal(null);
    } catch (err) {
      console.error("Image mapping upload failed", err);
      alert("Image upload failed — check backend (see console).");
    } finally {
      setLoading(false);
    }
  };

  // ---------- Submit confirmed items to compute macros & micros ----------
  const submitConfirmed = async () => {
    if (!confirmed.length) {
      alert("No items to confirm.");
      return;
    }
    const payload = {
      confirmed: confirmed.map((c) => {
        const out = { item: c.selected, quantity: Number((c.quantity * c.portion_mult).toFixed(3)), portion_mult: c.portion_mult };
        if (c.manual_calories !== null && c.manual_calories !== "") out.calories = Number(c.manual_calories);
        return out;
      })
    };
    setLoading(true);
    try {
      // analyze_items is expected to return micronutrients + macros for confirmed list
      const data = await handleFetchJson("http://127.0.0.1:8000/analyze_items/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      console.log("analyze_items response:", data);
      setFinal(safeObject(data));
      setMicros(safeObject(data));
      // update mapping UI maybe with cleaned rows
      setMapped((prev) => prev);
    } catch (err) {
      console.error("submitConfirmed error", err);
      alert("Submit failed — see console.");
    } finally {
      setLoading(false);
    }
  };

  const updateConfirmed = (idx, patch) => {
    setConfirmed((prev) => prev.map((c) => (c.id === idx ? { ...c, ...patch } : c)));
  };

  const removeConfirmed = (idx) => {
    setConfirmed((prev) => prev.filter((c) => c.id !== idx));
  };

  // ---------- small UI helpers ----------
  const renderMacrosTable = (macros) => {
    if (!macros) {
      return (
        <table className="macros-table">
          <thead><tr><th>Metric</th><th>Value</th></tr></thead>
          <tbody>
            <tr><td>Calories</td><td>—</td></tr>
            <tr><td>Protein (g)</td><td>—</td></tr>
            <tr><td>Carbs (g)</td><td>—</td></tr>
            <tr><td>Fat (g)</td><td>—</td></tr>
            <tr><td>Fiber (g)</td><td>—</td></tr>
            <tr><td>Sugar (g)</td><td>—</td></tr>
          </tbody>
        </table>
      );
    }
    const m = safeObject(macros);
    return (
      <table className="macros-table">
        <thead><tr><th>Metric</th><th>Value</th></tr></thead>
        <tbody>
          <tr><td>Calories</td><td>{m.total_calories ?? m.calories_kcal ?? "—"}</td></tr>
          <tr><td>Protein (g)</td><td>{m.total_protein ?? m.protein_g ?? "—"}</td></tr>
          <tr><td>Carbs (g)</td><td>{m.total_carbs ?? m.total_carbohydrate_g ?? "—"}</td></tr>
          <tr><td>Fat (g)</td><td>{m.total_fat ?? m.total_fat_g ?? "—"}</td></tr>
          <tr><td>Fiber (g)</td><td>{m.total_fiber ?? m.dietary_fiber_g ?? "—"}</td></tr>
          <tr><td>Sugar (g)</td><td>{m.total_sugar ?? m.sugars_g ?? "—"}</td></tr>
        </tbody>
      </table>
    );
  };
 
  // ---------- render ----------
  return (
    <div className="app-shell">
      <main className="app-main">
      <header className="header">
        <h1>Food Analysis — Upload Orders or Screenshot</h1>
        <nav style={{ marginLeft: "auto" }}>
          {/* Link will work because AppWrapper (below) wraps MainApp with BrowserRouter */}
          <Link to="/metrics" style={{ marginLeft: 12, textDecoration: "none" }}>About metrics</Link>
        </nav>
      </header>

      
        <section className="ui-card">
          {/* <div className="card">
            <h3>Upload CSV</h3>
            <input type="file" accept=".csv" onChange={uploadCSV} />
            {report && (
              <div className="summary">
                <div className="summary-row"><b>Calories:</b> {report.summary?.total_calories ?? "—"}</div>
                <div className="summary-row"><b>Protein:</b> {report.summary?.total_protein ?? "—"} g</div>
                <div className="summary-row"><b>Carbs:</b> {report.summary?.total_carbs ?? "—"} g</div>
                <div className="summary-row"><b>Fat:</b> {report.summary?.total_fat ?? "—"} g</div>
                <div className="summary-row"><b>Fiber:</b> {report.summary?.total_fiber ?? "—"} g</div>
                <div className="summary-row"><b>Sugar:</b> {report.summary?.total_sugar ?? "—"} g</div>
                <div className="insights">
                  <h4>Insights</h4>
                  <ul>{safeArray(report.insights).map((i, idx) => <li key={idx}>{i}</li>)}</ul>
                </div>
              </div>
            )}
          </div> */}
          
        <div className="container" style={{ marginTop: '40px', marginBottom: '40px' }}>
          <div className="card p-4 mb-4 " style={{ padding: '25px', marginBottom: '35px' }}>
            <h2 className="form-label" style={{ fontSize: '24px' }}>Upload Screenshot/Receipt</h2>
            <div style={{ display: "flex", gap: 8 }}>
              <input type="file" accept="image/*" style={{ marginTop:'15px' , marginBottom: '15px', padding: '10px' }} onChange={uploadImageWithMicros} />
              <button className="btn btn-success btn-lg"  style={{ padding: '12px 25px', fontSize: '16px', marginLeft: '400px' }} onClick={() => document.querySelector('input[type="file"]').click()}>Map only</button>
            </div>
            <p className="muted" style={{ marginBottom: 0, fontSize: '14px' }}>Tip: crop to the order lines — less UI chrome improves OCR.</p>
            {loading && <div className="loader">Analyzing…</div>}
          </div>
          </div>
        </section>
        <aside className="photo-panel" aria-hidden="true">
  <div className="photo-card">
    <PhotoSlideshow images={[bg1, bg3]} interval={5000} />
  </div>
</aside>
        <section className="ui-card" style={{ padding: '25px', marginBottom: '35px' }}>
          <h2 style={{ fontSize: '16px' }}>OCR Preview</h2>
          <div className="ocr-box">{mapped ? mapped.ocr_text || mapped.ocr_text_preview || "(no OCR text)" : "(no OCR text)"}</div>
        </section>
        <section className="items-section" style={{ padding: '25px', marginTop: '35px' }}>
          <h2 style={{ marginBottom: '15px' }}>Detected & Editable Items</h2>

          {confirmed.length === 0 && <p className="muted">No detected items yet — upload an image or CSV.</p>}

          <div className="items-list">
            {confirmed.map((it) => (
              <div key={it.id} className="item-row" aria-live="polite">
                <div className="item-left">
                  <div className="label">Raw</div>
                  <div className="raw">{it.raw_text}</div>
                  <div className="muted small">{it.extracted_text}</div>
                </div>

                <div className="item-middle">
                  <div className="label">Match (pick or edit)</div>
                  <select
                    aria-label="Choose match"
                    value={it.selected}
                    onChange={(e) => updateConfirmed(it.id, { selected: e.target.value })}
                    className="select"
                  >
                    {safeArray(it.candidates).map((opt, i) => (
                      <option key={i} value={opt.db_item}>{opt.db_item} ({opt.score})</option>
                    ))}
                    <option value={it.extracted_text}>Use raw: {it.extracted_text}</option>
                  </select>
                  {it.model_prob !== null && (
                    <div className={`chip ${it.model_prob < 0.6 ? "chip-warn" : "chip-ok"}`}>
                      model {Math.round((it.model_prob || 0) * 100)}%
                    </div>
                  )}
                </div>

                <div className="item-controls">
                  <label className="label small">Quantity</label>
                  <input className="small-input" type="number" min="0.25" step="0.25" value={it.quantity} onChange={(e) => updateConfirmed(it.id, { quantity: Number(e.target.value) })} />

                  <label className="label small">Portion</label>
                  <input className="small-input" type="number" min="0.25" step="0.1" value={it.portion_mult} onChange={(e) => updateConfirmed(it.id, { portion_mult: Number(e.target.value) })} />

                  <label className="label small">Manual calories</label>
                  <input className="small-input" type="number" min="0" value={it.manual_calories || ""} onChange={(e) => updateConfirmed(it.id, { manual_calories: e.target.value ? Number(e.target.value) : null })} />
                </div>

                <div className="item-right">
                  <button className="btn btn-ghost" onClick={() => removeConfirmed(it.id)}>Remove</button>
                </div>
              </div>
            ))}
          </div>


          <div className="actions">
            <button className="btn btn-primary" style={{ marginTop:'30px',padding: '10px 20px', fontSize: '16px' }}onClick={submitConfirmed}>Confirm & Calculate</button>
          </div>
        </section>
        

        {/* Final macros summary */}
        {final && (
          <section className="final-section">
            <h2>Final Nutrition Summary</h2>
            {renderMacrosTable(final.summary || final.macros_summary)}
            <div className="insights">
              <h4>Insights</h4>
              <ul>{safeArray(final.insights).map((i, idx) => <li key={idx}>{i}</li>)}</ul>
            </div>
          </section>
        )}

        {/* Micronutrients & %DV */}
        {micros && (
          <section className="final-section">
            <section style={{ marginTop: 24 }}>
              <h2>Micronutrients & %DV</h2>

              <details style={{ whiteSpace: "pre-wrap", marginBottom: 12 }}>
                <summary onClick={() => setDebugOpen((v) => !v)}>{debugOpen ? "Hide" : "Raw response (click to expand)"}</summary>
                {debugOpen && <pre style={{ maxHeight: 360, overflow: "auto" }}>{JSON.stringify(micros, null, 2)}</pre>}
              </details>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 360px", gap: 20 }}>
                <div>
                  <h4>Totals</h4>
                  {safeEntries(micros.micronutrient_totals).length > 0 ? (
                    <table className="nutrients-table">
                      <thead><tr><th>Nutrient</th><th>Amount</th></tr></thead>
                      <tbody>
                        {safeEntries(micros.micronutrient_totals).map(([k, v]) => (
                          <tr key={k}><td>{k.replace(/_/g, " ")}</td><td>{v === null || v === undefined ? "—" : v}</td></tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <div>No micronutrient totals available (FDC lookup may have failed or no data returned).</div>
                  )}
                </div>

                <div>
                  <h4>% Daily Values</h4>
                  {safeEntries(micros.percent_dv_friendly || micros.percent_dv || {}).length > 0 ? (
                    <div>
                      {safeEntries(micros.percent_dv_friendly || micros.percent_dv || {}).map(([k, obj]) => {
                        // obj might be number or {pct,label,category}
                        const pct = obj && typeof obj === "object" && obj.pct !== undefined ? obj.pct : (typeof obj === "number" ? obj : null);
                        const friendly = pctToLabel(pct);
                        return (
                          <div key={k} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 0", borderBottom: "1px solid #f0f0f0" }}>
                            <div style={{ flex: 1 }}>
                              <strong>{k.replace(/_/g, " ")}</strong>
                              <div style={{ fontSize: 12, color: "#666" }}>{pct === null ? "No data" : `${pct}% DV`}</div>
                            </div>
                            <div style={{ width: 140, textAlign: "right" }}>
                              <Badge category={friendly.category} label={friendly.label} />
                            </div>
                          </div>
                        );
                      })}
                      <div style={{ marginTop: 10, fontSize: 13 }}>
                        <strong>Legend:</strong> <span style={{ marginLeft: 8 }}>High ≥20% — Moderate 5–19% — Low &lt;5%</span>
                      </div>
                      <div style={{ marginTop: 8 }}>
                        <small style={{ color: "#444" }}>Tip: %DV is based on FDA daily values (typical adult). Use as a directional guide.</small>
                      </div>
                    </div>
                  ) : (
                    <div>No %DV information available.</div>
                  )}
                </div>
              </div>

              <div style={{ marginTop: 18 }}>
                <h4>Top lacking nutrients</h4>
                {safeArray(micros.top_lacking).length > 0 ? (
                  <ol>
                    {safeArray(micros.top_lacking).map((pair, idx) => {
                      if (!pair) return null;
                      const [k, v] = pair;
                      return <li key={idx}>{k.replace(/_/g, " ")}: {v}% DV</li>;
                    })}
                  </ol>
                ) : (
                  <div>No top-lacking nutrients available.</div>
                )}
              </div>
             
              <div style={{ marginTop: 18 }}>
                <h4>Per-item provenance (first 8)</h4>
                {safeArray(micros.per_item_provenance).length > 0 ? (
                  <div>
                    {safeArray(micros.per_item_provenance).slice(0, 8).map((p, idx) => (
                      <div key={idx} style={{ padding: 8, border: "1px solid #f0f0f0", borderRadius: 6, marginBottom: 6 }}>
                        <div><strong>{p.mapped_to || p.raw || p.raw_text}</strong></div>
                        <div style={{ fontSize: 12, color: "#666" }}>
                          {p.provenance && p.provenance.fdcId ? `${p.provenance.description || ""} • fdc:${p.provenance.fdcId}` : JSON.stringify(p.provenance)}
                        </div>
                        <div style={{ fontSize: 12, color: "#555", marginTop: 4 }}>qty: {p.quantity ?? p.qty ?? 1}{p.portion_mult ? ` • portion: ${p.portion_mult}` : ""}</div>
                      </div>
                    ))}
                  </div>
                ) : <div>No per-item provenance returned.</div>}
              </div>
            </section>
          </section>
        )}

      </main>

      <footer className="footer">
        <small>Built for prototype & testing — don't use for medical/clinical decisions.</small>
      </footer>
      
    </div>
  );
}

/* Top-level wrapper — provides Router and routes.
   IMPORTANT: this uses <MainApp /> (the big component above) and MetricsPage.
   This is the single default export for the module.
*/
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<MainApp />} />
        <Route path="/metrics" element={<MetricsPage />} />
        <Route path="*" element={<MainApp />} />
      </Routes>
    </BrowserRouter>
  );
}
