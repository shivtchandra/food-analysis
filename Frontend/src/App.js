// src/App.js
import React, { useState, useEffect, useRef } from "react";
import { BrowserRouter, Routes, Route, Link, useNavigate } from "react-router-dom";
import MetricsPage from "./MetricsPage";
import bg1 from "./assets/bg1.png";
import bg3 from "./assets/bg3.png";
import "./App.css";
import PhotoSlideshow from "./PhotoSlideshow.jsx";
import StickerField from "./StickerField.jsx";
import ResultsPage from "./ResultsPage.jsx";
import run from "./assets/stickers/run.png";
import burger from "./assets/stickers/burger.png";
import boy from "./assets/stickers/boy.png";
import salad from "./assets/stickers/salad.png";
import eat from "./assets/stickers/eat.png";
import ProfilePage from "./ProfilePage.jsx";
import AnalyticsPage from "./AnalyticsPage.jsx";
import { AuthProvider, useAuth } from "./context/AuthContext";
import LoginPage from "./LoginPage";
import ProtectedRoute from "./ProtectedRoute";


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

const backgrounds = [bg1, bg3];


function PrivateRoute({ children }) {
  const { user } = useAuth();
  if (!user) return <LoginPage />;
  return children;
}

/* ----------------------------
   MAIN APPLICATION
---------------------------- */
function MainApp() {
  const navigate = useNavigate();
  const [report, setReport] = useState(null);
  const [mapped, setMapped] = useState(null);
  const [loading, setLoading] = useState(false);
  const [confirmed, setConfirmed] = useState([]);
  const [final, setFinal] = useState(null);
  const [micros, setMicros] = useState(null);
  const [debugOpen, setDebugOpen] = useState(false);
  const [restaurantDetection, setRestaurantDetection] = useState(null); // AI + Places results
  const [placeInfo, setPlaceInfo] = useState(null);

  // manual add states
  const [manualName, setManualName] = useState("");
  const [manualQty, setManualQty] = useState(1);
  const [manualPortion, setManualPortion] = useState(1);
  const [manualCalories, setManualCalories] = useState("");

  // ---------- network helpers ----------
  const handleFetchJson = async (url, options) => {
    const res = await fetch(url, options);
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(`HTTP ${res.status}: ${txt}`);
    }
    return res.json();
  };

  // ---------- helpers: quantity parsing ----------
  // Accepts a raw string and tries to extract leading quantity patterns like:
  // "1x paneer pizza", "2 x Burger", "3 × Chicken", "1X masala dosa", "1 X idli"
  // Returns { qty: number|null, text: string }
  const parseQuantityPrefix = (s) => {
    if (!s || typeof s !== "string") return { qty: null, text: s || "" };
    // normalize some unicode multiply signs and collapse whitespace
    const normalized = s.replace(/\u00D7/g, "x").replace(/×/g, "x").replace(/\s+/g, " ").trim();
    // regex: optional leading count (digits) optionally followed by '.' or 'x' or 'X' and optional punctuation/spaces
    // Examples matched: "1x", "1 x", "1X", "2.", "2 -", "2)"
    const m = normalized.match(/^\s*(\d+)\s*(?:[xX]|[×]|[.\-:)]|\b)\s*(.*)$/);
    if (m) {
      const qty = Number(m[1]) || null;
      const rest = (m[2] || "").trim();
      return { qty: qty, text: rest || normalized }; // if rest empty, keep normalized fallback
    }
    // Also try patterns like "1 Pizza" (count + space + word)
    const m2 = normalized.match(/^\s*(\d+)\s+(.+)$/);
    if (m2) {
      const qty = Number(m2[1]) || null;
      const rest = (m2[2] || "").trim();
      return { qty: qty, text: rest || normalized };
    }
    return { qty: null, text: normalized };
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

  // ---------- Image upload (preferred) ----------
  const uploadImageWithMicros = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);
    setLoading(true);
    try {
      const data = await handleFetchJson(
        "http://127.0.0.1:8000/analyze_image_with_micronutrients/?include_low_confidence=true",
        { method: "POST", body: formData }
      );
      console.log("analyze_image_with_micronutrients response:", data);
      
      // Use backend-filtered items (already filtered for quantity markers)
      const backendItems = safeArray(data.mapped_items_normalized || data.mapping_result?.mapped_items || data.mapped_items || []);
      
      const parsedItems = backendItems.map((m, idx) => {
        const raw = m.raw_text || m.extracted_text || "";
        const { qty, text } = parseQuantityPrefix(raw);
        return {
          id: idx,
          raw_text: raw,
          extracted_text: text || m.extracted_text || raw,
          quantity: m.quantity || qty || 1,
          portion_mult: m.portion_mult || 1,
          candidates: m.candidates || [],
          selected: (m.candidates && m.candidates.length) ? m.candidates[0].db_item : (text || m.extracted_text || raw),
          selected_score: (m.candidates && m.candidates.length) ? m.candidates[0].score : 0,
          manual_calories: null,
          model_prob: m.model_prob ?? null,
        };
      });
      
      // Use parsed items directly (backend already filtered)
      setConfirmed(parsedItems);
      setFinal(null);
      setMapped(safeObject(data.mapping_result));
      setMicros(safeObject(data));
      setReport(null);
      
      // Store OCR + AI info for later
      const combined = {
        final: data,
        mapping_result: data.mapping_result || null,
        ai_detection: data.ai_detection || null,
        place_candidates: data.place_candidates || null,
        ocr_text_for_ai:
          data.ocr_text_for_ai ||
          (data.mapping_result && (data.mapping_result.ocr_text || data.mapping_result.ocr_text_preview)) ||
          "",
      };

      // If at least one parsed item had an explicit quantity parsed from OCR, prefer ONLY those lines
      // const withQty = parsedItems.filter((it) => it.quantity && it.raw_text && /^(\d+)/.test(it.raw_text.trim()));
      // const itemsToUse = withQty.length > 0 ? withQty : parsedItems;

      // update state but DO NOT auto-navigate — user confirms edits first
      

      try {
        sessionStorage.setItem("food_results", JSON.stringify(combined));
      } catch (err) {
        console.warn("sessionStorage set failed:", err);
      }
    } catch (err) {
      console.error("Image micronutrients upload failed", err);
      alert("Image upload failed — check backend (see console).");
    } finally {
      setLoading(false);
    }
  };

  // ---------- Submit confirmed items ----------
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
      }),
    };
    setLoading(true);
    try {
      const data = await handleFetchJson("http://127.0.0.1:8000/analyze_items/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      console.log("analyze_items response:", data);
      setFinal(safeObject(data));
      setMicros(safeObject(data));

      const combined = { final: data, confirmed };
      try {
        sessionStorage.setItem("food_results", JSON.stringify(combined));
      } catch (err) {
        console.warn("sessionStorage set failed:", err);
      }

      navigate("/results");
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
  const removeConfirmed = (idx) => setConfirmed((prev) => prev.filter((c) => c.id !== idx));

  // ---------- manual add helper ----------
  const addManualItem = () => {
    const name = (manualName || "").trim();
    if (!name) {
      alert("Please enter an item name.");
      return;
    }
    const qty = Number(manualQty) || 1;
    const portion = Number(manualPortion) || 1;
    const manual_cal = manualCalories === "" ? null : Number(manualCalories);
    const newId = Date.now(); // simple unique id
    const newItem = {
      id: newId,
      raw_text: `${qty}x ${name}`,
      extracted_text: name,
      quantity: qty,
      portion_mult: portion,
      candidates: [],
      selected: name,
      selected_score: 100,
      manual_calories: manual_cal,
      model_prob: null
    };
    setConfirmed((prev) => [...prev, newItem]);
    // reset manual form
    setManualName("");
    setManualQty(1);
    setManualPortion(1);
    setManualCalories("");
  };

  const renderMacrosTable = (macros) => {
    if (!macros) return null;
    const m = safeObject(macros);
    return (
      <table className="macros-table">
        <thead>
          <tr><th>Metric</th><th>Value</th></tr>
        </thead>
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

  return (
    <div className="app-shell">

      <StickerField
        count={18}
        stickers={["🥗", "🍎", "🥑", "🍌", "🍓", "🍞", "💪", "🏃‍♀️", "🥕", "🥛", "🍳", "🍪", "🍇"]}
        pngStickers={[run, burger, boy, salad,eat]}
        seed={1234}
      />
      
      <main className="app-main">
        <div className="content-col">
          <header className="header">
            <h1>Food Analysis — Upload Orders or Screenshot</h1>
            <nav style={{ marginLeft: "auto" }}>
              <Link to="/metrics" style={{ marginLeft: 12, textDecoration: "none" }}>
                About metrics
              </Link>
                </nav>
                <Link to="/analytics" style={{ textDecoration: "none", padding: "6px 10px", borderRadius: 8, background: "#f0f6ec" }}>
               Analytics
            </Link>
            <Link to="/profile" style={{ textDecoration: "none", padding: "6px 10px", borderRadius: 8, background: "#f0f6ec" }}>
              profile
            </Link>
          </header>

          {/* Upload UI */}
          <section className="ui-card">
            <div className="container" style={{ marginTop: "40px", marginBottom: "40px" }}>
              <div className="card p-4 mb-4" style={{ padding: "25px", marginBottom: "35px" }}>
                <h2 className="form-label" style={{ fontSize: "24px" }}>
                  Upload Screenshot/Receipt
                </h2>
                <div style={{ display: "flex", gap: 8 }}>
                  <input
                    type="file"
                    accept="image/*"
                    style={{ marginTop: "15px", marginBottom: "15px", padding: "10px" }}
                    onChange={uploadImageWithMicros}
                  />
                </div>
                <p className="muted" style={{ marginBottom: 0, fontSize: "14px" }}>
                  Tip: crop to the order lines — less UI chrome improves OCR.
                </p>
                {loading && <div className="loader">Analyzing…</div>}
              </div>
            </div>
          </section>

          {/* OCR Preview */}
          <section className="ui-card" style={{ padding: "25px", marginBottom: "35px" }}>
            <h2 style={{ fontSize: "16px" }}>OCR Preview</h2>
            <div className="ocr-box">
              {mapped ? mapped.ocr_text || mapped.ocr_text_preview || "(no OCR text)" : "(no OCR text)"}
            </div>
          </section>

          {/* Manual add form */}
          <section className="ui-card" style={{ padding: "18px 25px", marginBottom: "18px" }}>
            <h3 style={{ marginBottom: 8 }}>Add item manually</h3>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <input
                placeholder="Item name (e.g. Paneer Pizza)"
                value={manualName}
                onChange={(e) => setManualName(e.target.value)}
                style={{ flex: "1 1 280px", padding: "8px" }}
              />
              <input
                type="number"
                min="1"
                value={manualQty}
                onChange={(e) => setManualQty(e.target.value)}
                style={{ width: 80, padding: "8px" }}
                aria-label="Quantity"
              />
              <input
                type="number"
                min="0.1"
                step="0.1"
                value={manualPortion}
                onChange={(e) => setManualPortion(e.target.value)}
                style={{ width: 100, padding: "8px" }}
                aria-label="Portion multiplier"
              />
              <input
                type="number"
                min="0"
                value={manualCalories}
                onChange={(e) => setManualCalories(e.target.value)}
                placeholder="Manual calories (optional)"
                style={{ width: 160, padding: "8px" }}
              />
              <button className="btn btn-secondary" onClick={addManualItem} style={{ padding: "8px 12px" }}>
                Add item
              </button>
            </div>
            <small className="muted" style={{ display: "block", marginTop: 8 }}>
              Tip: fill quantity and portion for accurate totals; manual calories are used if FDC lookup fails.
            </small>
          </section>

          {/* Editable Items */}
          <section className="items-section" style={{ padding: "25px", marginTop: "35px" }}>
            <h2 style={{ marginBottom: "15px" }}>Detected & Editable Items</h2>
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
                        <option key={i} value={opt.db_item}>
                          {opt.db_item} ({opt.score})
                        </option>
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
                    <input
                      className="small-input"
                      type="number"
                      min="0.25"
                      step="0.25"
                      value={it.quantity}
                      onChange={(e) => updateConfirmed(it.id, { quantity: Number(e.target.value) })}
                    />
                    <label className="label small">Portion</label>
                    <input
                      className="small-input"
                      type="number"
                      min="0.25"
                      step="0.1"
                      value={it.portion_mult}
                      onChange={(e) => updateConfirmed(it.id, { portion_mult: Number(e.target.value) })}
                    />
                    <label className="label small">Manual calories</label>
                    <input
                      className="small-input"
                      type="number"
                      min="0"
                      value={it.manual_calories || ""}
                      onChange={(e) => updateConfirmed(it.id, {
                        manual_calories: e.target.value ? Number(e.target.value) : null,
                      })}
                    />
                  </div>

                  <div className="item-right">
                    <button className="btn btn-ghost" onClick={() => removeConfirmed(it.id)}>
                      Remove
                    </button>
                  </div>
                </div>
              ))}
            </div>

            <div className="actions">
              <button
                className="btn btn-primary"
                style={{ marginTop: "30px", padding: "10px 20px", fontSize: "16px" }}
                onClick={submitConfirmed}
              >
                Confirm & Calculate
              </button>
            </div>
          </section>
        </div>

        {/* <aside className="photo-panel" aria-hidden="true">
          <div className="photo-card">
            <PhotoSlideshow images={[bg1, bg3]} interval={5000} blur parallax />
          </div>
        </aside> */}
      </main>

      <footer className="footer">
        <small>Built for prototype & testing — don't use for medical/clinical decisions.</small>
      </footer>
    </div>
  );
}

/* ---------- Wrapper for useNavigate ---------- */
function MainAppWrapper() {
  const navigate = useNavigate();
  return <MainApp navigate={navigate} />;
}

/* ---------- App Routes ---------- */
// export default function App() {
//   return (
//     <AuthProvider>
//     <BrowserRouter>
//       <Routes>
//       <Route
//             path="/"
//             element={
//               <ProtectedRoute>
//                 <MainAppWrapper />
//               </ProtectedRoute>
//             }
//           />
          
//         <Route path="/" element={<MainAppWrapper />} />
//         <Route path="/metrics" element={<MetricsPage />} />
//         <Route path="/results" element={<ResultsPage />} />
//         <Route path="*" element={<MainAppWrapper />} />
//         <Route path="/profile" element={<ProfilePage />} />
//         <Route path="/analytics" element={<AnalyticsPage />} />

//       </Routes>
//     </BrowserRouter>
//     </AuthProvider>
//   );
// }
export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>

          {/* 🔐 Login route - public */}
          <Route path="/login" element={<LoginPage />} />

          {/* 🔒 Protected routes */}
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <MainAppWrapper />
              </ProtectedRoute>
            }
          />

          <Route
            path="/profile"
            element={
              <ProtectedRoute>
                <ProfilePage />
              </ProtectedRoute>
            }
          />

          <Route
            path="/analytics"
            element={
              <ProtectedRoute>
                <AnalyticsPage />
              </ProtectedRoute>
            }
          />

          <Route
            path="/metrics"
            element={
              <ProtectedRoute>
                <MetricsPage />
              </ProtectedRoute>
            }
          />

          <Route
            path="/results"
            element={
              <ProtectedRoute>
                <ResultsPage />
              </ProtectedRoute>
            }
          />

          {/* fallback */}
          <Route path="*" element={<LoginPage />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
